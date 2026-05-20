from pathlib import Path
import json

from modules_pro.remotion_assembler import RemotionAssembler
from utils.layered_cutout import attach_layered_cutout_assets


def _write_bytes(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return str(path)


def test_copy_assets_to_public_prefers_motiontoon_bundle_for_simple_sprite(tmp_path, monkeypatch):
    project_root = tmp_path / "remotion-poc"
    project_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("modules_pro.remotion_assembler.REMOTION_PROJECT_PATH", project_root)

    scene_path = tmp_path / "scene_0000.png"
    _write_bytes(scene_path, b"scene-image")

    wrong_bg = _write_bytes(tmp_path / "_layered" / "scene_0000__bg.png", b"wrong-bg")
    wrong_fg = _write_bytes(tmp_path / "_layered" / "scene_0000__fg.png", b"wrong-fg")
    attach_layered_cutout_assets(
        str(scene_path),
        {
            "background_path": wrong_bg,
            "foreground_path": wrong_fg,
        },
        overlay_kind="",
        strength=0.78,
        rig_overrides={
            "character_layer_mode": "simple_sprite",
            "sprite_center_x": 0.5,
            "sprite_center_y": 0.4,
            "sprite_width_ratio": 0.32,
            "sprite_height_ratio": 0.72,
        },
    )

    motiontoon_dir = tmp_path / "_motiontoon"
    expected_bg = motiontoon_dir / "scene_0000__bg.png"
    expected_fg = motiontoon_dir / "scene_0000__fg.png"
    _write_bytes(expected_bg, b"correct-bg")
    _write_bytes(expected_fg, b"correct-fg")

    assembler = RemotionAssembler()
    assembler.add_scene(
        image_path=str(scene_path),
        audio_path="",
        text="장면 테스트",
        speaker="할아버지",
        duration_ms=1000,
        motion_data={
            "use_layered_cutout": True,
            "character_layer_mode": "simple_sprite",
            "layered_cutout_strength": 0.78,
        },
    )

    result = assembler._copy_assets_to_public()
    background_paths = result[2]
    foreground_paths = result[3]

    copied_bg = project_root / "public" / background_paths[0]
    copied_fg = project_root / "public" / foreground_paths[0]

    assert copied_bg.read_bytes() == expected_bg.read_bytes()
    assert copied_fg.read_bytes() == expected_fg.read_bytes()


def test_copy_assets_to_public_marks_walking_variants_with_walk_drift(tmp_path, monkeypatch):
    project_root = tmp_path / "remotion-poc"
    project_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("modules_pro.remotion_assembler.REMOTION_PROJECT_PATH", project_root)

    scene_path = tmp_path / "neutral_walking_01.png"
    _write_bytes(scene_path, b"scene-image")

    assembler = RemotionAssembler()
    assembler.add_scene(
        image_path=str(scene_path),
        audio_path="",
        text="장면 테스트",
        speaker="young_man",
        duration_ms=1000,
        motion_data={"primitives": ["idle_drift"]},
    )

    assembler._copy_assets_to_public()

    assert assembler.scenes[0].motion_data is not None
    assert "walk_drift" in assembler.scenes[0].motion_data["primitives"]
    assert assembler.scenes[0].motion_data["pose_hint"] == "walking"


def test_build_props_includes_scene_mouth_cues(tmp_path, monkeypatch):
    project_root = tmp_path / "remotion-poc"
    project_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("modules_pro.remotion_assembler.REMOTION_PROJECT_PATH", project_root)

    scene_path = tmp_path / "scene_0000.png"
    cues_path = tmp_path / "scene_0000_mouth_cues.json"
    _write_bytes(scene_path, b"scene-image")
    cues_path.write_text(
        json.dumps({"fps": 30, "cues": [{"frame": 0, "mouth": 1}, {"frame": 1, "mouth": 0}]}),
        encoding="utf-8",
    )

    assembler = RemotionAssembler()
    assembler.add_scene(
        image_path=str(scene_path),
        audio_path="",
        text="test",
        speaker="young_woman",
        duration_ms=1000,
        mouth_cues_path=str(cues_path),
        motion_data={"face_rig": True, "primitives": []},
    )

    result = assembler._copy_assets_to_public()
    props = assembler._build_props(*result)

    assert props["images"][0]["mouthCues"] == [{"frame": 0, "mouth": 1}, {"frame": 1, "mouth": 0}]
