from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps


_FOCUS_MAP = {
    "message": (0.50, 0.56, 0.36, 0.46),
    "call": (0.50, 0.56, 0.34, 0.44),
    "bank": (0.50, 0.60, 0.40, 0.48),
    "document": (0.50, 0.54, 0.42, 0.50),
    "letter": (0.50, 0.50, 0.40, 0.50),
    "ledger": (0.50, 0.56, 0.42, 0.52),
    "seal": (0.50, 0.50, 0.34, 0.42),
    "decree": (0.50, 0.52, 0.42, 0.52),
}

_PART_KEYS = (
    "background_path",
    "foreground_path",
    "head_path",
    "body_path",
    "left_arm_path",
    "right_arm_path",
    "eyes_open_path",
    "eyes_closed_path",
    "mouth_closed_path",
    "mouth_open_path",
)


def _clamp_strength(strength: float) -> float:
    return max(0.1, min(1.5, float(strength or 0.65)))


def _mask_focus(overlay_kind: str) -> tuple[float, float, float, float]:
    return _FOCUS_MAP.get((overlay_kind or "").strip().lower(), (0.50, 0.46, 0.38, 0.54))


def _sidecar_path(src_path: Path) -> Path:
    return src_path.parent / "_layered" / f"{src_path.stem}__parts.json"


def load_layered_cutout_assets(
    image_path: str,
    *,
    overlay_kind: str = "",
    min_strength: float = 0.0,
) -> Dict[str, str]:
    src_path = Path(image_path)
    sidecar = _sidecar_path(src_path)
    if not src_path.exists() or not sidecar.exists():
        return {}

    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return {}

    stored_source = Path(str(data.get("source_path", "")))
    if stored_source and stored_source != src_path:
        return {}

    stored_kind = str(data.get("overlay_kind", "") or "").strip().lower()
    if overlay_kind and stored_kind and stored_kind != str(overlay_kind).strip().lower():
        return {}

    stored_strength = float(data.get("strength", 0.0) or 0.0)
    if stored_strength + 1e-6 < float(min_strength or 0.0):
        return {}

    source_mtime = float(data.get("source_mtime", 0.0) or 0.0)
    if source_mtime and src_path.stat().st_mtime > source_mtime + 1e-6:
        return {}

    assets = {}
    for key in _PART_KEYS:
        value = str(data.get(key, "") or "")
        if not value:
            continue
        asset_path = Path(value)
        if not asset_path.exists():
            return {}
        assets[key] = str(asset_path)
    if not assets:
        return {}
    return assets


def load_layered_cutout_metadata(
    image_path: str,
    *,
    overlay_kind: str = "",
    min_strength: float = 0.0,
) -> Dict[str, Any]:
    src_path = Path(image_path)
    sidecar = _sidecar_path(src_path)
    if not src_path.exists() or not sidecar.exists():
        return {}

    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return {}

    stored_source = Path(str(data.get("source_path", "")))
    if stored_source and stored_source != src_path:
        return {}

    stored_kind = str(data.get("overlay_kind", "") or "").strip().lower()
    if overlay_kind and stored_kind and stored_kind != str(overlay_kind).strip().lower():
        return {}

    stored_strength = float(data.get("strength", 0.0) or 0.0)
    if stored_strength + 1e-6 < float(min_strength or 0.0):
        return {}

    source_mtime = float(data.get("source_mtime", 0.0) or 0.0)
    if source_mtime and src_path.stat().st_mtime > source_mtime + 1e-6:
        return {}

    has_any_asset = False
    for key in _PART_KEYS:
        value = str(data.get(key, "") or "")
        if not value:
            continue
        if not Path(value).exists():
            return {}
        has_any_asset = True

    if not has_any_asset:
        return {}

    return dict(data)


def _write_layered_cutout_sidecar(
    src_path: Path,
    assets: Dict[str, str],
    *,
    overlay_kind: str,
    strength: float,
    rig_overrides: Dict[str, Any] | None = None,
) -> None:
    sidecar = _sidecar_path(src_path)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_path": str(src_path),
        "source_mtime": float(src_path.stat().st_mtime),
        "overlay_kind": str(overlay_kind or "").strip().lower(),
        "strength": float(strength or 0.0),
    }
    payload.update({key: str(assets.get(key, "") or "") for key in _PART_KEYS})
    rig_data = {
        key: value
        for key, value in dict(rig_overrides or {}).items()
        if value is not None
    }
    if rig_data:
        payload["rig"] = rig_data
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _expand_bbox(
    bbox: tuple[int, int, int, int] | None,
    size: tuple[int, int],
    *,
    pad_x: int,
    pad_y: int,
) -> tuple[int, int, int, int]:
    width, height = size
    if not bbox:
        return (0, 0, width, height)
    left, top, right, bottom = bbox
    return (
        max(0, left - pad_x),
        max(0, top - pad_y),
        min(width, right + pad_x),
        min(height, bottom + pad_y),
    )


def attach_layered_cutout_assets(
    image_path: str,
    assets: Dict[str, str],
    *,
    overlay_kind: str = "",
    strength: float = 0.65,
    rig_overrides: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    src_path = Path(image_path)
    if not src_path.exists():
        return {}

    normalized_assets: Dict[str, str] = {}
    for key in _PART_KEYS:
        value = str(assets.get(key, "") or "")
        if not value:
            continue
        if not Path(value).exists():
            return {}
        normalized_assets[key] = value

    if not normalized_assets:
        return {}

    _write_layered_cutout_sidecar(
        src_path,
        normalized_assets,
        overlay_kind=overlay_kind,
        strength=_clamp_strength(strength),
        rig_overrides=rig_overrides,
    )
    return normalized_assets


def clone_layered_cutout_assets(
    source_image_path: str,
    target_image_path: str,
    *,
    rig_overrides: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    source_meta = load_layered_cutout_metadata(source_image_path)
    if not source_meta:
        return {}

    merged_rig = dict(source_meta.get("rig", {}) or {})
    merged_rig.update({k: v for k, v in dict(rig_overrides or {}).items() if v is not None})
    assets = {key: str(source_meta.get(key, "") or "") for key in _PART_KEYS}
    return attach_layered_cutout_assets(
        target_image_path,
        assets,
        overlay_kind=str(source_meta.get("overlay_kind", "") or ""),
        strength=float(source_meta.get("strength", 0.65) or 0.65),
        rig_overrides=merged_rig,
    )


def _build_subject_mask(size: tuple[int, int], overlay_kind: str, strength: float) -> Image.Image:
    width, height = size
    center_x, center_y, radius_x, radius_y = _mask_focus(overlay_kind)
    strength = _clamp_strength(strength)

    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)

    subject_box = (
        int(width * (center_x - radius_x)),
        int(height * (center_y - radius_y)),
        int(width * (center_x + radius_x)),
        int(height * (center_y + radius_y)),
    )
    torso_box = (
        int(width * (center_x - radius_x * 0.72)),
        int(height * max(0.0, center_y - radius_y * 1.15)),
        int(width * (center_x + radius_x * 0.72)),
        int(height * min(1.0, center_y + radius_y * 0.20)),
    )
    draw.ellipse(subject_box, fill=196)
    draw.ellipse(torso_box, fill=255)

    blur_radius = max(18, int(min(width, height) * 0.04 * strength))
    return mask.filter(ImageFilter.GaussianBlur(radius=blur_radius))


def _build_part_masks(
    size: tuple[int, int],
    overlay_kind: str,
    strength: float,
) -> tuple[Image.Image, Image.Image, Image.Image, Image.Image]:
    width, height = size
    center_x, center_y, radius_x, radius_y = _mask_focus(overlay_kind)
    strength = _clamp_strength(strength)

    head_mask = Image.new("L", size, 0)
    body_mask = Image.new("L", size, 0)
    left_arm_mask = Image.new("L", size, 0)
    right_arm_mask = Image.new("L", size, 0)
    head_draw = ImageDraw.Draw(head_mask)
    body_draw = ImageDraw.Draw(body_mask)
    left_arm_draw = ImageDraw.Draw(left_arm_mask)
    right_arm_draw = ImageDraw.Draw(right_arm_mask)

    head_box = (
        int(width * (center_x - radius_x * 0.38)),
        int(height * (center_y - radius_y * 1.22)),
        int(width * (center_x + radius_x * 0.38)),
        int(height * (center_y - radius_y * 0.20)),
    )
    body_box = (
        int(width * (center_x - radius_x * 0.68)),
        int(height * (center_y - radius_y * 0.30)),
        int(width * (center_x + radius_x * 0.68)),
        int(height * (center_y + radius_y * 0.78)),
    )
    arm_width = max(16, int(width * radius_x * 0.34))
    arm_height = max(18, int(height * radius_y * 0.84))
    shoulder_y = int(height * (center_y - radius_y * 0.12))
    left_arm_box = (
        int(width * (center_x - radius_x * 0.92)),
        shoulder_y,
        int(width * (center_x - radius_x * 0.92)) + arm_width,
        shoulder_y + arm_height,
    )
    right_arm_box = (
        int(width * (center_x + radius_x * 0.58)),
        shoulder_y,
        int(width * (center_x + radius_x * 0.58)) + arm_width,
        shoulder_y + arm_height,
    )

    head_draw.ellipse(head_box, fill=255)
    body_draw.rounded_rectangle(body_box, radius=max(10, int(min(width, height) * 0.04)), fill=232)
    left_arm_draw.rounded_rectangle(
        left_arm_box,
        radius=max(8, int(min(width, height) * 0.03)),
        fill=210,
    )
    right_arm_draw.rounded_rectangle(
        right_arm_box,
        radius=max(8, int(min(width, height) * 0.03)),
        fill=210,
    )

    head_blur = max(8, int(min(width, height) * 0.018 * strength))
    body_blur = max(12, int(min(width, height) * 0.024 * strength))
    arm_blur = max(10, int(min(width, height) * 0.02 * strength))
    return (
        head_mask.filter(ImageFilter.GaussianBlur(radius=head_blur)),
        body_mask.filter(ImageFilter.GaussianBlur(radius=body_blur)),
        left_arm_mask.filter(ImageFilter.GaussianBlur(radius=arm_blur)),
        right_arm_mask.filter(ImageFilter.GaussianBlur(radius=arm_blur)),
    )


def _build_face_assets(out_dir: Path, stem: str, rig_overrides: Dict[str, Any] | None = None) -> Dict[str, str]:
    rig = dict(rig_overrides or {})
    cast_slot = str(rig.get("cast_slot", "") or "").strip().lower()
    overlay_theme = str(rig.get("overlay_theme", "") or "").strip().lower()
    emotion_hint = str(rig.get("emotion_hint", "") or "").strip().lower()
    pose_hint = str(rig.get("pose_hint", "") or "").strip().lower()

    width = 180
    height = 128
    line_color = (22, 22, 28, 220)
    fill_color = (255, 255, 255, 32)
    if overlay_theme == "life_saguk":
        line_color = (66, 34, 18, 210)
        fill_color = (244, 229, 206, 40)
    elif cast_slot == "antagonist":
        line_color = (48, 10, 10, 224)
        fill_color = (255, 235, 235, 26)
    elif cast_slot in {"elder", "support"}:
        line_color = (58, 42, 24, 208)
        fill_color = (245, 236, 216, 30)

    eyes_open_path = out_dir / f"{stem}__eyes_open.png"
    eyes_closed_path = out_dir / f"{stem}__eyes_closed.png"
    mouth_closed_path = out_dir / f"{stem}__mouth_closed.png"
    mouth_open_path = out_dir / f"{stem}__mouth_open.png"

    eyes_open = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    eyes_closed = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    mouth_closed = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    mouth_open = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    eo = ImageDraw.Draw(eyes_open)
    ec = ImageDraw.Draw(eyes_closed)
    mc = ImageDraw.Draw(mouth_closed)
    mo = ImageDraw.Draw(mouth_open)

    eye_width = 42 if cast_slot != "elder" else 38
    eye_height = 10 if cast_slot != "antagonist" else 8
    eye_top = 34
    open_eye_start = 180
    open_eye_end = 360
    closed_eye_y = 38
    mouth_closed_box = (width // 2 - 16, 94, width // 2 + 16, 100)
    mouth_open_box = (width // 2 - 22, 90, width // 2 + 22, 110)

    if emotion_hint in {"angry", "desperate"}:
        eye_height = max(7, eye_height - 2)
        open_eye_start = 200
        open_eye_end = 352
        closed_eye_y = 36
        mouth_closed_box = (width // 2 - 18, 94, width // 2 + 18, 100)
        mouth_open_box = (width // 2 - 24, 90, width // 2 + 24, 112)
    elif emotion_hint in {"fear", "scared", "worried"}:
        eye_top = 30
        eye_height = eye_height + 4
        mouth_open_box = (width // 2 - 20, 88, width // 2 + 20, 114)
    elif emotion_hint in {"sad", "calm"}:
        eye_top = 36
        open_eye_start = 165
        open_eye_end = 350
        mouth_closed_box = (width // 2 - 14, 96, width // 2 + 14, 100)
        mouth_open_box = (width // 2 - 18, 92, width // 2 + 18, 108)
    elif emotion_hint in {"whisper"}:
        eye_height = max(6, eye_height - 2)
        mouth_closed_box = (width // 2 - 12, 96, width // 2 + 12, 99)
        mouth_open_box = (width // 2 - 14, 94, width // 2 + 14, 104)

    if pose_hint in {"kneeling", "sitting"}:
        mouth_closed_box = (
            mouth_closed_box[0],
            mouth_closed_box[1] + 2,
            mouth_closed_box[2],
            mouth_closed_box[3] + 2,
        )
        mouth_open_box = (
            mouth_open_box[0],
            mouth_open_box[1] + 2,
            mouth_open_box[2],
            mouth_open_box[3] + 2,
        )

    left_eye = (28, eye_top, 28 + eye_width, eye_top + eye_height)
    right_eye = (width - 28 - eye_width, eye_top, width - 28, eye_top + eye_height)
    eo.arc(left_eye, start=open_eye_start, end=open_eye_end, fill=line_color, width=4)
    eo.arc(right_eye, start=open_eye_start, end=open_eye_end, fill=line_color, width=4)
    eo.rectangle((left_eye[0] + 8, left_eye[1] + 3, left_eye[2] - 8, left_eye[3] + 4), fill=fill_color)
    eo.rectangle((right_eye[0] + 8, right_eye[1] + 3, right_eye[2] - 8, right_eye[3] + 4), fill=fill_color)

    if emotion_hint in {"sad", "calm"}:
        ec.arc((28, closed_eye_y - 1, 28 + eye_width, closed_eye_y + 7), start=15, end=165, fill=line_color, width=4)
        ec.arc((width - 28 - eye_width, closed_eye_y - 1, width - 28, closed_eye_y + 7), start=15, end=165, fill=line_color, width=4)
    else:
        ec.line((28, closed_eye_y, 28 + eye_width, closed_eye_y), fill=line_color, width=4)
        ec.line((width - 28 - eye_width, closed_eye_y, width - 28, closed_eye_y), fill=line_color, width=4)

    mc.rounded_rectangle(mouth_closed_box, radius=8, fill=line_color)
    mo.rounded_rectangle(mouth_open_box, radius=12, fill=line_color)
    inner_pad_x = 6 if emotion_hint in {"whisper", "sad", "calm"} else 8
    inner_pad_y = 4 if emotion_hint in {"fear", "scared", "desperate"} else 3
    mo.rounded_rectangle(
        (
            mouth_open_box[0] + inner_pad_x,
            mouth_open_box[1] + inner_pad_y,
            mouth_open_box[2] - inner_pad_x,
            mouth_open_box[3] - inner_pad_y,
        ),
        radius=8,
        fill=(0, 0, 0, 0),
        outline=fill_color,
        width=2,
    )

    eyes_open.save(eyes_open_path)
    eyes_closed.save(eyes_closed_path)
    mouth_closed.save(mouth_closed_path)
    mouth_open.save(mouth_open_path)

    return {
        "eyes_open_path": str(eyes_open_path),
        "eyes_closed_path": str(eyes_closed_path),
        "mouth_closed_path": str(mouth_closed_path),
        "mouth_open_path": str(mouth_open_path),
    }


def build_layered_cutout_assets(
    image_path: str,
    *,
    overlay_kind: str = "",
    strength: float = 0.65,
    force: bool = False,
    rig_overrides: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    src_path = Path(image_path)
    if not src_path.exists():
        return {"background_path": "", "foreground_path": ""}

    overlay_kind = str(overlay_kind or "").strip().lower()
    strength = _clamp_strength(strength)

    if not force:
        cached_assets = load_layered_cutout_assets(
            str(src_path),
            overlay_kind=overlay_kind,
            min_strength=strength,
        )
        if cached_assets:
            cached_meta = load_layered_cutout_metadata(
                str(src_path),
                overlay_kind=overlay_kind,
                min_strength=strength,
            )
            rig = dict(cached_meta.get("rig", {}) or {}) if isinstance(cached_meta, dict) else {}
            if all(key in rig for key in ("sprite_center_x", "sprite_center_y", "sprite_width_ratio", "sprite_height_ratio")):
                if float(rig.get("sprite_width_ratio", 1.0) or 1.0) <= 0.54 and float(rig.get("sprite_height_ratio", 1.0) or 1.0) <= 0.82:
                    return cached_assets

    out_dir = src_path.parent / "_layered"
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = src_path.stem
    bg_path = out_dir / f"{stem}__bg.png"
    fg_path = out_dir / f"{stem}__fg.png"
    head_path = out_dir / f"{stem}__head.png"
    body_path = out_dir / f"{stem}__body.png"
    left_arm_path = out_dir / f"{stem}__left_arm.png"
    right_arm_path = out_dir / f"{stem}__right_arm.png"
    eyes_open_path = out_dir / f"{stem}__eyes_open.png"
    eyes_closed_path = out_dir / f"{stem}__eyes_closed.png"
    mouth_closed_path = out_dir / f"{stem}__mouth_closed.png"
    mouth_open_path = out_dir / f"{stem}__mouth_open.png"

    if (
        not force
        and bg_path.exists()
        and fg_path.exists()
        and head_path.exists()
        and body_path.exists()
        and left_arm_path.exists()
        and right_arm_path.exists()
        and eyes_open_path.exists()
        and eyes_closed_path.exists()
        and mouth_closed_path.exists()
        and mouth_open_path.exists()
        and bg_path.stat().st_mtime >= src_path.stat().st_mtime
        and fg_path.stat().st_mtime >= src_path.stat().st_mtime
        and head_path.stat().st_mtime >= src_path.stat().st_mtime
        and body_path.stat().st_mtime >= src_path.stat().st_mtime
        and left_arm_path.stat().st_mtime >= src_path.stat().st_mtime
        and right_arm_path.stat().st_mtime >= src_path.stat().st_mtime
        and eyes_open_path.stat().st_mtime >= src_path.stat().st_mtime
        and eyes_closed_path.stat().st_mtime >= src_path.stat().st_mtime
        and mouth_closed_path.stat().st_mtime >= src_path.stat().st_mtime
        and mouth_open_path.stat().st_mtime >= src_path.stat().st_mtime
    ):
        face_assets = {
            "eyes_open_path": "",
            "eyes_closed_path": "",
            "mouth_closed_path": "",
            "mouth_open_path": "",
        }
        if bool(dict(rig_overrides or {}).get("allow_synthetic_face_parts", False)):
            face_assets = _build_face_assets(out_dir, stem, rig_overrides=rig_overrides)
        cached_meta = load_layered_cutout_metadata(
            str(src_path),
            overlay_kind=overlay_kind,
            min_strength=strength,
        )
        rig_data = dict(cached_meta.get("rig", {}) or {}) if isinstance(cached_meta, dict) else {}
        rig_data.update({k: v for k, v in dict(rig_overrides or {}).items() if v is not None})
        rig_data["face_part_source"] = (
            "synthetic_overlay" if any(face_assets.values()) else str(rig_data.get("face_part_source") or "none")
        )
        assets = {
            "background_path": str(bg_path),
            "foreground_path": str(fg_path),
            "head_path": str(head_path),
            "body_path": str(body_path),
            "left_arm_path": str(left_arm_path),
            "right_arm_path": str(right_arm_path),
        }
        assets.update(face_assets)
        if all(
            key in rig_data
            for key in ("sprite_center_x", "sprite_center_y", "sprite_width_ratio", "sprite_height_ratio")
        ):
            _write_layered_cutout_sidecar(
                src_path,
                assets,
                overlay_kind=overlay_kind,
                strength=strength,
                rig_overrides=rig_data,
            )
            return assets

    base = Image.open(src_path).convert("RGBA")
    mask = _build_subject_mask(base.size, overlay_kind, strength)
    head_mask, body_mask, left_arm_mask, right_arm_mask = _build_part_masks(base.size, overlay_kind, strength)
    blurred = base.filter(ImageFilter.GaussianBlur(radius=max(6, int(12 * _clamp_strength(strength)))))
    blurred = ImageEnhance.Color(blurred).enhance(0.78)
    blurred = ImageEnhance.Brightness(blurred).enhance(0.88)
    feathered_mask = mask.filter(ImageFilter.GaussianBlur(radius=max(10, int(18 * _clamp_strength(strength)))))
    inverse_mask = ImageOps.invert(feathered_mask)

    # Use the scene background as the primary plate and largely remove the subject
    # so the paper-doll layers read as separate pieces.
    background = Image.new("RGBA", base.size, (0, 0, 0, 0))
    background.paste(base, (0, 0), inverse_mask)

    # Keep only a faint blurred ghost of the removed subject area so gaps do not
    # flash to black during aggressive cutout motion.
    subject_ghost = blurred.copy()
    subject_ghost.putalpha(feathered_mask.point(lambda value: min(255, int(value * 0.18))))
    background = Image.alpha_composite(background, subject_ghost)

    foreground = Image.new("RGBA", base.size, (0, 0, 0, 0))
    foreground.paste(base, (0, 0), mask)
    center_x, center_y, radius_x, radius_y = _mask_focus(overlay_kind)
    sprite_box = (
        int(base.size[0] * (center_x - radius_x * 0.46)),
        int(base.size[1] * (center_y - radius_y * 0.94)),
        int(base.size[0] * (center_x + radius_x * 0.46)),
        int(base.size[1] * (center_y + radius_y * 0.62)),
    )
    subject_bbox = _expand_bbox(
        sprite_box,
        base.size,
        pad_x=max(6, int(base.size[0] * 0.006)),
        pad_y=max(6, int(base.size[1] * 0.008)),
    )
    foreground = foreground.crop(subject_bbox)

    head = Image.new("RGBA", base.size, (0, 0, 0, 0))
    head.paste(base, (0, 0), head_mask)

    body = Image.new("RGBA", base.size, (0, 0, 0, 0))
    body.paste(base, (0, 0), body_mask)
    left_arm = Image.new("RGBA", base.size, (0, 0, 0, 0))
    left_arm.paste(base, (0, 0), left_arm_mask)
    right_arm = Image.new("RGBA", base.size, (0, 0, 0, 0))
    right_arm.paste(base, (0, 0), right_arm_mask)

    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow_alpha = mask.filter(ImageFilter.GaussianBlur(radius=max(10, int(22 * _clamp_strength(strength)))))
    shadow.paste((0, 0, 0, 84), (0, 0), shadow_alpha)
    background = Image.alpha_composite(background, shadow)

    background.save(bg_path)
    foreground.save(fg_path)
    head.save(head_path)
    body.save(body_path)
    left_arm.save(left_arm_path)
    right_arm.save(right_arm_path)
    face_assets = {
        "eyes_open_path": "",
        "eyes_closed_path": "",
        "mouth_closed_path": "",
        "mouth_open_path": "",
    }
    if bool(dict(rig_overrides or {}).get("allow_synthetic_face_parts", False)):
        face_assets = _build_face_assets(out_dir, stem, rig_overrides=rig_overrides)
    bbox_left, bbox_top, bbox_right, bbox_bottom = subject_bbox
    rig_data = dict(rig_overrides or {})
    rig_data.update({
        "sprite_center_x": round(((bbox_left + bbox_right) / 2) / base.size[0], 4),
        "sprite_center_y": round(((bbox_top + bbox_bottom) / 2) / base.size[1], 4),
        "sprite_width_ratio": round((bbox_right - bbox_left) / base.size[0], 4),
        "sprite_height_ratio": round((bbox_bottom - bbox_top) / base.size[1], 4),
        "face_part_source": "synthetic_overlay" if any(face_assets.values()) else str(rig_data.get("face_part_source") or "none"),
    })
    assets = {
        "background_path": str(bg_path),
        "foreground_path": str(fg_path),
        "head_path": str(head_path),
        "body_path": str(body_path),
        "left_arm_path": str(left_arm_path),
        "right_arm_path": str(right_arm_path),
    }
    assets.update(face_assets)
    _write_layered_cutout_sidecar(
        src_path,
        assets,
        overlay_kind=overlay_kind,
        strength=strength,
        rig_overrides=rig_data,
    )
    return assets
