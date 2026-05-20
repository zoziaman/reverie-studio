import base64
from pathlib import Path

from modules_pro.character_library_manager import CharacterImage, CharacterLibraryEntry, CharacterLibraryManager, LibraryConfig


def _write_png(path: Path) -> str:
    path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0ioAAAAASUVORK5CYII="
        )
    )
    return str(path)


def test_build_character_sheet_preserves_metadata_after_path_canonicalization(tmp_path):
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path))
    hero_dir = tmp_path / "hero"
    hero_dir.mkdir(parents=True, exist_ok=True)

    actual_path = Path(_write_png(hero_dir / "neutral_standing_01.png"))
    stale_path = tmp_path / "stale" / "neutral_standing_01.png"
    stale_path.parent.mkdir(parents=True, exist_ok=True)
    stale_path.write_bytes(b"stale")

    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "neutral_standing": [
                CharacterImage(
                    path=str(stale_path),
                    expression="neutral",
                    pose="standing",
                    quality_score=0.91,
                    seed=321,
                )
            ]
        },
    )

    sheet = manager.build_character_sheet("hero", save=False)
    variant = sheet["variants"]["neutral_standing"]

    assert Path(variant["image_path"]) == actual_path
    assert variant["quality_score"] == 0.91
    assert variant["seed"] == 321


def test_character_sheet_audit_flags_missing_variants_and_assets(tmp_path):
    config = LibraryConfig(min_quality_score=0.8, required_variant_keys=["neutral_standing", "talking_sitting"])
    manager = CharacterLibraryManager(pack_id="test_pack", library_base_path=str(tmp_path), config=config)
    hero_dir = tmp_path / "hero"
    hero_dir.mkdir(parents=True, exist_ok=True)
    image_path = _write_png(hero_dir / "neutral_standing_01.png")

    manager.library["hero"] = CharacterLibraryEntry(
        character_id="hero",
        character_name="Hero",
        images={
            "neutral_standing": [
                CharacterImage(
                    path=image_path,
                    expression="neutral",
                    pose="standing",
                    quality_score=0.6,
                    seed=11,
                )
            ]
        },
    )

    sheet = manager.build_character_sheet("hero", save=False)
    sheet["variants"]["neutral_standing"]["face_parts"] = {
        "eyes_open_path": "",
        "eyes_closed_path": "",
        "mouth_closed_path": "",
        "mouth_open_path": "",
    }
    sheet["variants"]["neutral_standing"]["parts"] = {
        "background_path": "",
        "foreground_path": "",
        "head_path": "",
        "body_path": "",
    }

    audit = manager.audit_character_sheet("hero", sheet=sheet)

    issue_codes = {issue["code"] for issue in audit["issues"]}

    assert audit["status"] == "fail"
    assert "missing_required_variant" in issue_codes
    assert "quality_below_threshold" in issue_codes
    assert "missing_face_parts" in issue_codes
    assert "missing_layered_parts" in issue_codes
