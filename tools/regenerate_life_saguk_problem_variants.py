from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.pack_config import ACTIVE_PACK, load_pack_by_id
from modules_pro.character_library_manager import CharacterLibraryManager
from modules_pro.visual_director import visual_director
from pipeline.sd_client import create_sd_client
from utils.runtime_utils import ensure_report_output_dir


PACK_ID = "senior_life_saguk"
SD_API_URL = "http://127.0.0.1:7860"

VARIANT_PLAN = {
    "young_woman": [
        "neutral_standing",
        "blink_standing",
        "talking_standing",
        "happy_standing",
    ],
    "young_man": [
        "neutral_standing",
        "blink_standing",
        "talking_standing",
        "neutral_walking",
    ],
    "grandma": [
        "neutral_sitting",
        "talking_sitting",
        "sad_sitting",
    ],
}


def _remove_variant_artifacts(manager: CharacterLibraryManager, character_id: str, variant_key: str) -> list[str]:
    removed: list[str] = []
    char_dir = manager.library_path / character_id
    if not char_dir.exists():
        return removed

    for path in char_dir.glob(f"{variant_key}_*.png"):
        if path.is_file():
            path.unlink(missing_ok=True)
            removed.append(str(path))

    layered_dir = char_dir / "_layered"
    if layered_dir.exists():
        for path in layered_dir.glob(f"{variant_key}_*"):
            if path.is_file():
                path.unlink(missing_ok=True)
                removed.append(str(path))

    face_parts_dir = char_dir / "_face_parts" / variant_key
    if face_parts_dir.exists():
        shutil.rmtree(face_parts_dir, ignore_errors=True)
        removed.append(str(face_parts_dir))

    portraits_dir = char_dir / "_face_portraits"
    if portraits_dir.exists():
        for path in portraits_dir.glob(f"{variant_key}*"):
            if path.is_file():
                path.unlink(missing_ok=True)
                removed.append(str(path))

    return removed


def _purge_variant_entries(manager: CharacterLibraryManager, character_id: str, variant_keys: list[str]) -> dict[str, list[str]]:
    entry = manager.library.get(character_id)
    removed: dict[str, list[str]] = {}
    if not entry:
        return removed

    for variant_key in variant_keys:
        for image in entry.images.pop(variant_key, []) or []:
            image_path = Path(str(getattr(image, "path", "") or ""))
            if image_path.exists():
                image_path.unlink(missing_ok=True)
                removed.setdefault(variant_key, []).append(str(image_path))
        removed.setdefault(variant_key, []).extend(_remove_variant_artifacts(manager, character_id, variant_key))

    entry.total_images = sum(len(images) for images in entry.images.values())
    manager._save_library()
    manager.build_character_sheet(character_id, save=True)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate known-bad senior_life_saguk character variants.")
    parser.add_argument(
        "--skip-clean",
        action="store_true",
        help="Keep existing variant entries and only try to generate new ones.",
    )
    args = parser.parse_args()

    load_pack_by_id(PACK_ID)

    sd_client = create_sd_client(SD_API_URL)
    components = visual_director.init_v59_pipeline(
        pack_id=PACK_ID,
        genre="senior",
        sd_api=sd_client,
        gemini_client=None,
    )
    base_manager = components["char_library"]
    prompt_composer = components["prompt_composer"]

    manager = CharacterLibraryManager(
        pack_id=PACK_ID,
        library_base_path=str(base_manager.library_path),
        sd_api_url=SD_API_URL,
        prompt_composer=prompt_composer,
        config=base_manager.config,
    )

    char_defs = {
        getattr(char_def, "id", ""): char_def
        for char_def in getattr(getattr(ACTIVE_PACK, "visual_storytelling", None), "characters", []) or []
    }

    summary: dict[str, dict[str, object]] = {}
    for char_id, variant_keys in VARIANT_PLAN.items():
        if char_id not in char_defs:
            summary[char_id] = {"success": False, "reason": "character_definition_missing"}
            continue

        removed = {}
        if not args.skip_clean:
            removed = _purge_variant_entries(manager, char_id, list(variant_keys))

        success, paths = manager.generate_character_library(
            character_def=char_defs[char_id],
            variant_keys=list(variant_keys),
            images_per_combo=1,
        )
        sheet = manager.build_character_sheet(char_id, save=True)
        coverage = manager.get_character_sheet_coverage(
            char_id,
            required_variant_keys=list(variant_keys),
        )
        summary[char_id] = {
            "success": bool(success),
            "variant_keys": list(variant_keys),
            "generated_count": len(paths),
            "generated_paths": list(paths),
            "removed_artifacts": removed,
            "coverage": coverage,
            "sheet_variant_count": int(sheet.get("variant_count", 0) or 0),
            "sheet_path": str(manager.library_path / char_id / "sheet_manifest.json"),
        }

    out_path = ensure_report_output_dir("cast_regen") / "life_saguk_problem_variant_regeneration_summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
