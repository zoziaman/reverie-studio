from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.pack_config import ACTIVE_PACK, load_pack_by_id
from modules_pro.character_library_manager import CharacterLibraryManager
from utils.layered_cutout import build_layered_cutout_assets
from utils.sprite_artifact_cleanup import inpaint_hsv_clusters, paste_patch_from_source


BACKUP_ROOT = ROOT / "data" / "backups" / "sprite_artifact_cleanup"
DEFAULT_PRESET = "senior_scam_alert_probe_cleanup_v1"


PRESETS: Dict[str, List[Dict[str, Any]]] = {
    DEFAULT_PRESET: [
        {
            "image_path": ROOT / "assets" / "characters" / "senior_scam_alert" / "grandma" / "sad_sitting_01.png",
            "pack_id": "senior_scam_alert",
            "character_id": "grandma",
            "variant_key": "sad_sitting",
            "operations": [
                {
                    "type": "patch_fill",
                    "target_box": (164, 182, 186, 217),
                    "source_box": (136, 182, 158, 217),
                    "feather_radius": 3.0,
                    "rounded_radius": 6,
                },
                {
                    "type": "inpaint_hsv_clusters",
                    "rois": [
                        (367, 226, 375, 238),
                        (271, 409, 288, 425),
                        (210, 505, 219, 518),
                        (354, 649, 361, 656),
                        (409, 715, 415, 722),
                    ],
                    "saturation_min": 85,
                    "value_min": 45,
                    "dilate_px": 1,
                    "radius": 3.0,
                },
            ],
        },
        {
            "image_path": ROOT / "assets" / "characters" / "senior_scam_alert" / "grandma" / "talking_sitting_01.png",
            "pack_id": "senior_scam_alert",
            "character_id": "grandma",
            "variant_key": "talking_sitting",
            "operations": [
                {
                    "type": "patch_fill",
                    "target_box": (164, 182, 186, 217),
                    "source_box": (136, 182, 158, 217),
                    "feather_radius": 3.0,
                    "rounded_radius": 6,
                },
                {
                    "type": "inpaint_hsv_clusters",
                    "rois": [
                        (367, 226, 375, 238),
                        (271, 409, 288, 425),
                        (210, 505, 219, 518),
                        (354, 649, 361, 656),
                        (409, 715, 415, 722),
                    ],
                    "saturation_min": 85,
                    "value_min": 45,
                    "dilate_px": 1,
                    "radius": 3.0,
                },
            ],
        },
        {
            "image_path": ROOT / "assets" / "characters" / "senior_scam_alert" / "young_man" / "neutral_walking_01.png",
            "pack_id": "senior_scam_alert",
            "character_id": "young_man",
            "variant_key": "neutral_walking",
            "replace_from": ROOT
            / "data"
            / "outputs"
            / "candidates"
            / "character_qa"
            / "senior_scam_alert"
            / "young_man"
            / "20260319_135105_anchor2"
            / "senior_scam_alert"
            / "young_man"
            / "neutral_walking_02.png",
            "operations": [],
        },
    ]
}


def _backup_file(source_path: Path, backup_dir: Path) -> Path:
    target_path = backup_dir / source_path.relative_to(ROOT)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    return target_path


def _apply_operations(image_path: Path, config: Dict[str, Any]) -> Dict[str, Any]:
    from PIL import Image

    source_path = Path(config.get("replace_from", image_path))
    image = Image.open(source_path).convert("RGBA")
    applied_masks: list[dict[str, Any]] = []

    for operation in list(config.get("operations", []) or []):
        op_type = str(operation.get("type", "") or "")
        if op_type == "patch_fill":
            image = paste_patch_from_source(
                image,
                target_box=operation["target_box"],
                source_box=operation["source_box"],
                feather_radius=float(operation.get("feather_radius", 3.0) or 3.0),
                rounded_radius=int(operation.get("rounded_radius", 6) or 6),
            )
            applied_masks.append({"type": op_type, "target_box": list(operation["target_box"])})
            continue
        if op_type == "inpaint_hsv_clusters":
            image, mask = inpaint_hsv_clusters(
                image,
                rois=operation["rois"],
                saturation_min=int(operation.get("saturation_min", 90) or 90),
                value_min=int(operation.get("value_min", 50) or 50),
                hue_ranges=tuple(tuple(pair) for pair in operation.get("hue_ranges", ((35, 150), (150, 179)))),
                dilate_px=int(operation.get("dilate_px", 1) or 1),
                radius=float(operation.get("radius", 3.0) or 3.0),
            )
            applied_masks.append(
                {
                    "type": op_type,
                    "rois": [list(roi) for roi in operation["rois"]],
                    "mask_nonzero": int(sum(1 for value in mask.getdata() if value)),
                }
            )
            continue
        raise ValueError(f"Unsupported operation type: {op_type}")

    image.save(image_path)
    return {"image_path": str(image_path), "applied_masks": applied_masks, "source_path": str(source_path)}


def _rebuild_variant_parts(image_path: Path) -> None:
    build_layered_cutout_assets(
        str(image_path),
        overlay_kind="document",
        strength=0.82,
        force=True,
        rig_overrides=None,
    )


def _rebuild_character_sheet(pack_id: str, character_id: str) -> None:
    loaded = load_pack_by_id(pack_id)
    if not loaded:
        raise RuntimeError(f"Failed to load pack: {pack_id}")
    manager = CharacterLibraryManager(
        pack_id=ACTIVE_PACK.pack_id,
        library_base_path=str(ROOT / "assets" / "characters" / ACTIVE_PACK.pack_id),
        config=ACTIVE_PACK,
    )
    manager.build_character_sheet(character_id, save=True)


def run_preset(preset_name: str) -> dict[str, Any]:
    configs = PRESETS.get(preset_name)
    if not configs:
        raise KeyError(f"Unknown preset: {preset_name}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUP_ROOT / timestamp / preset_name
    results = []
    rebuilt: set[tuple[str, str]] = set()

    for config in configs:
        image_path = Path(config["image_path"])
        if not image_path.exists():
            raise FileNotFoundError(f"Missing image for preset: {image_path}")
        _backup_file(image_path, backup_dir)
        result = _apply_operations(image_path, config)
        _rebuild_variant_parts(image_path)
        pack_id = str(config["pack_id"])
        character_id = str(config["character_id"])
        rebuilt.add((pack_id, character_id))
        results.append(result)

    for pack_id, character_id in sorted(rebuilt):
        _rebuild_character_sheet(pack_id, character_id)

    payload = {
        "preset": preset_name,
        "generated_at": datetime.now().isoformat(),
        "backup_dir": str(backup_dir),
        "results": results,
        "rebuilt_characters": [
            {"pack_id": pack_id, "character_id": character_id}
            for pack_id, character_id in sorted(rebuilt)
        ],
    }
    summary_path = backup_dir / "retouch_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Retouch preset scam-pack sprite artifacts.")
    parser.add_argument("--preset", default=DEFAULT_PRESET, help="Preset name to apply.")
    args = parser.parse_args()

    summary = run_preset(args.preset)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
