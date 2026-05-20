import base64
import json
from pathlib import Path
from types import SimpleNamespace
from PIL import Image, ImageDraw

from modules_pro.character_library_manager import (
    CharacterImage,
    CharacterLibraryEntry,
    CharacterLibraryManager,
    LibraryConfig,
)
from modules_pro.prompt_composer import PromptComposer, char_defs_from_dict
from modules_pro.scene_analyzer import CharacterState, SceneAnalysisResult, SceneAnalyzer
from modules_pro.visual_storytelling_director import GeneratedImage, VisualStorytellingDirector
from pipeline.image_pipeline import ImagePipeline
from utils.layered_cutout import build_layered_cutout_assets, load_layered_cutout_metadata


def _touch(path: Path) -> str:
    path.write_bytes(b"test")
    return str(path)


def _make_sprite(path: Path, color: tuple[int, int, int, int]) -> str:
    img = Image.new("RGBA", (160, 320), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((42, 20, 118, 100), fill=(235, 214, 186, 255))
    draw.rounded_rectangle((34, 92, 126, 286), radius=20, fill=color)
    img.save(path)
    return str(path)


def test_character_library_picks_same_best_image(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))

    better = _touch(tmp_path / "better.png")
    worse = _touch(tmp_path / "worse.png")

    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "neutral_standing": [
                CharacterImage(path=worse, quality_score=0.7, blur_score=0.3, seed=22),
                CharacterImage(path=better, quality_score=0.95, blur_score=0.1, seed=11),
            ]
        },
    )

    first = manager.get_character_image("hero", "neutral", "standing")
    second = manager.get_character_image("hero", "neutral", "standing")

    assert first == better
    assert second == better


def test_character_library_stable_seed_is_deterministic():
    seed_a = CharacterLibraryManager._stable_seed("pack:hero")
    seed_b = CharacterLibraryManager._stable_seed("pack:hero")
    seed_c = CharacterLibraryManager._stable_seed("pack:villain")

    assert seed_a == seed_b
    assert seed_a != seed_c


def test_character_library_canonicalize_prefers_current_character_folder(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    hero_dir = tmp_path / "hero"
    hero_dir.mkdir(parents=True, exist_ok=True)

    current_path = hero_dir / "neutral.png"
    stale_dir = tmp_path / "stale_duplicate"
    stale_dir.mkdir(parents=True, exist_ok=True)
    stale_path = stale_dir / "neutral.png"

    current_path.write_bytes(b"current")
    stale_path.write_bytes(b"stale")

    resolved = manager._canonicalize_character_image_path("hero", str(stale_path))

    assert resolved == str(current_path)


def test_character_library_default_config_supports_sheet_queries(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path), config=LibraryConfig())

    required = manager.get_required_sheet_variant_keys("hero")

    assert "neutral_standing" in required


def test_character_library_resolve_variant_normalizes_aliases(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "fear_standing": [CharacterImage(path="fear.png", expression="fear", pose="standing")],
            "sad_sitting": [CharacterImage(path="sad.png", expression="sad", pose="sitting")],
        },
    )

    expression, pose = manager.resolve_variant("hero", "worried", "listening")
    alt_expression, alt_pose = manager.resolve_variant("hero", "crying", "kneeling")

    assert expression == "fear"
    assert pose == "standing"
    assert alt_expression == "sad"
    assert alt_pose == "sitting"


def test_character_library_primes_motiontoon_parts(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    image_path = tmp_path / "hero.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0ioAAAAASUVORK5CYII="
        )
    )

    parts = manager.prime_motiontoon_parts(str(image_path), overlay_kind="document")

    assert Path(parts["background_path"]).exists()
    assert Path(parts["foreground_path"]).exists()


def test_character_library_get_character_parts_uses_sidecar(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    image_path = tmp_path / "hero.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0ioAAAAASUVORK5CYII="
        )
    )
    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "neutral_standing": [
                CharacterImage(path=str(image_path), expression="neutral", pose="standing")
            ]
        },
    )

    parts = manager.get_character_parts("hero", "neutral", "standing")

    assert Path(parts["background_path"]).exists()
    assert Path(parts["head_path"]).exists()


def test_character_library_builds_character_sheet_manifest(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    image_path = tmp_path / "hero.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0ioAAAAASUVORK5CYII="
        )
    )
    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "neutral_standing": [
                CharacterImage(path=str(image_path), expression="neutral", pose="standing", quality_score=0.9)
            ]
        },
    )

    sheet = manager.build_character_sheet("hero", save=True)

    sheet_path = tmp_path / "hero" / "sheet_manifest.json"
    assert sheet_path.exists()
    assert sheet["variant_count"] == 1
    assert "neutral_standing" in sheet["variants"]
    assert Path(sheet["variants"]["neutral_standing"]["parts"]["background_path"]).exists()


def test_build_character_sheet_rebuilds_parts_when_cached_rig_metadata_is_missing(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    image_path = Path(_make_sprite(tmp_path / "hero_talking_sitting.png", (86, 96, 154, 255)))
    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "talking_sitting": [
                CharacterImage(path=str(image_path), expression="talking", pose="sitting", quality_score=0.9)
            ]
        },
    )

    build_layered_cutout_assets(
        str(image_path),
        overlay_kind="document",
        strength=0.82,
    )

    sidecar_path = image_path.parent / "_layered" / f"{image_path.stem}__parts.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar.pop("rig", None)
    sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")

    sheet = manager.build_character_sheet("hero", save=False)
    rig = sheet["variants"]["talking_sitting"]["rig"]
    refreshed_meta = load_layered_cutout_metadata(str(image_path))

    assert rig["sprite_center_x"] is not None
    assert rig["sprite_center_y"] is not None
    assert rig["sprite_width_ratio"] is not None
    assert rig["sprite_height_ratio"] is not None
    assert refreshed_meta["rig"]["sprite_center_x"] == rig["sprite_center_x"]


def test_character_sheet_builds_real_face_parts_from_variant_images(tmp_path, monkeypatch):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    monkeypatch.setattr(manager, "_is_face_part_sane", lambda *args, **kwargs: True)
    neutral_path = _make_sprite(tmp_path / "neutral.png", (66, 86, 134, 255))
    talking_path = _make_sprite(tmp_path / "talking.png", (86, 96, 154, 255))
    blink_path = _make_sprite(tmp_path / "blink.png", (66, 86, 134, 255))
    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "neutral_standing": [CharacterImage(path=neutral_path, expression="neutral", pose="standing", quality_score=0.9)],
            "talking_standing": [CharacterImage(path=talking_path, expression="talking", pose="standing", quality_score=0.9)],
            "blink_standing": [CharacterImage(path=blink_path, expression="blink", pose="standing", quality_score=0.9)],
        },
    )

    sheet = manager.build_character_sheet("hero", save=True)
    face_parts = sheet["variants"]["neutral_standing"]["face_parts"]

    assert Path(face_parts["eyes_open_path"]).exists()
    assert Path(face_parts["eyes_closed_path"]).exists()
    assert Path(face_parts["mouth_closed_path"]).exists()
    assert Path(face_parts["mouth_open_path"]).exists()


def test_character_sheet_real_face_parts_synthesize_blink_and_talking_from_neutral_when_variants_missing(tmp_path, monkeypatch):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    monkeypatch.setattr(manager, "_is_face_part_sane", lambda *args, **kwargs: True)
    neutral_path = _make_sprite(tmp_path / "neutral_only.png", (66, 86, 134, 255))
    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "neutral_standing": [CharacterImage(path=neutral_path, expression="neutral", pose="standing", quality_score=0.9)],
        },
    )

    sheet = manager.build_character_sheet("hero", save=True)
    face_parts = sheet["variants"]["neutral_standing"]["face_parts"]

    assert Path(face_parts["eyes_open_path"]).exists()
    assert Path(face_parts["mouth_closed_path"]).exists()
    assert Path(face_parts["eyes_closed_path"]).exists()
    assert Path(face_parts["mouth_open_path"]).exists()


def test_character_sheet_real_face_parts_do_not_depend_on_portrait_generation(tmp_path, monkeypatch):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    monkeypatch.setattr(manager, "_is_face_part_sane", lambda *args, **kwargs: True)
    neutral_path = _make_sprite(tmp_path / "neutral.png", (66, 86, 134, 255))
    talking_path = _make_sprite(tmp_path / "talking.png", (86, 96, 154, 255))
    blink_path = _make_sprite(tmp_path / "blink.png", (66, 86, 134, 255))
    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "neutral_standing": [CharacterImage(path=neutral_path, expression="neutral", pose="standing", quality_score=0.9)],
            "talking_standing": [CharacterImage(path=talking_path, expression="talking", pose="standing", quality_score=0.9)],
            "blink_standing": [CharacterImage(path=blink_path, expression="blink", pose="standing", quality_score=0.9)],
        },
    )

    monkeypatch.setattr(manager, "_ensure_face_portrait_variant", lambda *args, **kwargs: "")

    sheet = manager.build_character_sheet("hero", save=True)
    face_parts = sheet["variants"]["neutral_standing"]["face_parts"]

    assert Path(face_parts["eyes_open_path"]).exists()
    assert Path(face_parts["eyes_closed_path"]).exists()
    assert Path(face_parts["mouth_closed_path"]).exists()
    assert Path(face_parts["mouth_open_path"]).exists()


def test_get_variant_face_crop_box_prefers_sane_detected_face_over_stale_overrides(tmp_path, monkeypatch):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    image_path = tmp_path / "hero.png"
    img = Image.new("RGBA", (160, 320), (244, 244, 244, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse((40, 20, 120, 100), fill=(235, 214, 186, 255))
    img.save(image_path)

    detected_face = (40, 20, 120, 100)
    monkeypatch.setattr(CharacterLibraryManager, "_detect_face_bbox_in_subject", lambda *args, **kwargs: detected_face)
    monkeypatch.setattr(CharacterLibraryManager, "_detect_dark_feature_box", lambda *args, **kwargs: None)

    crop = manager._get_variant_face_crop_box(
        str(image_path),
        {
            "face_part_boxes": {
                "face": [0.00, 0.00, 0.18, 0.18],
                "eyes": [0.00, 0.00, 0.12, 0.06],
                "mouth": [0.00, 0.00, 0.10, 0.06],
            }
        },
        part_kind="eyes",
    )

    expected = CharacterLibraryManager._part_box_from_face_bbox(detected_face, (160, 320), "eyes")

    assert crop == expected


def test_detect_face_bbox_in_subject_falls_back_to_full_image_detection(tmp_path, monkeypatch):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    image_path = tmp_path / "hero.png"
    Image.new("RGBA", (160, 320), (244, 244, 244, 255)).save(image_path)

    full_face = (60, 70, 110, 130)

    def fake_detect_face_bbox(image):
        return None if image.size != (160, 320) else full_face

    monkeypatch.setattr(CharacterLibraryManager, "_detect_face_bbox", staticmethod(fake_detect_face_bbox))

    with Image.open(image_path).convert("RGBA") as img:
        detected = manager._detect_face_bbox_in_subject(img, (0, 0, 160, 320))

    assert detected == full_face


def test_synthesize_closed_eyes_part_draws_non_blank_fallback_without_detected_features(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    base_path = tmp_path / "eyes_open.png"
    output_path = tmp_path / "eyes_closed.png"

    Image.new("RGBA", (80, 40), (214, 204, 198, 255)).save(base_path)

    saved = manager._synthesize_closed_eyes_part(str(base_path), output_path)

    assert saved == str(output_path)
    with Image.open(output_path).convert("RGBA") as img:
        assert img.getchannel("A").getbbox() is not None
    assert manager._is_face_part_sane(str(output_path), "eyes") is True


def test_synthesize_open_mouth_part_expands_tiny_detected_bbox(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    base_path = tmp_path / "mouth_closed.png"
    output_path = tmp_path / "mouth_open.png"

    img = Image.new("RGBA", (68, 38), (236, 236, 232, 255))
    draw = ImageDraw.Draw(img)
    draw.line((45, 6, 61, 30), fill=(30, 20, 20, 255), width=2)
    img.save(base_path)

    saved = manager._synthesize_open_mouth_part(str(base_path), output_path)

    assert saved == str(output_path)
    assert manager._is_face_part_sane(str(output_path), "mouth") is True


def test_face_part_sanity_rejects_blank_or_implausible_parts(tmp_path):
    blank = tmp_path / "blank.png"
    huge = tmp_path / "huge.png"

    Image.new("RGBA", (220, 60), (255, 255, 255, 255)).save(blank)
    Image.new("RGBA", (300, 200), (180, 180, 180, 255)).save(huge)

    assert CharacterLibraryManager._is_face_part_sane(str(blank), "eyes") is False
    assert CharacterLibraryManager._is_face_part_sane(str(huge), "mouth") is False


def test_character_sheet_variant_uses_fallback_chain_and_preferred_coverage(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    manager.config.preferred_expressions = ["talking", "fear"]
    manager.config.preferred_poses = ["sitting", "standing"]
    image_path = tmp_path / "hero_talking_sitting.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0ioAAAAASUVORK5CYII="
        )
    )
    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "talking_sitting": [
                CharacterImage(path=str(image_path), expression="talking", pose="sitting", quality_score=0.88)
            ]
        },
    )

    sheet = manager.build_character_sheet("hero", save=True)
    variant = manager.get_character_sheet_variant("hero", "angry", "running", fallback=True)

    assert "talking_sitting" in sheet["variants"]
    assert variant["variant_key"] == "talking_sitting"
    assert variant["expression"] == "talking"
    assert variant["pose"] == "sitting"


def test_required_sheet_variant_keys_prefer_pack_slot_mapping(tmp_path, monkeypatch):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    manager.config.required_variant_keys = ["neutral_standing", "happy_standing"]
    manager.config.required_variant_keys_by_slot = {"elder": ["blink_standing", "sad_sitting"]}
    monkeypatch.setattr(manager, "_resolve_pack_cast_slot_names", lambda character_id: ["elder"])

    required = manager.get_required_sheet_variant_keys("grandma")

    assert required == ["blink_standing", "sad_sitting", "neutral_standing"]


def test_required_sheet_variant_keys_union_multiple_pack_slots(tmp_path, monkeypatch):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    manager.config.required_variant_keys = ["neutral_standing"]
    manager.config.required_variant_keys_by_slot = {
        "deuteragonist": ["neutral_standing", "blink_standing", "neutral_walking"],
        "antagonist": ["neutral_standing", "fear_standing", "anger_standing"],
    }
    monkeypatch.setattr(manager, "_resolve_pack_cast_slot_names", lambda character_id: ["deuteragonist", "antagonist"])

    required = manager.get_required_sheet_variant_keys("young_man")

    assert required == [
        "neutral_standing",
        "blink_standing",
        "neutral_walking",
        "fear_standing",
        "anger_standing",
    ]


def test_character_sheet_coverage_reports_missing_required_variants(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    manager.config.preferred_expressions = ["neutral", "talking"]
    manager.config.preferred_poses = ["standing", "sitting"]
    image_path = tmp_path / "hero_neutral_standing.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0ioAAAAASUVORK5CYII="
        )
    )
    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "neutral_standing": [
                CharacterImage(path=str(image_path), expression="neutral", pose="standing", quality_score=0.88)
            ]
        },
    )

    coverage = manager.get_character_sheet_coverage("hero")

    assert "neutral_standing" in coverage["existing_keys"]
    assert "talking_sitting" in coverage["missing_keys"]
    assert coverage["is_complete"] is False


def test_character_sheet_falls_back_to_layered_face_parts_when_portrait_parts_fail(tmp_path, monkeypatch):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    monkeypatch.setattr(manager, "_build_part_from_portrait", lambda *args, **kwargs: "")
    monkeypatch.setattr(manager, "_is_face_part_sane", lambda *args, **kwargs: True)
    neutral_path = _make_sprite(tmp_path / "neutral.png", (66, 86, 134, 255))
    talking_path = _make_sprite(tmp_path / "talking.png", (86, 96, 154, 255))
    blink_path = _make_sprite(tmp_path / "blink.png", (66, 86, 134, 255))
    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "neutral_standing": [CharacterImage(path=neutral_path, expression="neutral", pose="standing", quality_score=0.9)],
            "talking_standing": [CharacterImage(path=talking_path, expression="talking", pose="standing", quality_score=0.9)],
            "blink_standing": [CharacterImage(path=blink_path, expression="blink", pose="standing", quality_score=0.9)],
        },
    )

    sheet = manager.build_character_sheet("hero", save=False)
    face_parts = sheet["variants"]["neutral_standing"]["face_parts"]

    assert face_parts["eyes_open_path"].endswith("__eyes_open.png")
    assert face_parts["eyes_closed_path"]
    assert face_parts["mouth_closed_path"].endswith("__mouth_closed.png")
    assert face_parts["mouth_open_path"]


def test_character_sheet_prefers_existing_layered_face_parts_before_portrait_generation(tmp_path, monkeypatch):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    monkeypatch.setattr(manager, "_is_face_part_sane", lambda *args, **kwargs: True)
    neutral_path = _make_sprite(tmp_path / "neutral.png", (66, 86, 134, 255))
    talking_path = _make_sprite(tmp_path / "talking.png", (86, 96, 154, 255))
    blink_path = _make_sprite(tmp_path / "blink.png", (66, 86, 134, 255))
    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "neutral_standing": [CharacterImage(path=neutral_path, expression="neutral", pose="standing", quality_score=0.9)],
            "talking_standing": [CharacterImage(path=talking_path, expression="talking", pose="standing", quality_score=0.9)],
            "blink_standing": [CharacterImage(path=blink_path, expression="blink", pose="standing", quality_score=0.9)],
        },
    )

    build_layered_cutout_assets(neutral_path, overlay_kind="document", strength=0.82)
    build_layered_cutout_assets(talking_path, overlay_kind="document", strength=0.82)
    build_layered_cutout_assets(blink_path, overlay_kind="document", strength=0.82)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("portrait generation should not run when layered face parts are already sane")

    monkeypatch.setattr(manager, "_build_part_from_portrait", _fail_if_called)

    sheet = manager.build_character_sheet("hero", save=False)
    face_parts = sheet["variants"]["neutral_standing"]["face_parts"]

    assert face_parts["eyes_open_path"].endswith("__eyes_open.png")
    assert face_parts["mouth_closed_path"].endswith("__mouth_closed.png")
    assert Path(face_parts["eyes_closed_path"]).exists()
    assert Path(face_parts["mouth_open_path"]).exists()


def test_character_sheet_reuses_cached_face_parts_before_portrait_generation(tmp_path, monkeypatch):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    monkeypatch.setattr(manager, "_is_face_part_sane", lambda *args, **kwargs: True)
    neutral_path = _make_sprite(tmp_path / "neutral.png", (66, 86, 134, 255))
    talking_path = _make_sprite(tmp_path / "talking.png", (86, 96, 154, 255))
    blink_path = _make_sprite(tmp_path / "blink.png", (66, 86, 134, 255))
    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "neutral_standing": [CharacterImage(path=neutral_path, expression="neutral", pose="standing", quality_score=0.9)],
            "talking_standing": [CharacterImage(path=talking_path, expression="talking", pose="standing", quality_score=0.9)],
            "blink_standing": [CharacterImage(path=blink_path, expression="blink", pose="standing", quality_score=0.9)],
        },
    )

    manager.build_character_sheet("hero", save=False)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("portrait generation should not run when cached face parts already exist")

    monkeypatch.setattr(manager, "_build_part_from_portrait", _fail_if_called)

    sheet = manager.build_character_sheet("hero", save=False)
    face_parts = sheet["variants"]["neutral_standing"]["face_parts"]

    assert Path(face_parts["eyes_open_path"]).exists()
    assert Path(face_parts["eyes_closed_path"]).exists()
    assert Path(face_parts["mouth_closed_path"]).exists()
    assert Path(face_parts["mouth_open_path"]).exists()


def test_character_sheet_coverage_prefers_explicit_required_variant_keys(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    manager.config.required_variant_keys = ["talking_sitting", "fear_standing"]

    coverage = manager.get_character_sheet_coverage("hero")

    assert coverage["required_keys"] == ["talking_sitting", "fear_standing", "neutral_standing"]
    assert "fear_standing" in coverage["missing_keys"]


def test_character_library_generation_overrides_pass_anchor_img2img_settings(tmp_path, monkeypatch):
    config = LibraryConfig(auto_generate_count=1, max_retries=1, min_quality_score=0.0)
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path), config=config)
    manager.sd_api_url = "http://sd.local"
    anchor_path = Path(_make_sprite(tmp_path / "anchor.png", (96, 126, 180, 255)))
    encoded_anchor = base64.b64encode(anchor_path.read_bytes()).decode("ascii")
    captured = {}

    monkeypatch.setattr(manager, "prime_motiontoon_parts", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        manager,
        "_validate_image",
        lambda *args, **kwargs: {"score": 1.0, "face_detected": True, "blur_score": 0.0},
    )
    monkeypatch.setattr(manager, "build_character_sheet", lambda *args, **kwargs: {"variants": {}})

    def _fake_generate_sd_image(**kwargs):
        captured.update(kwargs)
        return {"images": [encoded_anchor], "info": {"seed": 1234}}

    monkeypatch.setattr(manager, "_generate_sd_image", _fake_generate_sd_image)

    character_def = SimpleNamespace(
        id="hero",
        name="Hero",
        base_prompt="hero prompt",
        negative_prompt="",
        expressions={"neutral": "neutral face"},
        poses={"standing": "standing pose"},
    )

    success, generated = manager.generate_character_library(
        character_def=character_def,
        variant_keys=["neutral_standing"],
        images_per_combo=1,
        generation_overrides_by_variant={
            "neutral_standing": {
                "init_image_path": str(anchor_path),
                "denoising_strength": 0.41,
                "prompt_suffix": "same face anchor",
                "negative_prompt_suffix": "different person",
                "width": 640,
                "height": 960,
            }
        },
    )

    assert success is True
    assert len(generated) == 1
    assert captured["init_image_path"] == str(anchor_path)
    assert captured["denoising_strength"] == 0.41
    assert captured["width"] == 640
    assert captured["height"] == 960
    assert "same face anchor" in captured["prompt"]
    assert "different person" in captured["negative_prompt"]


def test_character_library_generation_overrides_pass_consistency_and_pose_reference_settings(tmp_path, monkeypatch):
    config = LibraryConfig(auto_generate_count=1, max_retries=1, min_quality_score=0.0)
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path), config=config)
    manager.sd_api_url = "http://sd.local"
    reference_path = Path(_make_sprite(tmp_path / "reference.png", (96, 126, 180, 255)))
    pose_path = Path(_make_sprite(tmp_path / "pose.png", (180, 126, 96, 255)))
    encoded_image = base64.b64encode(reference_path.read_bytes()).decode("ascii")
    captured = {}

    monkeypatch.setattr(manager, "prime_motiontoon_parts", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        manager,
        "_validate_image",
        lambda *args, **kwargs: {"score": 1.0, "face_detected": True, "blur_score": 0.0},
    )
    monkeypatch.setattr(manager, "build_character_sheet", lambda *args, **kwargs: {"variants": {}})

    def _fake_generate_sd_image(**kwargs):
        captured.update(kwargs)
        return {"images": [encoded_image], "info": {"seed": 1234}}

    monkeypatch.setattr(manager, "_generate_sd_image", _fake_generate_sd_image)

    character_def = SimpleNamespace(
        id="hero",
        name="Hero",
        base_prompt="hero prompt",
        negative_prompt="",
        expressions={"neutral": "neutral face"},
        poses={"sitting": "sitting pose"},
    )

    success, generated = manager.generate_character_library(
        character_def=character_def,
        variant_keys=["neutral_sitting"],
        images_per_combo=1,
        generation_overrides_by_variant={
            "neutral_sitting": {
                "consistency_image_path": str(reference_path),
                "consistency_mode": "face_plus",
                "consistency_weight": 0.81,
                "pose_image_path": str(pose_path),
                "pose_module": "reference_only",
                "pose_weight": 0.58,
                "pose_control_mode": "My prompt is more important",
                "pose_end_step": 0.85,
                "prompt_suffix": "same seated character",
                "negative_prompt_suffix": "different outfit",
            }
        },
    )

    assert success is True
    assert len(generated) == 1
    assert captured["consistency_image_path"] == str(reference_path)
    assert captured["consistency_mode"] == "face_plus"
    assert captured["consistency_weight"] == 0.81
    assert captured["pose_image_path"] == str(pose_path)
    assert captured["pose_module"] == "reference_only"
    assert captured["pose_weight"] == 0.58
    assert captured["pose_control_mode"] == "My prompt is more important"
    assert captured["pose_end_step"] == 0.85
    assert "same seated character" in captured["prompt"]
    assert "different outfit" in captured["negative_prompt"]


def test_apply_consistency_reference_payload_adds_controlnet_args(tmp_path, monkeypatch):
    import core.ip_adapter_bridge as bridge_module

    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    manager.sd_api_url = "http://sd.local"
    reference_path = Path(_make_sprite(tmp_path / "reference.png", (110, 150, 200, 255)))

    class DummyBridge:
        def enhance_payload(self, base_payload, ip_config, reference_image_path=None):
            payload = dict(base_payload)
            payload["alwayson_scripts"] = {
                "controlnet": {
                    "args": [
                        {
                            "reference": reference_image_path,
                            "mode": ip_config.mode.value,
                            "weight": ip_config.weight,
                        }
                    ]
                }
            }
            return payload

    monkeypatch.setattr(bridge_module, "get_ip_adapter_bridge", lambda sd_url=None: DummyBridge())

    payload = manager._apply_consistency_reference_payload(
        {"prompt": "hero"},
        consistency_image_path=str(reference_path),
        consistency_mode="full",
        consistency_weight=0.67,
    )

    args = payload["alwayson_scripts"]["controlnet"]["args"][0]
    assert args["reference"] == str(reference_path)
    assert args["mode"] == "ip-adapter-full"
    assert args["weight"] == 0.67


def test_append_pose_reference_payload_appends_reference_only_controlnet_unit(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    pose_path = Path(_make_sprite(tmp_path / "pose.png", (110, 150, 200, 255)))

    payload = manager._append_pose_reference_payload(
        {
            "prompt": "hero",
            "alwayson_scripts": {
                "controlnet": {
                    "args": [{"module": "ip-adapter-auto", "weight": 0.82}]
                }
            },
        },
        pose_image_path=str(pose_path),
        pose_module="reference_only",
        pose_weight=0.61,
        pose_control_mode="My prompt is more important",
        pose_end_step=0.88,
    )

    args = payload["alwayson_scripts"]["controlnet"]["args"]
    assert len(args) == 2
    assert args[1]["module"] == "reference_only"
    assert args[1]["model"] == "None"
    assert args[1]["weight"] == 0.61
    assert args[1]["control_mode"] == "My prompt is more important"
    assert args[1]["guidance_end"] == 0.88
    assert args[1]["image"]


def test_scene_analyzer_adds_continuity_hint_for_same_character_and_location():
    analyzer = SceneAnalyzer(gemini_client=None, character_definitions=[])
    analyzer.previous_scenes = [
        SceneAnalysisResult(
            scene_id="s0",
            location="hallway",
            characters=[CharacterState(id="protagonist", emotion="neutral", action="standing")],
        )
    ]

    current = SceneAnalysisResult(
        scene_id="s1",
        location="hallway",
        characters=[CharacterState(id="protagonist", emotion="fear", action="standing")],
    )

    action = analyzer._determine_image_action(current)

    assert action == "expression"
    assert "same character as previous panel" in current.continuity_hint
    assert "same location" in current.continuity_hint


def test_prompt_composer_includes_continuity_hint_in_positive_prompt():
    character = SimpleNamespace(
        id="protagonist",
        name="Hero",
        base_prompt="young woman, black bob haircut, beige cardigan",
        style_suffix="webtoon style",
        expressions={"fear": "frightened expression"},
        poses={"standing": "standing pose"},
        lora=None,
        gender_negative="",
        age_negative="",
    )
    composer = PromptComposer(character_definitions=[character], sd_model_config={})
    scene = SceneAnalysisResult(
        scene_id="s1",
        location="hallway",
        characters=[CharacterState(id="protagonist", emotion="fear", action="standing")],
        continuity_hint="same character as previous panel, same face, same hairstyle, same outfit",
    )

    result = composer.compose_prompt(scene)

    assert result.continuity_hint in result.positive
    assert "same character as previous panel" in result.positive


def test_char_defs_from_dict_preserves_pack_constraints_and_aliases():
    characters = char_defs_from_dict(
        {
            "grandma": {
                "name": "Grandma",
                "display_name": "Grandma",
                "base": "single elderly korean woman, visible wrinkles",
                "style": "historical motiontoon, visibly old woman",
                "gender_negative": "(male:1.7), beard",
                "age_negative": "(young:1.8), smooth skin",
                "aliases": ["elder", "grandmother"],
            }
        },
        include_aliases=True,
        include_lora=True,
    )

    assert len(characters) == 1
    character = characters[0]
    assert character.display_name == "Grandma"
    assert character.style_suffix == "historical motiontoon, visibly old woman"
    assert character.gender_negative == "(male:1.7), beard"
    assert character.age_negative == "(young:1.8), smooth skin"
    assert character.aliases == ["grandma", "elder", "grandmother"]


def test_prompt_composer_library_prompt_uses_pack_style_and_negative_constraints_for_dict_defs():
    composer = PromptComposer(
        character_definitions={
            "grandma": {
                "name": "Grandma",
                "base": "single elderly korean woman, visible wrinkles",
                "style": "historical motiontoon, visibly old woman",
                "gender_negative": "(male:1.7), beard",
                "age_negative": "(young:1.8), smooth skin",
            }
        },
        sd_model_config={
            "steps": 28,
            "cfg_scale": 6.0,
            "checkpoint": "meinamix_v12Final.safetensors",
            "scheduler": "Normal",
        },
    )

    result = composer.compose_character_library_prompt("grandma", "sad", "sitting")

    assert "single elderly korean woman, visible wrinkles" in result.positive
    assert "historical motiontoon, visibly old woman" in result.positive
    assert "(male:1.7), beard" in result.negative
    assert "(young:1.8), smooth skin" in result.negative
    assert "plain solid light gray backdrop" in result.positive
    assert result.width == 512
    assert result.height == 768
    assert result.steps == 16
    assert result.cfg_scale == 6.0
    assert result.checkpoint == "meinamix_v12Final.safetensors"
    assert result.scheduler == "Normal"


def test_prompt_composer_scene_prompt_includes_character_lora_tag_and_trigger():
    composer = PromptComposer(
        character_definitions={
            "young_woman": {
                "name": "Young Woman",
                "base": "single korean adult woman",
                "style": "modern cautionary drama motiontoon",
                "expressions": {"fear": "worried adult face"},
                "poses": {"standing": "upright standing pose"},
                "lora": {"name": "scam_young_woman", "weight": 0.75, "trigger": "scam_yw"},
            }
        },
        sd_model_config={},
    )
    scene = SceneAnalysisResult(
        scene_id="scene_lora",
        location="bank",
        characters=[CharacterState(id="young_woman", emotion="fear", action="standing")],
        sd_prompt="single person, full body at a bank counter",
    )

    result = composer.compose_prompt(scene)

    assert "<lora:scam_young_woman:0.75>" in result.positive
    assert "scam_yw" in result.positive


def test_prompt_composer_library_prompt_includes_character_lora_tag_and_trigger():
    composer = PromptComposer(
        character_definitions={
            "young_man": {
                "name": "Young Man",
                "base": "single korean adult man",
                "style": "modern cautionary drama motiontoon",
                "lora": {"name": "scam_young_man", "weight": 0.7, "trigger": "scam_ym"},
            }
        },
        sd_model_config={},
    )

    result = composer.compose_character_library_prompt("young_man", "neutral", "walking")

    assert "<lora:scam_young_man:0.7>" in result.positive
    assert "scam_ym" in result.positive


def test_prompt_composer_library_prompt_prefers_character_expression_and_pose_overrides():
    composer = PromptComposer(
        character_definitions={
            "young_man": {
                "name": "Young Man",
                "base": "single korean adult man",
                "style": "historical motiontoon",
                "expressions": {
                    "neutral": "calm composed adult male face, mouth closed",
                },
                "poses": {
                    "standing": "upright standing pose, full body fully inside frame, no dramatic action",
                },
            }
        },
        sd_model_config={},
    )

    result = composer.compose_character_library_prompt("young_man", "neutral", "standing")

    assert "calm composed adult male face, mouth closed" in result.positive
    assert "upright standing pose, full body fully inside frame, no dramatic action" in result.positive
    assert "neutral face, calm expression" not in result.positive
    assert "standing pose, arms relaxed, balanced posture" not in result.positive


def test_visual_storytelling_prefers_explicit_dialogue_location_hint(tmp_path):
    director = VisualStorytellingDirector(output_dir=str(tmp_path))
    scene = SceneAnalysisResult(scene_id="s1", location="동굴", time_of_day="night")

    updated = director._apply_dialogue_visual_hints(
        scene,
        {
            "location": "장터 골목",
            "time": "낮",
            "image_prompt": "joseon market alley, no people",
        },
    )

    assert updated.location == "장터 골목"
    assert updated.time_of_day == "낮"
    assert "joseon market alley" in updated.sd_prompt


def test_prompt_composer_panel_card_mode_compiles_scene_prompt_from_structure():
    character = SimpleNamespace(
        id="protagonist",
        name="Hero",
        base_prompt="young woman, black bob haircut, beige cardigan",
        style_suffix="webtoon style",
        expressions={"fear": "frightened expression"},
        poses={"standing": "standing pose"},
        lora=None,
        gender_negative="",
        age_negative="",
    )
    composer = PromptComposer(
        character_definitions=[character],
        sd_model_config={},
        art_style_config={
            "art_style_prefix": "monochrome manga, black and white ink drawing",
            "texture_keywords": "clean lineart, high contrast",
        },
        prompt_strategy="panel_card",
        llm_hint_tag_limit=2,
    )
    scene = SceneAnalysisResult(
        scene_id="s_panel",
        location="hallway",
        location_detail="dark apartment hallway",
        atmosphere="horror",
        camera_shot="close-up",
        key_props=["letter"],
        outfit_hint="school uniform",
        continuity_hint="same character as previous panel",
        characters=[CharacterState(id="protagonist", emotion="fear", action="standing")],
        sd_prompt="monochrome manga, black and white ink drawing, (solo, angry expression:1.3), flickering fluorescent light, dutch angle, fully clothed",
    )

    result = composer.compose_prompt(scene)

    assert "(solo, angry expression:1.3)" not in result.positive
    assert "letter" in result.scene_prompt
    assert "close-up" in result.scene_prompt
    assert "same character as previous panel" in result.positive


def test_prompt_composer_legacy_mode_keeps_raw_sd_prompt_priority():
    composer = PromptComposer(
        character_definitions=[],
        sd_model_config={},
        prompt_strategy="legacy_sd_prompt",
    )
    scene = SceneAnalysisResult(
        scene_id="s_legacy",
        sd_prompt="raw custom weighted focus, eerie fog, wide shot",
    )

    result = composer.compose_prompt(scene)

    assert "raw custom weighted focus" in result.positive


def test_image_pipeline_seed_helpers_are_deterministic():
    pipeline = ImagePipeline(
        channel="horror",
        mode="story",
        sd_url="http://127.0.0.1:7860",
        sd_webui_root="C:\\sd",
        data_dir="C:\\data",
        assets_dir="C:\\assets",
    )

    base_seed = pipeline._resolve_scene_seed(
        character_id="protagonist",
        speaker="주인공",
        location="hallway",
        prompt="dark hallway, frightened expression",
        mode_tag="v59",
    )
    same_seed = pipeline._resolve_scene_seed(
        character_id="protagonist",
        speaker="주인공",
        location="hallway",
        prompt="dark hallway, frightened expression",
        mode_tag="v59",
    )
    retry_seed = pipeline._variant_seed(base_seed, 1)

    assert base_seed == same_seed
    assert retry_seed != base_seed
    assert retry_seed == pipeline._variant_seed(base_seed, 1)


def test_image_pipeline_cached_scene_seed_prefers_character_id_and_aliases_speaker():
    pipeline = ImagePipeline(
        channel="horror",
        mode="story",
        sd_url="http://127.0.0.1:7860",
        sd_webui_root="C:\\sd",
        data_dir="C:\\data",
        assets_dir="C:\\assets",
    )
    cache = {}

    payload = pipeline._apply_cached_scene_seed(
        {"prompt": "dark hallway, frightened expression"},
        cache,
        character_id="young_man",
        speaker="김영수",
        location="hallway",
        mode_tag="v59",
    )

    expected = pipeline._resolve_scene_seed(
        character_id="young_man",
        speaker="김영수",
        location="hallway",
        prompt="dark hallway, frightened expression",
        mode_tag="v59",
    )
    followup = pipeline._apply_cached_scene_seed(
        {"prompt": "other place"},
        cache,
        character_id="",
        speaker="김영수",
        location="kitchen",
        mode_tag="v59",
    )

    assert payload["seed"] == expected
    assert cache["young_man"] == expected
    assert cache["김영수"] == expected
    assert followup["seed"] == expected


def test_image_pipeline_legacy_generate_images_applies_consistency_for_non_senior(tmp_path, monkeypatch):
    pipeline = ImagePipeline(
        channel="horror",
        mode="story",
        sd_url="http://127.0.0.1:7860",
        sd_webui_root="C:\\sd",
        data_dir=str(tmp_path),
        assets_dir="C:\\assets",
    )
    captured = {}

    pipeline._apply_consistency_fn = lambda payload: {**payload, "consistency_marker": True}
    pipeline._apply_vram_safety = lambda payload, purpose="image": {**payload, "vram_marker": purpose}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"images": [base64.b64encode(b"img").decode("ascii")]}

    def _fake_post(url, json, timeout):
        captured.update(json)
        return _Resp()

    import requests

    monkeypatch.setattr(requests, "post", _fake_post)
    files = pipeline.generate_images(["hero in hallway"], "proj", "horror")

    assert captured["consistency_marker"] is True
    assert captured["vram_marker"] == "image"
    assert len(files) == 1
    assert Path(files[0]).exists()


class _FakeCharLibrary:
    def __init__(self):
        self.calls = []
        self.available = {}
        self.sd_api_url = "http://sd"
        self.sheet_parts = {}

    def find_character_by_alias(self, alias):
        mapping = {
            "Hero": "protagonist",
            "Ghost": "ghost",
            "Narrator": "",
        }
        return mapping.get(alias, "")

    def has_character(self, character_id, min_expressions=3, min_images_per_expression=1):
        return False

    def generate_character_library(self, character_def, expressions=None, poses=None, variant_keys=None, images_per_combo=None, **kwargs):
        self.calls.append(
            {
                "id": character_def.id,
                "expressions": expressions,
                "poses": poses,
                "variant_keys": variant_keys,
                "images_per_combo": images_per_combo,
                "kwargs": kwargs,
            }
        )
        return True, []

    def get_character_image(self, character_id, expression="neutral", pose="standing", fallback=True):
        return self.available.get((character_id, expression, pose))

    def get_character_parts(self, character_id, expression="neutral", pose="standing", fallback=True):
        image_path = self.available.get((character_id, expression, pose))
        if not image_path:
            return {}
        return {"background_path": f"{image_path}.bg", "foreground_path": f"{image_path}.fg"}

    def bind_character_sheet_variant(self, target_image_path, character_id, expression="neutral", pose="standing", fallback=True, rig_overrides=None):
        return self.sheet_parts.get((character_id, expression, pose), {})

    def get_character_sheet_variant(self, character_id, expression="neutral", pose="standing", fallback=True):
        parts = self.sheet_parts.get((character_id, expression, pose))
        image_path = self.available.get((character_id, expression, pose), "")
        if not parts and fallback:
            parts = self.sheet_parts.get((character_id, "neutral", "standing"), {})
            image_path = image_path or self.available.get((character_id, "neutral", "standing"), "")
        if not parts and not image_path:
            return {}
        return {
            "image_path": image_path,
            "parts": parts,
            "expression": expression,
            "pose": pose,
        }

    def has_character_sheet_variant(self, character_id, expression="neutral", pose="standing", fallback=True):
        return bool(self.get_character_sheet_variant(character_id, expression, pose, fallback=fallback))

    def get_character_sheet_coverage(self, character_id, available_expressions=None, available_poses=None, required_variant_keys=None):
        required = []
        if required_variant_keys:
            required = list(required_variant_keys)
        else:
            expressions = list(available_expressions or [])
            poses = list(available_poses or [])
            for expr in expressions:
                for pose in poses:
                    required.append(f"{expr}_{pose}")
        existing = []
        missing = []
        for key in required:
            expr, pose = key.split("_", 1)
            if self.get_character_sheet_variant(character_id, expr, pose, fallback=False):
                existing.append(key)
            else:
                missing.append(key)
        return {
            "required_keys": required,
            "existing_keys": existing,
            "missing_keys": missing,
            "coverage_ratio": (len(existing) / len(required)) if required else 1.0,
            "is_complete": not missing,
        }

    def resolve_variant(self, character_id, expression, pose):
        expression_map = {"worried": "fear", "scared": "fear", "crying": "sad"}
        pose_map = {"listening": "standing", "kneeling": "sitting"}
        return expression_map.get(expression, expression), pose_map.get(pose, pose)


def _make_director(tmp_path, char_library=None):
    director = VisualStorytellingDirector(
        config={},
        gemini_client=None,
        sd_client=None,
        output_dir=str(tmp_path),
        char_library_manager=char_library,
    )
    director.prompt_composer = SimpleNamespace(
        char_map={
            "protagonist": SimpleNamespace(
                id="protagonist",
                expressions={"neutral": "neutral", "talking": "talking", "fear": "fear"},
                poses={"standing": "standing", "listening": "listening", "walking": "walking"},
            ),
            "ghost": SimpleNamespace(
                id="ghost",
                expressions={"neutral": "neutral", "fear": "fear"},
                poses={"standing": "standing"},
            ),
        }
    )
    return director


def test_visual_director_major_character_references_use_top_speakers(tmp_path):
    char_library = _FakeCharLibrary()
    director = _make_director(tmp_path, char_library=char_library)

    dialogues = [
        {"speaker": "Hero", "text": "a"},
        {"speaker": "Ghost", "text": "b"},
        {"speaker": "Hero", "text": "c"},
        {"speaker": "Hero", "text": "d"},
        {"speaker": "Narrator", "text": "e"},
    ]

    director._ensure_major_character_references(dialogues)

    assert [call["id"] for call in char_library.calls] == ["protagonist", "ghost"]
    assert "talking" in char_library.calls[0]["expressions"]
    assert char_library.calls[0]["images_per_combo"] == 2


def test_visual_director_major_character_references_accept_character_key(tmp_path):
    char_library = _FakeCharLibrary()
    director = _make_director(tmp_path, char_library=char_library)

    dialogues = [
        {"character": "Hero", "text": "a"},
        {"character": "Hero", "text": "b"},
        {"character": "Ghost", "text": "c"},
    ]

    director._ensure_major_character_references(dialogues)

    assert [call["id"] for call in char_library.calls] == ["protagonist", "ghost"]


def test_visual_director_major_character_references_only_generate_missing_sheet_variants(tmp_path):
    char_library = _FakeCharLibrary()
    char_library.sheet_parts[("protagonist", "neutral", "standing")] = {
        "background_path": "sheet_bg.png",
    }
    director = _make_director(tmp_path, char_library=char_library)
    director.config = {
        "character_library": {
            "preferred_expressions": ["neutral", "talking"],
            "preferred_poses": ["standing"],
        }
    }

    dialogues = [
        {"speaker": "Hero", "text": "a"},
        {"speaker": "Hero", "text": "b"},
    ]

    director._ensure_major_character_references(dialogues)

    assert len(char_library.calls) == 1
    assert char_library.calls[0]["id"] == "protagonist"
    assert char_library.calls[0]["variant_keys"] == ["talking_standing"]


def test_visual_director_major_character_references_respect_slot_specific_required_variants(tmp_path):
    char_library = _FakeCharLibrary()
    char_library.sheet_parts[("protagonist", "neutral", "standing")] = {
        "background_path": "sheet_bg.png",
    }
    director = _make_director(tmp_path, char_library=char_library)
    director.config = {
        "character_library": {
            "preferred_expressions": ["neutral", "talking"],
            "preferred_poses": ["standing"],
            "required_variant_keys_by_slot": {
                "protagonist": ["neutral_standing", "fear_standing"]
            },
        }
    }
    director._get_pack_motiontoon_cast_slots = lambda: {
        "protagonist": {"character_id": "protagonist"}
    }

    dialogues = [
        {"speaker": "Hero", "text": "a"},
        {"speaker": "Hero", "text": "b"},
    ]

    director._ensure_major_character_references(dialogues)

    assert len(char_library.calls) == 1
    assert char_library.calls[0]["variant_keys"] == ["fear_standing"]


def test_visual_director_reuse_prefers_same_character_over_last_global(tmp_path):
    director = _make_director(tmp_path)
    hero_image = GeneratedImage(path="hero.png", scene_id="hero_scene")
    villain_image = GeneratedImage(path="villain.png", scene_id="villain_scene")
    director.character_panel_state["protagonist"] = {
        "image": hero_image,
        "location": "hallway",
        "emotion": "neutral",
        "pose": "standing",
    }
    director.location_panel_state["hallway"] = {
        "image": villain_image,
        "location": "hallway",
    }
    director.previous_images["villain_scene"] = villain_image

    selected = director._get_reuse_source(
        {"char_id": "protagonist", "location": "hallway", "emotion": "neutral", "pose": "standing"}
    )

    assert selected is hero_image


def test_visual_director_same_character_sequence_prefers_reuse_then_expression(tmp_path):
    char_library = _FakeCharLibrary()
    char_library.available[("protagonist", "fear", "standing")] = "fear.png"
    director = _make_director(tmp_path, char_library=char_library)
    director.character_panel_state["protagonist"] = {
        "image": GeneratedImage(path="hero_prev.png", scene_id="prev"),
        "location": "hallway",
        "emotion": "neutral",
        "pose": "standing",
    }

    reuse_action = director._select_effective_action(
        "new",
        {"char_id": "protagonist", "location": "hallway", "emotion": "neutral", "pose": "standing"},
    )
    expression_action = director._select_effective_action(
        "new",
        {"char_id": "protagonist", "location": "hallway", "emotion": "fear", "pose": "standing"},
    )

    assert reuse_action == "reuse"
    assert expression_action == "expression"


def test_scene_analyzer_hydrates_camera_props_and_outfit():
    character = SimpleNamespace(
        id="protagonist",
        name="Hero",
        base_prompt="young woman, black bob haircut, school uniform",
        aliases=["Hero"],
    )
    analyzer = SceneAnalyzer(gemini_client=None, character_definitions=[character])
    result = SceneAnalysisResult(
        scene_id="s1",
        original_dialogue="She clutched the candle and stared at the mirror.",
        speaker="Hero",
        characters=[CharacterState(id="protagonist", name="Hero", emotion="fear", action="standing")],
        scene_keywords=["mirror", "shadows"],
        sd_prompt="dim hallway, close-up, candle, tense atmosphere",
    )

    hydrated = analyzer._hydrate_visual_state(result)

    assert hydrated.camera_shot == "close-up"
    assert "candle" in hydrated.key_props
    assert hydrated.outfit_hint == "school uniform"


def test_prompt_composer_scene_prompt_includes_props_camera_and_outfit():
    composer = PromptComposer(character_definitions=[], sd_model_config={})
    scene = SceneAnalysisResult(
        scene_id="s1",
        location="hallway",
        camera_shot="close-up",
        key_props=["letter", "candle"],
        outfit_hint="school uniform",
        scene_keywords=["shadows"],
    )

    scene_prompt = composer._get_scene_prompt(scene)

    assert "letter" in scene_prompt
    assert "close-up" in scene_prompt
    assert "school uniform" in scene_prompt


def test_visual_director_cut_state_backfills_outfit_props_and_camera(tmp_path):
    director = _make_director(tmp_path)
    director.character_panel_state["protagonist"] = {
        "image": GeneratedImage(path="hero_prev.png", scene_id="prev"),
        "location": "hallway",
        "emotion": "neutral",
        "pose": "standing",
        "camera_shot": "close-up",
        "outfit_hint": "school uniform",
        "key_props": ["letter"],
    }

    scene = SceneAnalysisResult(
        scene_id="s2",
        location="hallway",
        characters=[CharacterState(id="protagonist", emotion="neutral", action="standing")],
    )
    scene_state = director._extract_scene_identity(scene, 2)

    director._augment_scene_with_cut_state(scene, scene_state)

    assert scene.camera_shot == "close-up"
    assert scene.outfit_hint == "school uniform"
    assert scene.key_props == ["letter"]
    assert "same face" in scene.continuity_hint


def test_visual_director_prop_change_forces_new_panel(tmp_path):
    char_library = _FakeCharLibrary()
    char_library.available[("protagonist", "neutral", "standing")] = "neutral.png"
    director = _make_director(tmp_path, char_library=char_library)
    director.character_panel_state["protagonist"] = {
        "image": GeneratedImage(path="hero_prev.png", scene_id="prev"),
        "location": "hallway",
        "emotion": "neutral",
        "pose": "standing",
        "camera_shot": "close-up",
        "outfit_hint": "school uniform",
        "key_props": ["letter"],
    }

    action = director._select_effective_action(
        "new",
        {
            "char_id": "protagonist",
            "location": "hallway",
            "emotion": "neutral",
            "pose": "standing",
            "camera_shot": "close-up",
            "outfit_hint": "school uniform",
            "key_props": ["knife"],
        },
    )

    assert action == "new"


def test_visual_director_prop_change_without_library_does_not_reuse(tmp_path):
    director = _make_director(tmp_path)
    director.character_panel_state["protagonist"] = {
        "image": GeneratedImage(path="hero_prev.png", scene_id="prev"),
        "location": "hallway",
        "emotion": "neutral",
        "pose": "standing",
        "camera_shot": "close-up",
        "outfit_hint": "school uniform",
        "key_props": ["letter"],
    }

    action = director._select_effective_action(
        "new",
        {
            "char_id": "protagonist",
            "location": "hallway",
            "emotion": "neutral",
            "pose": "standing",
            "camera_shot": "close-up",
            "outfit_hint": "school uniform",
            "key_props": ["knife"],
        },
    )

    assert action == "new"


def test_visual_director_normalizes_scene_variant_before_library_lookup(tmp_path):
    char_library = _FakeCharLibrary()
    char_library.available[("protagonist", "fear", "standing")] = "fear.png"
    director = _make_director(tmp_path, char_library=char_library)

    result = director._get_from_library("protagonist", "worried", "listening")

    assert result == "fear.png"


def test_visual_director_new_image_primes_motiontoon_parts(tmp_path):
    char_library = _FakeCharLibrary()
    primed = {}
    lib_image = tmp_path / "library.png"
    lib_image.write_bytes(b"test")
    char_library.available[("protagonist", "neutral", "standing")] = str(lib_image)

    def _prime(image_path, overlay_kind="document", rig_overrides=None):
        primed["path"] = image_path
        return {"background_path": f"{image_path}.bg"}

    char_library.prime_motiontoon_parts = _prime
    director = _make_director(tmp_path, char_library=char_library)
    director.sd_client = None
    scene = SimpleNamespace(
        scene_id="scene_0001",
        characters=[SimpleNamespace(id="protagonist", emotion="neutral", action="standing")],
    )

    result = director._handle_new_image(scene, 0, tmp_path)

    assert result.parts["background_path"].endswith(".bg")
    assert primed["path"].endswith("scene_0001.png")


def test_visual_director_expression_swap_copies_library_image_and_primes_parts(tmp_path):
    char_library = _FakeCharLibrary()
    primed = {}
    lib_image = tmp_path / "library_expr.png"
    lib_image.write_bytes(b"expr")
    char_library.available[("protagonist", "fear", "standing")] = str(lib_image)

    def _prime(image_path, overlay_kind="document", rig_overrides=None):
        primed["path"] = image_path
        primed["rig"] = rig_overrides or {}
        return {"background_path": f"{image_path}.bg"}

    char_library.prime_motiontoon_parts = _prime
    director = _make_director(tmp_path, char_library=char_library)
    director._get_motiontoon_rig_overrides = lambda char_id, emotion="", pose="": {"face_anchor_x": 0.61}
    scene = SimpleNamespace(
        scene_id="scene_expr",
        characters=[SimpleNamespace(id="protagonist", emotion="worried", action="listening")],
    )

    result = director._handle_expression_swap(scene, 0, tmp_path)

    assert result.path.endswith("scene_expr.png")
    assert result.parts["background_path"].endswith(".bg")
    assert primed["path"].endswith("scene_expr.png")
    assert primed["rig"]["face_anchor_x"] == 0.61


def test_visual_director_expression_swap_prefers_character_sheet_parts(tmp_path):
    char_library = _FakeCharLibrary()
    lib_image = tmp_path / "library_expr.png"
    lib_image.write_bytes(b"expr")
    char_library.available[("protagonist", "fear", "standing")] = str(lib_image)
    char_library.sheet_parts[("protagonist", "fear", "standing")] = {
        "background_path": "sheet_bg.png",
        "foreground_path": "sheet_fg.png",
        "head_path": "sheet_head.png",
        "body_path": "sheet_body.png",
        "left_arm_path": "sheet_left.png",
        "right_arm_path": "sheet_right.png",
        "eyes_open_path": "sheet_eyes_open.png",
        "eyes_closed_path": "sheet_eyes_closed.png",
        "mouth_closed_path": "sheet_mouth_closed.png",
        "mouth_open_path": "sheet_mouth_open.png",
    }

    def _prime(*args, **kwargs):
        raise AssertionError("prime_motiontoon_parts should not run when sheet parts exist")

    char_library.prime_motiontoon_parts = _prime
    director = _make_director(tmp_path, char_library=char_library)
    scene = SimpleNamespace(
        scene_id="scene_sheet",
        characters=[SimpleNamespace(id="protagonist", emotion="worried", action="listening")],
    )

    result = director._handle_expression_swap(scene, 0, tmp_path)

    assert result.path.endswith("scene_sheet.png")
    assert result.parts["eyes_open_path"] == "sheet_eyes_open.png"
    assert result.parts["mouth_open_path"] == "sheet_mouth_open.png"


def test_visual_director_expression_swap_simple_sprite_without_reuse_falls_back_to_new_image(tmp_path):
    char_library = _FakeCharLibrary()
    lib_image = tmp_path / "library_expr.png"
    lib_image.write_bytes(b"expr")
    char_library.available[("protagonist", "fear", "standing")] = str(lib_image)
    director = _make_director(tmp_path, char_library=char_library)
    director._use_simple_character_sprite_mode = lambda: True
    director._get_reuse_source = lambda scene_state: None
    director._handle_new_image = lambda scene, index, output_path: GeneratedImage(
        path="regenerated.png",
        scene_id="scene_expr",
        action="new",
    )
    scene = SimpleNamespace(
        scene_id="scene_expr",
        characters=[SimpleNamespace(id="protagonist", emotion="worried", action="listening")],
    )

    result = director._handle_expression_swap(scene, 0, tmp_path)

    assert result.path == "regenerated.png"
    assert result.action == "new"


def test_visual_director_new_image_simple_sprite_without_library_avoids_fake_split_parts(tmp_path):
    char_library = _FakeCharLibrary()
    director = _make_director(tmp_path, char_library=char_library)
    director._use_simple_character_sprite_mode = lambda: True
    director.prompt_composer = SimpleNamespace(
        compose_prompt=lambda scene: SimpleNamespace(positive="bg", negative="neg"),
        char_map={},
    )

    def _call_sd_api(composed, image_path):
        Path(image_path).write_bytes(b"img")
        return {"seed": 1}

    director._call_sd_api = _call_sd_api
    director.sd_client = object()
    director._create_placeholder_image = lambda image_path: Path(image_path).write_bytes(b"img")
    director._get_from_library = lambda char_id, emotion, pose: ""
    director._get_motiontoon_rig_overrides = lambda char_id, emotion="", pose="": {"overlay_kind": "document"}

    primed = {}

    def _prime(image_path, overlay_kind="document", rig_overrides=None):
        primed["called"] = True
        return {
            "background_path": f"{image_path}.bg",
            "foreground_path": f"{image_path}.fg",
            "head_path": f"{image_path}.head",
        }

    char_library.prime_motiontoon_parts = _prime
    scene = SimpleNamespace(
        scene_id="scene_simple_new",
        characters=[SimpleNamespace(id="protagonist", emotion="neutral", action="standing")],
    )

    result = director._handle_new_image(scene, 0, tmp_path)

    assert result.parts["background_path"].endswith("scene_simple_new__bg.png")
    assert result.parts.get("foreground_path", "") == ""
    assert result.parts.get("head_path", "") == ""
    assert primed.get("called") is None


def test_visual_director_simple_sprite_can_generate_library_variant_on_demand(tmp_path):
    char_library = _FakeCharLibrary()
    director = _make_director(tmp_path, char_library=char_library)
    generated = tmp_path / "generated_sprite.png"
    generated.write_bytes(b"img")

    def _generate(character_def, variant_keys=None, images_per_combo=None, **kwargs):
        char_library.available[("protagonist", "fear", "standing")] = str(generated)
        return True, [str(generated)]

    char_library.generate_character_library = _generate

    result = director._ensure_simple_sprite_library_image("protagonist", "fear", "standing")

    assert result == str(generated)


def test_visual_director_simple_sprite_uses_pack_preferred_character_when_scene_has_no_character(tmp_path):
    char_library = _FakeCharLibrary()
    director = _make_director(tmp_path, char_library=char_library)
    director._use_simple_character_sprite_mode = lambda: True
    director._get_pack_preferred_character_ids = lambda: ["protagonist"]
    director._normalize_scene_variant = lambda char_id, emotion, pose: (emotion, pose)
    director._ensure_simple_sprite_library_image = lambda char_id, emotion, pose: "sprite.png"
    director.prompt_composer = SimpleNamespace(
        compose_prompt=lambda scene: SimpleNamespace(positive="bg", negative="neg"),
        char_map={},
    )
    director.sd_client = object()
    director._call_sd_api = lambda composed, image_path: Path(image_path).write_bytes(b"img") or {"seed": 1}
    director._create_placeholder_image = lambda image_path: Path(image_path).write_bytes(b"img")
    director._compose_scene_motiontoon_assets = lambda *args, **kwargs: {
        "background_path": "bg.png",
        "foreground_path": "sprite.png",
    }

    scene = SimpleNamespace(scene_id="scene_pref", characters=[])

    result = director._handle_new_image(scene, 0, tmp_path)

    assert result.character_id == "protagonist"


def test_visual_director_get_from_library_prefers_sheet_variant_image(tmp_path):
    char_library = _FakeCharLibrary()
    sheet_image = tmp_path / "sheet_variant.png"
    sheet_image.write_bytes(b"sheet")
    char_library.available[("protagonist", "fear", "standing")] = str(sheet_image)
    char_library.sheet_parts[("protagonist", "fear", "standing")] = {
        "background_path": "sheet_bg.png",
    }
    director = _make_director(tmp_path, char_library=char_library)

    result = director._get_from_library("protagonist", "worried", "listening")

    assert result == str(sheet_image)


def test_visual_director_select_effective_action_accepts_sheet_backed_variant(tmp_path):
    char_library = _FakeCharLibrary()
    char_library.sheet_parts[("protagonist", "fear", "standing")] = {
        "background_path": "sheet_bg.png",
    }
    director = _make_director(tmp_path, char_library=char_library)
    director.character_panel_state["protagonist"] = {
        "image": GeneratedImage(path="hero_prev.png", scene_id="prev"),
        "location": "hallway",
        "emotion": "neutral",
        "pose": "standing",
        "camera_shot": "close-up",
        "outfit_hint": "school uniform",
        "key_props": ["letter"],
    }

    action = director._select_effective_action(
        "new",
        {
            "char_id": "protagonist",
            "location": "hallway",
            "emotion": "worried",
            "pose": "listening",
            "camera_shot": "close-up",
            "outfit_hint": "school uniform",
            "key_props": ["letter"],
        },
    )

    assert action == "expression"


def test_visual_director_reuse_clones_scene_file_and_preserves_parts(tmp_path):
    char_library = _FakeCharLibrary()
    director = _make_director(tmp_path, char_library=char_library)
    prev_image_path = tmp_path / "prev_scene.png"
    prev_image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0ioAAAAASUVORK5CYII="
        )
    )
    prev_parts = build_layered_cutout_assets(
        str(prev_image_path),
        overlay_kind="document",
        strength=0.82,
        rig_overrides={"face_anchor_x": 0.51, "cast_slot": "protagonist"},
    )
    director._get_motiontoon_rig_overrides = lambda char_id, emotion="", pose="": {"face_anchor_x": 0.63}
    director.character_panel_state["protagonist"] = {
        "image": GeneratedImage(
            path=str(prev_image_path),
            scene_id="prev",
            parts=prev_parts,
        ),
        "location": "hallway",
        "emotion": "neutral",
        "pose": "standing",
        "camera_shot": "close-up",
        "outfit_hint": "school uniform",
        "key_props": ["letter"],
    }
    scene = SimpleNamespace(scene_id="scene_reuse")

    result = director._handle_reuse(
        scene,
        0,
        {
            "scene_id": "scene_reuse",
            "char_id": "protagonist",
            "location": "hallway",
            "emotion": "worried",
            "pose": "listening",
        },
        tmp_path,
    )

    assert result.path.endswith("scene_reuse.png")
    assert Path(result.path).exists()
    assert result.expression == "fear"
    assert result.pose == "standing"
    assert Path(result.parts["background_path"]).exists()
    reuse_meta = load_layered_cutout_metadata(result.path)
    assert reuse_meta["rig"]["face_anchor_x"] == 0.63


def test_visual_director_reuse_simple_sprite_keeps_scene_clone_in_output_dir(tmp_path):
    char_library = _FakeCharLibrary()
    director = _make_director(tmp_path, char_library=char_library)
    director._use_simple_character_sprite_mode = lambda: True

    prev_scene_path = tmp_path / "scene_prev.png"
    prev_scene_path.write_bytes(b"scene")
    nested_motiontoon_dir = tmp_path / "_motiontoon"
    nested_motiontoon_dir.mkdir(parents=True, exist_ok=True)
    nested_bg_path = nested_motiontoon_dir / "scene_prev__bg.png"
    nested_bg_path.write_bytes(b"bg")
    nested_fg_path = nested_motiontoon_dir / "scene_prev__fg.png"
    nested_fg_path.write_bytes(b"fg")
    library_sprite_path = tmp_path / "grandma_sad_sitting.png"
    library_sprite_path.write_bytes(b"sprite")
    char_library.available[("grandma", "sad", "sitting")] = str(library_sprite_path)

    captured = {}

    def _compose(target_image_path, background_source_path="", sprite_source_path="", **kwargs):
        captured["target_image_path"] = target_image_path
        captured["background_source_path"] = background_source_path
        captured["sprite_source_path"] = sprite_source_path
        return {
            "background_path": background_source_path,
            "foreground_path": sprite_source_path,
        }

    director._compose_scene_motiontoon_assets = _compose
    director.character_panel_state["grandma"] = {
        "image": GeneratedImage(
            path=str(prev_scene_path),
            scene_id="scene_prev",
            parts={
                "background_path": str(nested_bg_path),
                "foreground_path": str(nested_fg_path),
            },
        ),
        "location": "apartment",
        "emotion": "sad",
        "pose": "sitting",
        "camera_shot": "",
        "outfit_hint": "",
        "key_props": [],
    }
    scene = SimpleNamespace(scene_id="scene_0006")

    result = director._handle_reuse(
        scene,
        6,
        {
            "scene_id": "scene_0006",
            "char_id": "grandma",
            "location": "apartment",
            "emotion": "sad",
            "pose": "sitting",
        },
        tmp_path,
    )

    expected_scene_path = tmp_path / "scene_0006.png"
    assert result.path == str(expected_scene_path)
    assert expected_scene_path.exists()
    assert captured["target_image_path"] == str(expected_scene_path)
    assert captured["background_source_path"] == str(nested_bg_path)
    assert captured["sprite_source_path"] == str(library_sprite_path)


def test_fixed_cast_mapping_assigns_story_speakers_to_pack_slots():
    director = VisualStorytellingDirector.__new__(VisualStorytellingDirector)
    director.scene_analyzer = SceneAnalyzer(gemini_client=None, character_definitions=[])
    director.gemini_client = None
    director._get_pack_motiontoon_cast_slots = lambda: {
        "protagonist": {"character_id": "young_woman", "aliases": ["주인공", "낭자"]},
        "deuteragonist": {"character_id": "young_man", "aliases": ["사내", "도령"]},
        "elder": {"character_id": "grandma", "aliases": ["어머니", "할머니"]},
        "support": {"character_id": "grandpa", "aliases": ["노인"]},
    }
    director._apply_pack_cast_aliases = VisualStorytellingDirector._apply_pack_cast_aliases.__get__(director, VisualStorytellingDirector)
    director._get_pack_slot_order = VisualStorytellingDirector._get_pack_slot_order.__get__(director, VisualStorytellingDirector)
    director._infer_pack_slot_for_speaker = VisualStorytellingDirector._infer_pack_slot_for_speaker.__get__(director, VisualStorytellingDirector)
    director._apply_fixed_cast_role_mapping = VisualStorytellingDirector._apply_fixed_cast_role_mapping.__get__(director, VisualStorytellingDirector)

    applied = director._apply_fixed_cast_role_mapping(
        [
            {"speaker": "서윤", "text": "제가 그 서찰을 봤어요."},
            {"speaker": "서윤", "text": "그날 이후로 달라졌어요."},
            {"speaker": "도진", "text": "지금이라도 늦지 않았어."},
            {"speaker": "어머니", "text": "너 혼자 감당할 일이 아니야."},
        ]
    )

    assert applied is True
    assert director.scene_analyzer.alias_to_id["서윤"] == "young_woman"
    assert director.scene_analyzer.alias_to_id["도진"] == "young_man"
    assert director.scene_analyzer.alias_to_id["어머니"] == "grandma"


def test_major_character_ids_prefer_pack_fixed_cast():
    director = VisualStorytellingDirector.__new__(VisualStorytellingDirector)
    director._get_pack_preferred_character_ids = lambda: ["young_woman", "young_man", "grandma", "grandpa"]

    major_ids = VisualStorytellingDirector._get_major_character_ids(
        director,
        [{"speaker": "서윤", "text": "..."}, {"speaker": "도진", "text": "..."}],
        limit=3,
    )

    assert major_ids == ["young_woman", "young_man", "grandma", "grandpa"]


def test_infer_pack_slot_prefers_child_tokens_over_support():
    director = VisualStorytellingDirector.__new__(VisualStorytellingDirector)
    director._get_pack_motiontoon_cast_slots = lambda: {
        "protagonist": {"character_id": "young_woman", "aliases": ["부인"]},
        "deuteragonist": {"character_id": "young_man", "aliases": ["사내"]},
        "child": {"character_id": "child", "aliases": ["사내아이", "아이", "돌이"]},
        "elder": {"character_id": "grandma", "aliases": ["어멈"]},
        "support": {"character_id": "grandpa", "aliases": ["훈장"]},
    }
    director._infer_pack_slot_for_speaker = VisualStorytellingDirector._infer_pack_slot_for_speaker.__get__(director, VisualStorytellingDirector)

    assert director._infer_pack_slot_for_speaker("사내아이") == "child"
    assert director._infer_pack_slot_for_speaker("아이") == "child"
    assert director._infer_pack_slot_for_speaker("돌이") == "child"


def test_infer_pack_slot_routes_male_elder_tokens_to_support_when_available():
    director = VisualStorytellingDirector.__new__(VisualStorytellingDirector)
    director._get_pack_motiontoon_cast_slots = lambda: {
        "protagonist": {"character_id": "young_woman", "aliases": ["부인"]},
        "elder": {"character_id": "grandma", "aliases": ["어머니", "할머니"]},
        "support": {"character_id": "grandpa", "aliases": ["아버지", "할아버지", "훈장"]},
    }
    director._infer_pack_slot_for_speaker = VisualStorytellingDirector._infer_pack_slot_for_speaker.__get__(director, VisualStorytellingDirector)

    assert director._infer_pack_slot_for_speaker("아버지") == "support"
    assert director._infer_pack_slot_for_speaker("할아버지") == "support"
