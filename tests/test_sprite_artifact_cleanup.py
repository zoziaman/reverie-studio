from PIL import Image, ImageDraw

from utils.sprite_artifact_cleanup import build_hsv_cluster_mask, inpaint_hsv_clusters, paste_patch_from_source


def test_paste_patch_from_source_replaces_target_region():
    img = Image.new("RGBA", (40, 20), (240, 240, 240, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 9, 19), fill=(60, 100, 140, 255))
    draw.rectangle((20, 0, 29, 19), fill=(255, 0, 0, 255))

    result = paste_patch_from_source(
        img,
        target_box=(20, 0, 30, 20),
        source_box=(0, 0, 10, 20),
        feather_radius=0.0,
        rounded_radius=0,
    )

    assert result.getpixel((25, 10))[:3] == (60, 100, 140)


def test_inpaint_hsv_clusters_cleans_neon_region_inside_roi():
    img = Image.new("RGBA", (48, 48), (245, 242, 236, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((18, 18, 27, 27), fill=(0, 255, 255, 255))

    mask = build_hsv_cluster_mask(
        img,
        rois=[(15, 15, 30, 30)],
        saturation_min=100,
        value_min=100,
        dilate_px=0,
    )
    assert mask.getbbox() is not None

    result, _ = inpaint_hsv_clusters(
        img,
        rois=[(15, 15, 30, 30)],
        saturation_min=100,
        value_min=100,
        dilate_px=1,
        radius=3.0,
    )

    cleaned = result.getpixel((22, 22))[:3]
    assert cleaned != (0, 255, 255)
