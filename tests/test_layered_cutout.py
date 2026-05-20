from pathlib import Path

from PIL import Image

from utils.layered_cutout import (
    clone_layered_cutout_assets,
    build_layered_cutout_assets,
    load_layered_cutout_assets,
    load_layered_cutout_metadata,
)


def test_build_layered_cutout_assets_creates_background_and_foreground(tmp_path):
    src = tmp_path / "scene.png"
    img = Image.new("RGBA", (240, 135), (35, 45, 60, 255))
    for x in range(80, 160):
        for y in range(20, 125):
            img.putpixel((x, y), (225, 210, 180, 255))
    img.save(src)

    result = build_layered_cutout_assets(str(src), overlay_kind="document", strength=0.8)

    bg = Path(result["background_path"])
    fg = Path(result["foreground_path"])
    head = Path(result["head_path"])
    body = Path(result["body_path"])
    left_arm = Path(result["left_arm_path"])
    right_arm = Path(result["right_arm_path"])
    eyes_open = Path(result["eyes_open_path"])
    eyes_closed = Path(result["eyes_closed_path"])
    mouth_closed = Path(result["mouth_closed_path"])
    mouth_open = Path(result["mouth_open_path"])
    assert bg.exists()
    assert fg.exists()
    assert head.exists()
    assert body.exists()
    assert left_arm.exists()
    assert right_arm.exists()
    assert eyes_open.exists()
    assert eyes_closed.exists()
    assert mouth_closed.exists()
    assert mouth_open.exists()

    with (
        Image.open(bg) as bg_img,
        Image.open(fg) as fg_img,
        Image.open(head) as head_img,
        Image.open(body) as body_img,
        Image.open(left_arm) as left_arm_img,
        Image.open(right_arm) as right_arm_img,
        Image.open(eyes_open) as eyes_open_img,
        Image.open(eyes_closed) as eyes_closed_img,
        Image.open(mouth_closed) as mouth_closed_img,
        Image.open(mouth_open) as mouth_open_img,
    ):
        assert bg_img.size == (240, 135)
        assert fg_img.size[0] < bg_img.size[0]
        assert fg_img.size[1] < bg_img.size[1]
        assert fg_img.size[0] > 0
        assert fg_img.size[1] > 0
        assert head_img.size == (240, 135)
        assert body_img.size == (240, 135)
        assert left_arm_img.size == (240, 135)
        assert right_arm_img.size == (240, 135)
        assert eyes_open_img.size == (180, 128)
        assert eyes_closed_img.size == (180, 128)
        assert mouth_closed_img.size == (180, 128)
        assert mouth_open_img.size == (180, 128)


def test_build_layered_cutout_assets_writes_reusable_sidecar(tmp_path):
    src = tmp_path / "scene.png"
    Image.new("RGBA", (180, 100), (80, 90, 110, 255)).save(src)

    first = build_layered_cutout_assets(str(src), overlay_kind="message", strength=0.7)
    loaded = load_layered_cutout_assets(str(src), overlay_kind="message", min_strength=0.6)

    assert loaded == first


def test_build_layered_cutout_assets_persists_rig_metadata(tmp_path):
    src = tmp_path / "scene.png"
    Image.new("RGBA", (180, 100), (80, 90, 110, 255)).save(src)

    build_layered_cutout_assets(
        str(src),
        overlay_kind="message",
        strength=0.7,
        rig_overrides={"face_anchor_x": 0.56, "bob_strength": 0.72, "cast_slot": "protagonist"},
    )
    meta = load_layered_cutout_metadata(str(src), min_strength=0.6)

    assert meta["rig"]["face_anchor_x"] == 0.56
    assert meta["rig"]["bob_strength"] == 0.72
    assert meta["rig"]["cast_slot"] == "protagonist"
    assert Path(meta["eyes_open_path"]).exists()
    assert Path(meta["mouth_open_path"]).exists()


def test_clone_layered_cutout_assets_binds_source_parts_to_target(tmp_path):
    src = tmp_path / "source.png"
    dst = tmp_path / "target.png"
    Image.new("RGBA", (180, 100), (80, 90, 110, 255)).save(src)
    Image.new("RGBA", (180, 100), (70, 80, 100, 255)).save(dst)

    original = build_layered_cutout_assets(
        str(src),
        overlay_kind="document",
        strength=0.7,
        rig_overrides={"cast_slot": "protagonist", "face_anchor_x": 0.52},
    )
    cloned = clone_layered_cutout_assets(
        str(src),
        str(dst),
        rig_overrides={"face_anchor_x": 0.61, "bob_strength": 0.74},
    )
    meta = load_layered_cutout_metadata(str(dst))

    assert cloned == original
    assert meta["rig"]["cast_slot"] == "protagonist"
    assert meta["rig"]["face_anchor_x"] == 0.61
    assert meta["rig"]["bob_strength"] == 0.74
