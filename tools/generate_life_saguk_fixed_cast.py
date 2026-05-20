from __future__ import annotations

import argparse
import json
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


def _dedupe_variant_keys(values: list[str]) -> list[str]:
    keys: list[str] = []
    for value in values:
        key = str(value or "").strip()
        if not key or key in keys:
            continue
        keys.append(key)
    return keys


def _variant_keys_for_plan(char_lib_cfg) -> dict[str, list[str]]:
    required_by_slot = dict(getattr(char_lib_cfg, "required_variant_keys_by_slot", {}) or {})
    return {
        "grandma": _dedupe_variant_keys(
            [
                "neutral_standing",
                "blink_standing",
                "neutral_sitting",
                "talking_standing",
                "talking_sitting",
                "sad_sitting",
            ]
            + list(required_by_slot.get("elder", []) or [])
        ),
        "grandpa": _dedupe_variant_keys(
            [
                "neutral_standing",
                "blink_standing",
                "talking_standing",
                "fear_standing",
            ]
            + list(required_by_slot.get("support", []) or [])
        ),
        "child": _dedupe_variant_keys(
            [
                "neutral_standing",
                "blink_standing",
                "talking_standing",
                "neutral_sitting",
                "fear_standing",
                "sad_sitting",
            ]
            + list(required_by_slot.get("child", []) or [])
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate fixed senior_life_saguk cast sheets.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear the existing grandma/grandpa/child library entries before regeneration.",
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
    variant_plan = _variant_keys_for_plan(manager.config)

    if args.reset:
        for char_id in variant_plan:
            manager.clear_character(char_id)

    summary: dict[str, dict[str, object]] = {}
    for char_id, variant_keys in variant_plan.items():
        char_def = char_defs[char_id]
        success, paths = manager.generate_character_library(
            character_def=char_def,
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
            "generated_count": len(paths),
            "generated_paths": list(paths),
            "coverage": coverage,
            "sheet_variant_count": int(sheet.get("variant_count", 0) or 0),
            "sheet_path": str(manager.library_path / char_id / "sheet_manifest.json"),
        }

    out_path = ensure_report_output_dir("cast_regen") / "life_saguk_fixed_cast_generation_summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
