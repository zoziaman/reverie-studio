from __future__ import annotations

from typing import Iterable, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


Box = Tuple[int, int, int, int]
HueRange = Tuple[int, int]


def _normalize_box(box: Sequence[int], size: tuple[int, int]) -> Box:
    if len(box) != 4:
        raise ValueError("Box must contain four integers.")
    width, height = size
    left, top, right, bottom = [int(value) for value in box]
    left = max(0, min(width, left))
    top = max(0, min(height, top))
    right = max(left + 1, min(width, right))
    bottom = max(top + 1, min(height, bottom))
    return left, top, right, bottom


def _coerce_rgba(image: Image.Image) -> Image.Image:
    return image if image.mode == "RGBA" else image.convert("RGBA")


def paste_patch_from_source(
    image: Image.Image,
    *,
    target_box: Sequence[int],
    source_box: Sequence[int],
    feather_radius: float = 3.0,
    rounded_radius: int = 6,
) -> Image.Image:
    base = _coerce_rgba(image)
    dst = _normalize_box(target_box, base.size)
    src = _normalize_box(source_box, base.size)

    target_width = dst[2] - dst[0]
    target_height = dst[3] - dst[1]
    patch = base.crop(src).resize((target_width, target_height))

    canvas = base.copy()
    canvas.paste(patch, dst[:2], patch.getchannel("A"))

    mask = Image.new("L", base.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(dst, radius=max(0, int(rounded_radius)), fill=255)
    if feather_radius > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=float(feather_radius)))

    result = Image.composite(canvas, base, mask)
    result.putalpha(base.getchannel("A"))
    return result


def build_hsv_cluster_mask(
    image: Image.Image,
    *,
    rois: Iterable[Sequence[int]],
    saturation_min: int = 90,
    value_min: int = 50,
    hue_ranges: Iterable[HueRange] = ((35, 150), (150, 179)),
    dilate_px: int = 1,
) -> Image.Image:
    base = _coerce_rgba(image)
    rgb = np.array(base.convert("RGB"))

    try:
        import cv2
    except Exception as exc:  # pragma: no cover - production dependency guard
        raise RuntimeError("OpenCV is required for HSV cluster cleanup.") from exc

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    mask = np.zeros((base.height, base.width), dtype=np.uint8)

    hue_conditions = []
    for lower, upper in hue_ranges:
        hue_conditions.append((hsv[:, :, 0] >= int(lower)) & (hsv[:, :, 0] <= int(upper)))
    hue_mask = np.logical_or.reduce(hue_conditions) if hue_conditions else np.zeros(mask.shape, dtype=bool)

    for roi in rois:
        left, top, right, bottom = _normalize_box(roi, base.size)
        local = (
            (hsv[top:bottom, left:right, 1] >= int(saturation_min))
            & (hsv[top:bottom, left:right, 2] >= int(value_min))
            & hue_mask[top:bottom, left:right]
        )
        mask[top:bottom, left:right][local] = 255

    if dilate_px > 0:
        kernel_size = max(1, int(dilate_px) * 2 + 1)
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)

    return Image.fromarray(mask)


def inpaint_mask(
    image: Image.Image,
    *,
    mask: Image.Image,
    radius: float = 3.0,
) -> Image.Image:
    base = _coerce_rgba(image)
    mask_image = mask.convert("L")

    try:
        import cv2
    except Exception as exc:  # pragma: no cover - production dependency guard
        raise RuntimeError("OpenCV is required for inpainting.") from exc

    rgb = np.array(base.convert("RGB"))
    mask_arr = np.array(mask_image, dtype=np.uint8)
    cleaned = cv2.inpaint(
        cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
        mask_arr,
        float(radius),
        cv2.INPAINT_TELEA,
    )
    result = Image.fromarray(cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB)).convert("RGBA")
    result.putalpha(base.getchannel("A"))
    return result


def inpaint_hsv_clusters(
    image: Image.Image,
    *,
    rois: Iterable[Sequence[int]],
    saturation_min: int = 90,
    value_min: int = 50,
    hue_ranges: Iterable[HueRange] = ((35, 150), (150, 179)),
    dilate_px: int = 1,
    radius: float = 3.0,
) -> tuple[Image.Image, Image.Image]:
    mask = build_hsv_cluster_mask(
        image,
        rois=rois,
        saturation_min=saturation_min,
        value_min=value_min,
        hue_ranges=hue_ranges,
        dilate_px=dilate_px,
    )
    return inpaint_mask(image, mask=mask, radius=radius), mask
