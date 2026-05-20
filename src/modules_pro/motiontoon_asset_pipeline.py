from __future__ import annotations

import logging
import shutil
from collections import deque
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from utils.layered_cutout import (
    attach_layered_cutout_assets,
    load_layered_cutout_assets,
    load_layered_cutout_metadata,
)

try:
    from utils.logger import get_logger

    logger = get_logger("motiontoon_asset_pipeline")
except ImportError:
    logger = logging.getLogger(__name__)


_SPRITE_LAYOUTS = {
    "protagonist": {"center_x": 0.52, "center_y": 0.83, "height_ratio": 0.78},
    "deuteragonist": {"center_x": 0.42, "center_y": 0.83, "height_ratio": 0.76},
    "antagonist": {"center_x": 0.58, "center_y": 0.83, "height_ratio": 0.78},
    "elder": {"center_x": 0.49, "center_y": 0.84, "height_ratio": 0.72},
    "support": {"center_x": 0.56, "center_y": 0.84, "height_ratio": 0.72},
    "default": {"center_x": 0.52, "center_y": 0.83, "height_ratio": 0.76},
}
_PIPELINE_MARKER = "simple_sprite_bundle_v5_native_face_parts"


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _safe_float(value: Any, fallback: float) -> float:
    try:
        if value is None or value == "":
            return float(fallback)
        return float(value)
    except Exception:
        return float(fallback)


def _resolve_sprite_layout(
    rig: Dict[str, Any],
    foreground_size: Tuple[int, int],
    slot_name: str,
) -> Dict[str, float]:
    """Resolve scene-level character blocking without falling back to one static slot."""
    slot_layout = _SPRITE_LAYOUTS.get(str(slot_name or "").strip().lower(), _SPRITE_LAYOUTS["default"])
    aspect_ratio = foreground_size[0] / max(1, foreground_size[1])
    height_ratio = _clamp(
        _safe_float(rig.get("sprite_height_ratio"), float(slot_layout["height_ratio"])),
        0.42,
        0.88,
    )
    default_width = height_ratio * aspect_ratio
    width_ratio = _clamp(
        _safe_float(rig.get("sprite_width_ratio"), default_width),
        0.16,
        0.62,
    )
    return {
        "center_x": _clamp(_safe_float(rig.get("sprite_center_x"), float(slot_layout["center_x"])), 0.12, 0.88),
        "center_y": _clamp(_safe_float(rig.get("sprite_center_y"), float(slot_layout["center_y"])), 0.32, 0.96),
        "width_ratio": width_ratio,
        "height_ratio": height_ratio,
    }


def _load_rgba(path: str) -> Image.Image:
    return Image.open(path).convert("RGBA")


def _fill_mask_holes(mask_arr: np.ndarray) -> np.ndarray:
    height, width = mask_arr.shape
    visited = np.zeros((height, width), dtype=np.uint8)
    queue: deque[tuple[int, int]] = deque()

    def _push(x: int, y: int) -> None:
        if 0 <= x < width and 0 <= y < height and not visited[y, x] and mask_arr[y, x] == 0:
            visited[y, x] = 1
            queue.append((x, y))

    for x in range(width):
        _push(x, 0)
        _push(x, height - 1)
    for y in range(height):
        _push(0, y)
        _push(width - 1, y)

    while queue:
        x, y = queue.popleft()
        _push(x - 1, y)
        _push(x + 1, y)
        _push(x, y - 1)
        _push(x, y + 1)

    holes = (mask_arr == 0) & (visited == 0)
    if np.any(holes):
        mask_arr = mask_arr.copy()
        mask_arr[holes] = 255
    return mask_arr


def _retain_largest_component(mask_arr: np.ndarray) -> np.ndarray:
    try:
        import cv2
    except Exception:
        return mask_arr

    binary = np.where(mask_arr > 18, 255, 0).astype(np.uint8)
    if not np.any(binary):
        return mask_arr

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if component_count <= 2:
        return mask_arr

    best_label = 0
    best_area = 0
    for label in range(1, component_count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area > best_area:
            best_area = area
            best_label = label

    if best_label <= 0:
        return mask_arr

    retained = np.where(labels == best_label, mask_arr, 0).astype(np.uint8)
    return retained


def _validate_asset_bundle(assets: Dict[str, str]) -> Dict[str, str]:
    normalized = {key: str(value or "") for key, value in dict(assets or {}).items() if str(value or "")}
    if not normalized:
        return {}
    for key, value in normalized.items():
        if not Path(value).exists():
            return {}
    if not normalized.get("background_path"):
        return {}
    return normalized


def _materialize_image_copy(source_path: str, target_path: Path) -> None:
    try:
        _load_rgba(source_path).save(target_path)
    except Exception:
        shutil.copy2(source_path, target_path)


def _copy_part_asset(
    out_dir: Path,
    stem: str,
    suffix: str,
    source_path: str,
) -> str:
    target_path = out_dir / f"{stem}{suffix}"
    _materialize_image_copy(source_path, target_path)
    return str(target_path)


def _corner_color(image: Image.Image) -> Tuple[int, int, int]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    points = (
        (3, 3),
        (max(0, width - 4), 3),
        (3, max(0, height - 4)),
        (max(0, width - 4), max(0, height - 4)),
    )
    samples = [rgb.getpixel(point) for point in points]
    return tuple(int(sum(channel) / len(samples)) for channel in zip(*samples))


def _fallback_subject_bbox(size: Tuple[int, int]) -> Tuple[int, int, int, int]:
    width, height = size
    return (
        int(width * 0.23),
        int(height * 0.08),
        int(width * 0.77),
        int(height * 0.96),
    )


def _build_border_subject_mask(sprite_image: Image.Image) -> Tuple[Image.Image, Tuple[int, int, int, int] | None]:
    width, height = sprite_image.size
    background_rgb = _corner_color(sprite_image)
    rgb = np.array(sprite_image.convert("RGB"), dtype=np.int32)
    bg = np.array(background_rgb, dtype=np.int32)
    diff_sq = np.sum((rgb - bg) ** 2, axis=2)
    near_bg = diff_sq <= (34 * 34)

    visited = np.zeros((height, width), dtype=np.uint8)
    queue: deque[tuple[int, int]] = deque()

    def _push(x: int, y: int) -> None:
        if 0 <= x < width and 0 <= y < height and not visited[y, x] and near_bg[y, x]:
            visited[y, x] = 1
            queue.append((x, y))

    for x in range(width):
        _push(x, 0)
        _push(x, height - 1)
    for y in range(height):
        _push(0, y)
        _push(width - 1, y)

    while queue:
        x, y = queue.popleft()
        _push(x - 1, y)
        _push(x + 1, y)
        _push(x, y - 1)
        _push(x, y + 1)

    mask_arr = np.where(visited == 1, 0, 255).astype(np.uint8)
    threshold = Image.fromarray(mask_arr)
    threshold = threshold.filter(ImageFilter.MaxFilter(size=5))
    threshold = threshold.filter(ImageFilter.GaussianBlur(radius=max(1, int(min(width, height) * 0.004))))
    threshold = threshold.point(lambda value: 255 if value > 18 else 0)
    return threshold, threshold.getbbox()


def _build_subject_mask(sprite_image: Image.Image) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
    width, height = sprite_image.size
    alpha = sprite_image.getchannel("A")
    alpha_bbox = alpha.point(lambda value: 255 if value > 24 else 0).getbbox()
    if alpha_bbox and alpha_bbox[2] - alpha_bbox[0] < width * 0.94:
        return alpha, alpha_bbox

    try:
        import cv2

        rgb = np.array(sprite_image.convert("RGB"), dtype=np.uint8)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        gc_mask = np.full((height, width), cv2.GC_PR_BGD, dtype=np.uint8)
        rect = (
            int(width * 0.16),
            int(height * 0.04),
            int(width * 0.68),
            int(height * 0.92),
        )
        bg_model = np.zeros((1, 65), np.float64)
        fg_model = np.zeros((1, 65), np.float64)
        cv2.grabCut(bgr, gc_mask, rect, bg_model, fg_model, 5, cv2.GC_INIT_WITH_RECT)
        subject = np.where(
            (gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD),
            255,
            0,
        ).astype(np.uint8)

        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(subject, connectivity=8)
        if component_count > 1:
            best_label = 0
            best_area = 0
            for label in range(1, component_count):
                x, y, w, h, area = stats[label]
                touches_border = x <= 2 or y <= 2 or (x + w) >= width - 2 or (y + h) >= height - 2
                if touches_border:
                    continue
                if area > best_area:
                    best_area = int(area)
                    best_label = label
            if best_label:
                subject = np.where(labels == best_label, 255, 0).astype(np.uint8)

        threshold = Image.fromarray(subject).filter(ImageFilter.MaxFilter(size=5))
        threshold = threshold.filter(ImageFilter.GaussianBlur(radius=max(1, int(min(width, height) * 0.004))))
        threshold = threshold.point(lambda value: 255 if value > 18 else 0)
        bbox = threshold.getbbox()
        if bbox and (bbox[2] - bbox[0]) < width * 0.9 and (bbox[3] - bbox[1]) < height * 0.96:
            border_threshold, border_bbox = _build_border_subject_mask(sprite_image)
            if border_bbox:
                combined = ImageChops.lighter(threshold, border_threshold)
                combined_bbox = combined.getbbox()
                if (
                    combined_bbox
                    and (combined_bbox[2] - combined_bbox[0]) < width * 0.9
                    and (combined_bbox[3] - combined_bbox[1]) < height * 0.96
                ):
                    threshold = combined
                    bbox = combined_bbox
            return threshold, bbox
    except Exception:
        pass

    threshold, bbox = _build_border_subject_mask(sprite_image)

    if not bbox:
        bbox = _fallback_subject_bbox(sprite_image.size)
        threshold = Image.new("L", sprite_image.size, 0)
        draw = ImageDraw.Draw(threshold)
        draw.rounded_rectangle(bbox, radius=max(8, int(min(width, height) * 0.03)), fill=255)
    else:
        bbox_width = bbox[2] - bbox[0]
        bbox_height = bbox[3] - bbox[1]
        if bbox_width >= width * 0.94 or bbox_height >= height * 0.96:
            bbox = _fallback_subject_bbox(sprite_image.size)
            threshold = Image.new("L", sprite_image.size, 0)
            draw = ImageDraw.Draw(threshold)
            draw.rounded_rectangle(bbox, radius=max(8, int(min(width, height) * 0.03)), fill=255)

    return threshold, bbox


def _expand_bbox(
    bbox: Tuple[int, int, int, int],
    size: Tuple[int, int],
    *,
    pad_x: int,
    pad_y: int,
) -> Tuple[int, int, int, int]:
    width, height = size
    left, top, right, bottom = bbox
    return (
        max(0, left - pad_x),
        max(0, top - pad_y),
        min(width, right + pad_x),
        min(height, bottom + pad_y),
    )


def _extract_foreground(sprite_path: str) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
    sprite = _load_rgba(sprite_path)
    mask, bbox = _build_subject_mask(sprite)
    mask_arr = np.array(mask, dtype=np.uint8)
    mask_arr = np.where(mask_arr >= 220, 255, mask_arr)
    mask_arr = np.where(mask_arr <= 18, 0, mask_arr)
    mask_arr = _fill_mask_holes(mask_arr)
    mask = Image.fromarray(mask_arr)

    bbox = _expand_bbox(
        bbox,
        sprite.size,
        pad_x=max(8, int(sprite.size[0] * 0.03)),
        pad_y=max(12, int(sprite.size[1] * 0.045)),
    )
    foreground = Image.new("RGBA", sprite.size, (0, 0, 0, 0))
    foreground.paste(sprite, (0, 0), mask)
    cropped = foreground.crop(bbox)

    rgba = np.array(cropped, dtype=np.uint8)
    crop_alpha = rgba[:, :, 3]
    crop_alpha = np.where(crop_alpha >= 220, 255, crop_alpha)
    crop_alpha = np.where(crop_alpha <= 18, 0, crop_alpha)
    crop_alpha = _retain_largest_component(crop_alpha)
    rgba[:, :, 3] = crop_alpha.astype(np.uint8)
    cleaned = Image.fromarray(rgba)
    trimmed_bbox = cleaned.getchannel("A").point(lambda value: 255 if value > 10 else 0).getbbox()
    if trimmed_bbox:
        pad_x = max(6, int(cleaned.width * 0.03))
        pad_top = max(12, int(cleaned.height * 0.06))
        pad_bottom = max(8, int(cleaned.height * 0.035))
        expanded_trimmed = (
            max(0, trimmed_bbox[0] - pad_x),
            max(0, trimmed_bbox[1] - pad_top),
            min(cleaned.width, trimmed_bbox[2] + pad_x),
            min(cleaned.height, trimmed_bbox[3] + pad_bottom),
        )
        cleaned = cleaned.crop(expanded_trimmed)
        bbox = (
            bbox[0] + expanded_trimmed[0],
            bbox[1] + expanded_trimmed[1],
            bbox[0] + expanded_trimmed[2],
            bbox[1] + expanded_trimmed[3],
        )

    return cleaned, bbox


def _face_anchor_for_crop(
    full_size: Tuple[int, int],
    crop_bbox: Tuple[int, int, int, int],
    rig: Dict[str, Any],
) -> Tuple[float, float]:
    width, height = full_size
    left, top, right, bottom = crop_bbox
    crop_width = max(1, right - left)
    crop_height = max(1, bottom - top)
    anchor_x = float(rig.get("face_anchor_x", 0.5) or 0.5) * width
    anchor_y = float(rig.get("face_anchor_y", 0.28) or 0.28) * height
    local_x = _clamp((anchor_x - left) / crop_width, 0.22, 0.78)
    local_y = _clamp((anchor_y - top) / crop_height, 0.14, 0.52)
    return local_x, local_y


def _build_face_overlay_assets(
    out_dir: Path,
    stem: str,
    sprite_size: Tuple[int, int],
    *,
    rig: Dict[str, Any],
    include_eyes: bool = False,
) -> Dict[str, str]:
    width, height = sprite_size
    eyes_open_path = out_dir / f"{stem}__eyes_open.png"
    eyes_closed_path = out_dir / f"{stem}__eyes_closed.png"
    mouth_closed_path = out_dir / f"{stem}__mouth_closed.png"
    mouth_open_path = out_dir / f"{stem}__mouth_open.png"

    local_anchor_x = float(rig.get("face_anchor_x", 0.5) or 0.5)
    local_anchor_y = float(rig.get("face_anchor_y", 0.26) or 0.26)
    face_scale = _clamp(float(rig.get("face_scale", 1.0) or 1.0), 0.75, 1.25)
    emotion_hint = str(rig.get("emotion_hint", "") or "").strip().lower()

    eye_width = max(10, int(width * 0.11 * face_scale))
    eye_height = max(5, int(height * 0.022 * face_scale))
    eye_gap = max(10, int(width * 0.14 * face_scale))
    eye_y = int(height * local_anchor_y)
    center_x = int(width * local_anchor_x)
    mouth_y = int(height * _clamp(local_anchor_y + 0.16, 0.22, 0.76))

    line_color = (18, 18, 18, 245)
    fill_color = (250, 250, 250, 230)
    if emotion_hint in {"fear", "scared", "worried"}:
        eye_height = max(7, int(eye_height * 1.6))
    elif emotion_hint in {"sad", "calm"}:
        eye_height = max(4, int(eye_height * 0.9))
        mouth_y += 2

    def _canvas() -> Image.Image:
        return Image.new("RGBA", sprite_size, (0, 0, 0, 0))

    eyes_open = _canvas()
    eyes_closed = _canvas()
    mouth_closed = _canvas()
    mouth_open = _canvas()
    eo = ImageDraw.Draw(eyes_open)
    ec = ImageDraw.Draw(eyes_closed)
    mc = ImageDraw.Draw(mouth_closed)
    mo = ImageDraw.Draw(mouth_open)

    left_eye = (
        center_x - eye_gap - eye_width // 2,
        eye_y,
        center_x - eye_gap + eye_width // 2,
        eye_y + eye_height,
    )
    right_eye = (
        center_x + eye_gap - eye_width // 2,
        eye_y,
        center_x + eye_gap + eye_width // 2,
        eye_y + eye_height,
    )
    eo.arc(left_eye, start=180, end=360, fill=line_color, width=3)
    eo.arc(right_eye, start=180, end=360, fill=line_color, width=3)
    eo.rectangle((left_eye[0] + 4, left_eye[1] + 2, left_eye[2] - 4, left_eye[3] + 2), fill=fill_color)
    eo.rectangle((right_eye[0] + 4, right_eye[1] + 2, right_eye[2] - 4, right_eye[3] + 2), fill=fill_color)
    ec.line((left_eye[0], eye_y + eye_height // 2, left_eye[2], eye_y + eye_height // 2), fill=line_color, width=3)
    ec.line((right_eye[0], eye_y + eye_height // 2, right_eye[2], eye_y + eye_height // 2), fill=line_color, width=3)

    closed_box = (
        center_x - max(8, int(width * 0.055 * face_scale)),
        mouth_y,
        center_x + max(8, int(width * 0.055 * face_scale)),
        mouth_y + max(3, int(height * 0.012 * face_scale)),
    )
    open_box = (
        center_x - max(10, int(width * 0.07 * face_scale)),
        mouth_y - max(1, int(height * 0.01 * face_scale)),
        center_x + max(10, int(width * 0.07 * face_scale)),
        mouth_y + max(10, int(height * 0.06 * face_scale)),
    )
    mc.rounded_rectangle(closed_box, radius=4, fill=line_color)
    mo.rounded_rectangle(open_box, radius=8, fill=line_color)
    mo.rounded_rectangle(
        (
            open_box[0] + 4,
            open_box[1] + 4,
            open_box[2] - 4,
            open_box[3] - 4,
        ),
        radius=6,
        fill=(0, 0, 0, 0),
        outline=fill_color,
        width=2,
    )

    if include_eyes:
        eyes_open.save(eyes_open_path)
        eyes_closed.save(eyes_closed_path)
    mouth_closed.save(mouth_closed_path)
    mouth_open.save(mouth_open_path)
    return {
        "eyes_open_path": str(eyes_open_path) if include_eyes else "",
        "eyes_closed_path": str(eyes_closed_path) if include_eyes else "",
        "mouth_closed_path": str(mouth_closed_path),
        "mouth_open_path": str(mouth_open_path),
    }


class MotiontoonAssetPipeline:
    """Build explicit background + sprite + face-overlay assets for motiontoon scenes."""

    def build_scene_assets(
        self,
        scene_image_path: str,
        *,
        background_source_path: str,
        sprite_source_path: str = "",
        layer_part_overrides: Dict[str, str] | None = None,
        face_part_overrides: Dict[str, str] | None = None,
        rig_overrides: Dict[str, Any] | None = None,
        overlay_kind: str = "",
    ) -> Dict[str, str]:
        scene_path = Path(scene_image_path)
        if not scene_path.exists():
            return {}

        cached = load_layered_cutout_assets(str(scene_path), overlay_kind=overlay_kind, min_strength=0.82)
        if cached:
            meta = load_layered_cutout_metadata(str(scene_path), overlay_kind=overlay_kind, min_strength=0.82)
            rig_meta = dict(meta.get("rig", {}) or {}) if isinstance(meta, dict) else {}
            requested_face_rig = bool((rig_overrides or {}).get("face_rig_requested", True))
            cached_face_rig = bool(rig_meta.get("face_rig", False))
            cached_bundle = _validate_asset_bundle(cached)
            cached_has_mouth = bool(
                cached_bundle.get("mouth_closed_path")
                and cached_bundle.get("mouth_open_path")
            )
            if (
                meta
                and str(rig_meta.get("character_layer_mode", "") or "").strip().lower() == "simple_sprite"
                and str(rig_meta.get("motiontoon_pipeline", "") or "").strip().lower() == _PIPELINE_MARKER
                and requested_face_rig == cached_face_rig
                and (not requested_face_rig or cached_has_mouth)
            ):
                return cached_bundle

        if not background_source_path or not Path(background_source_path).exists():
            return {}

        out_dir = scene_path.parent / "_motiontoon"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = scene_path.stem

        background_path = out_dir / f"{stem}__bg.png"
        _materialize_image_copy(background_source_path, background_path)

        merged_rig = dict(rig_overrides or {})
        merged_rig["character_layer_mode"] = "simple_sprite"
        merged_rig["motiontoon_pipeline"] = _PIPELINE_MARKER

        assets: Dict[str, str] = {"background_path": str(background_path)}
        override_parts = {
            key: str(value or "")
            for key, value in dict(layer_part_overrides or {}).items()
            if key
        }
        face_overrides = {
            key: str(value or "")
            for key, value in dict(face_part_overrides or {}).items()
            if key
        }

        reusable_foreground = str(override_parts.get("foreground_path", "") or "")
        reusable_foreground_path = Path(reusable_foreground) if reusable_foreground else None
        derived_layered_foreground = bool(
            reusable_foreground_path
            and reusable_foreground_path.exists()
            and reusable_foreground_path.parent.name.strip().lower() == "_layered"
            and sprite_source_path
            and Path(sprite_source_path).exists()
        )
        if reusable_foreground and reusable_foreground_path and reusable_foreground_path.exists() and not derived_layered_foreground:
            foreground, crop_bbox = _extract_foreground(reusable_foreground)
            foreground_path = out_dir / f"{stem}__fg.png"
            foreground.save(foreground_path)

            full_sprite = _load_rgba(reusable_foreground)
            local_face_anchor_x, local_face_anchor_y = _face_anchor_for_crop(
                full_sprite.size,
                crop_bbox,
                merged_rig,
            )

            slot_name = str(merged_rig.get("cast_slot", "") or "default").strip().lower()
            layout = _resolve_sprite_layout(merged_rig, foreground.size, slot_name)
            merged_rig.update(
                {
                    "sprite_center_x": round(float(layout["center_x"]), 4),
                    "sprite_center_y": round(float(layout["center_y"]), 4),
                    "sprite_width_ratio": round(float(layout["width_ratio"]), 4),
                    "sprite_height_ratio": round(float(layout["height_ratio"]), 4),
                    "face_anchor_x": round(local_face_anchor_x, 4),
                    "face_anchor_y": round(local_face_anchor_y, 4),
                    "use_layered_cutout": True,
                }
            )
            copied_assets = {
                "foreground_path": str(foreground_path),
                "head_path": "",
                "body_path": "",
                "left_arm_path": "",
                "right_arm_path": "",
            }
            for key, suffix in (
                ("head_path", "__head.png"),
                ("body_path", "__body.png"),
                ("left_arm_path", "__left_arm.png"),
                ("right_arm_path", "__right_arm.png"),
            ):
                source_path = str(override_parts.get(key, "") or "")
                if source_path and Path(source_path).exists():
                    copied_assets[key] = _copy_part_asset(out_dir, stem, suffix, source_path)

            face_assets = {
                "eyes_open_path": "",
                "eyes_closed_path": "",
                "mouth_closed_path": "",
                "mouth_open_path": "",
            }
            for key, suffix in (
                ("eyes_open_path", "__eyes_open.png"),
                ("eyes_closed_path", "__eyes_closed.png"),
                ("mouth_closed_path", "__mouth_closed.png"),
                ("mouth_open_path", "__mouth_open.png"),
            ):
                source_path = face_overrides.get(key) or override_parts.get(key) or ""
                if source_path and Path(source_path).exists():
                    face_assets[key] = _copy_part_asset(out_dir, stem, suffix, source_path)

            face_rig_requested = bool(merged_rig.get("face_rig_requested", True))
            face_part_source = str(merged_rig.get("face_part_source", "") or "").strip().lower()
            allow_synthetic_face_parts = bool(merged_rig.get("allow_synthetic_face_parts", False))
            if any(face_assets.values()) and not face_part_source:
                face_part_source = "provided_face_parts"
            if (
                face_rig_requested
                and allow_synthetic_face_parts
                and not (face_assets.get("mouth_closed_path") and face_assets.get("mouth_open_path"))
            ):
                generated_face_assets = _build_face_overlay_assets(
                    out_dir,
                    stem,
                    foreground.size,
                    rig=merged_rig,
                    include_eyes=False,
                )
                for key, value in generated_face_assets.items():
                    if value and not face_assets.get(key):
                        face_assets[key] = value
                if any(generated_face_assets.values()):
                    face_part_source = "synthetic_overlay"
            merged_rig.update(
                {
                    "use_layered_cutout": True,
                    "face_rig": bool(
                        face_rig_requested
                        and (
                            face_assets.get("eyes_open_path")
                            or face_assets.get("eyes_closed_path")
                            or face_assets.get("mouth_closed_path")
                            or face_assets.get("mouth_open_path")
                        )
                    ),
                    "face_part_source": face_part_source,
                    "allow_synthetic_face_parts": allow_synthetic_face_parts,
                }
            )
            if not merged_rig["face_rig"]:
                merged_rig["face_part_source"] = "none"
                face_assets = {
                    "eyes_open_path": "",
                    "eyes_closed_path": "",
                    "mouth_closed_path": "",
                    "mouth_open_path": "",
                }
            assets.update(copied_assets)
            assets.update(face_assets)
            attached = attach_layered_cutout_assets(
                str(scene_path),
                assets,
                overlay_kind=overlay_kind,
                strength=0.82,
                rig_overrides=merged_rig,
            )
            return _validate_asset_bundle(attached or assets)

        if sprite_source_path and Path(sprite_source_path).exists():
            foreground, crop_bbox = _extract_foreground(sprite_source_path)
            foreground_path = out_dir / f"{stem}__fg.png"
            foreground.save(foreground_path)

            full_sprite = _load_rgba(sprite_source_path)
            local_face_anchor_x, local_face_anchor_y = _face_anchor_for_crop(
                full_sprite.size,
                crop_bbox,
                merged_rig,
            )

            slot_name = str(merged_rig.get("cast_slot", "") or "default").strip().lower()
            layout = _resolve_sprite_layout(merged_rig, foreground.size, slot_name)

            merged_rig.update(
                {
                    "sprite_center_x": round(float(layout["center_x"]), 4),
                    "sprite_center_y": round(float(layout["center_y"]), 4),
                    "sprite_width_ratio": round(float(layout["width_ratio"]), 4),
                    "sprite_height_ratio": round(float(layout["height_ratio"]), 4),
                    "face_anchor_x": round(local_face_anchor_x, 4),
                    "face_anchor_y": round(local_face_anchor_y, 4),
                    "use_layered_cutout": True,
                    "face_rig": True,
                }
            )

            face_assets = {
                "eyes_open_path": "",
                "eyes_closed_path": "",
                "mouth_closed_path": "",
                "mouth_open_path": "",
            }
            for key, value in face_overrides.items():
                if key in face_assets and value and Path(value).exists():
                    face_assets[key] = str(value)

            face_rig_requested = bool(merged_rig.get("face_rig_requested", True))
            face_part_source = str(merged_rig.get("face_part_source", "") or "").strip().lower()
            allow_synthetic_face_parts = bool(merged_rig.get("allow_synthetic_face_parts", False))
            if any(face_assets.values()) and not face_part_source:
                face_part_source = "provided_face_parts"
            if (
                face_rig_requested
                and allow_synthetic_face_parts
                and not (face_assets.get("mouth_closed_path") and face_assets.get("mouth_open_path"))
            ):
                generated_face_assets = _build_face_overlay_assets(
                    out_dir,
                    stem,
                    foreground.size,
                    rig=merged_rig,
                    include_eyes=False,
                )
                for key, value in generated_face_assets.items():
                    if value and not face_assets.get(key):
                        face_assets[key] = value
                if any(generated_face_assets.values()):
                    face_part_source = "synthetic_overlay"
            merged_rig["face_rig"] = bool(
                face_rig_requested
                and (
                    face_assets.get("eyes_open_path")
                    or face_assets.get("eyes_closed_path")
                    or face_assets.get("mouth_closed_path")
                    or face_assets.get("mouth_open_path")
                )
            )
            merged_rig["face_part_source"] = face_part_source
            merged_rig["allow_synthetic_face_parts"] = allow_synthetic_face_parts
            if not merged_rig["face_rig"]:
                merged_rig["face_part_source"] = "none"
                face_assets = {
                    "eyes_open_path": "",
                    "eyes_closed_path": "",
                    "mouth_closed_path": "",
                    "mouth_open_path": "",
                }
            assets.update(
                {
                    "foreground_path": str(foreground_path),
                    "head_path": "",
                    "body_path": "",
                    "left_arm_path": "",
                    "right_arm_path": "",
                }
            )
            assets.update(face_assets)
        else:
            merged_rig.update({"use_layered_cutout": False, "face_rig": False})

        attached = attach_layered_cutout_assets(
            str(scene_path),
            assets,
            overlay_kind=overlay_kind,
            strength=0.82,
            rig_overrides=merged_rig,
        )
        return _validate_asset_bundle(attached or assets)

    def build_background_only_assets(
        self,
        scene_image_path: str,
        *,
        background_source_path: str,
        rig_overrides: Dict[str, Any] | None = None,
        overlay_kind: str = "",
    ) -> Dict[str, str]:
        scene_path = Path(scene_image_path)
        if not scene_path.exists() or not background_source_path or not Path(background_source_path).exists():
            return {}

        out_dir = scene_path.parent / "_motiontoon"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = scene_path.stem
        background_path = out_dir / f"{stem}__bg.png"
        _materialize_image_copy(background_source_path, background_path)
        rig = dict(rig_overrides or {})
        rig["character_layer_mode"] = "simple_sprite"
        rig["motiontoon_pipeline"] = _PIPELINE_MARKER
        rig["use_layered_cutout"] = False
        rig["face_rig"] = False
        assets = {"background_path": str(background_path)}
        attached = attach_layered_cutout_assets(
            str(scene_path),
            assets,
            overlay_kind=overlay_kind,
            strength=0.82,
            rig_overrides=rig,
        )
        return _validate_asset_bundle(attached or assets)
