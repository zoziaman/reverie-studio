from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.pack_config import ACTIVE_PACK, load_pack_by_id
from modules_pro.character_library_manager import CharacterLibraryManager
from modules_pro.visual_director import visual_director
from pipeline.sd_client import create_sd_client
from utils.runtime_utils import ensure_data_path, sanitize_for_path


DEFAULT_VARIANTS = [
    "neutral_standing",
    "blink_standing",
    "talking_standing",
    "happy_standing",
]

DEFAULT_ANCHOR_PROMPT_SUFFIX = (
    "same identifiable character, identical face shape, identical eye shape, "
    "identical hairstyle, identical outfit silhouette, identical outfit color blocking, "
    "identical body proportions, adult realistic proportions, same character sheet anchor, no chibi simplification, "
    "no style drift, no extra person"
)
DEFAULT_ANCHOR_NEGATIVE_SUFFIX = (
    "different person, different hairstyle, different outfit, different body proportions, "
    "chibi face, doll face, child proportions, super deformed, oversized head, style drift"
)


def _default_anchor_denoising(variant_key: str, explicit: Optional[float]) -> float:
    if explicit is not None:
        return float(explicit)
    expression = variant_key.split("_", 1)[0].strip().lower()
    return {
        "neutral": 0.34,
        "blink": 0.32,
        "talking": 0.36,
        "happy": 0.38,
        "sad": 0.38,
        "fear": 0.36,
        "anger": 0.36,
    }.get(expression, 0.34)


def _build_anchor_overrides(
    variant_keys: List[str],
    anchor_image: Optional[str],
    anchor_variants: List[str],
    anchor_denoising: Optional[float],
    anchor_prompt_suffix: str,
    anchor_negative_suffix: str,
    consistency_image: Optional[str] = None,
    consistency_variants: Optional[List[str]] = None,
    consistency_mode: str = "",
    consistency_weight: Optional[float] = None,
    pose_image: Optional[str] = None,
    pose_variants: Optional[List[str]] = None,
    pose_module: str = "",
    pose_weight: Optional[float] = None,
    pose_control_mode: str = "",
    pose_start_step: Optional[float] = None,
    pose_end_step: Optional[float] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    steps: Optional[int] = None,
    cfg_scale: Optional[float] = None,
    sampler_name: str = "",
    scheduler: str = "",
    ) -> Dict[str, Dict[str, object]]:
    anchor_path = str(anchor_image or "").strip()
    consistency_path = str(consistency_image or "").strip()
    pose_path = str(pose_image or "").strip()
    prompt_suffix = str(anchor_prompt_suffix or "").strip()
    negative_suffix = str(anchor_negative_suffix or "").strip()
    consistency_mode = str(consistency_mode or "").strip()
    pose_module = str(pose_module or "").strip()
    pose_control_mode = str(pose_control_mode or "").strip()
    sampler_name = str(sampler_name or "").strip()
    scheduler = str(scheduler or "").strip()
    if (
        not anchor_path
        and not consistency_path
        and not pose_path
        and not prompt_suffix
        and not negative_suffix
        and width is None
        and height is None
        and steps is None
        and cfg_scale is None
        and not sampler_name
        and not scheduler
    ):
        return {}
    target_keys = set(anchor_variants or variant_keys)
    consistency_target_keys = set(consistency_variants or variant_keys)
    pose_target_keys = set(pose_variants or variant_keys)
    if anchor_path and not prompt_suffix:
        prompt_suffix = DEFAULT_ANCHOR_PROMPT_SUFFIX
    if anchor_path and not negative_suffix:
        negative_suffix = DEFAULT_ANCHOR_NEGATIVE_SUFFIX
    overrides: Dict[str, Dict[str, object]] = {}
    for variant_key in variant_keys:
        if variant_key not in target_keys:
            continue
        payload: Dict[str, object] = {}
        if anchor_path:
            payload["init_image_path"] = anchor_path
            payload["denoising_strength"] = _default_anchor_denoising(variant_key, anchor_denoising)
        if consistency_path and variant_key in consistency_target_keys:
            payload["consistency_image_path"] = consistency_path
            if consistency_mode:
                payload["consistency_mode"] = consistency_mode
            if consistency_weight is not None:
                payload["consistency_weight"] = float(consistency_weight)
        if pose_path and variant_key in pose_target_keys:
            payload["pose_image_path"] = pose_path
            if pose_module:
                payload["pose_module"] = pose_module
            if pose_weight is not None:
                payload["pose_weight"] = float(pose_weight)
            if pose_control_mode:
                payload["pose_control_mode"] = pose_control_mode
            if pose_start_step is not None:
                payload["pose_start_step"] = float(pose_start_step)
            if pose_end_step is not None:
                payload["pose_end_step"] = float(pose_end_step)
        if prompt_suffix:
            payload["prompt_suffix"] = prompt_suffix
        if negative_suffix:
            payload["negative_prompt_suffix"] = negative_suffix
        if width is not None:
            payload["width"] = int(width)
        if height is not None:
            payload["height"] = int(height)
        if steps is not None:
            payload["steps"] = int(steps)
        if cfg_scale is not None:
            payload["cfg_scale"] = float(cfg_scale)
        if sampler_name:
            payload["sampler_name"] = sampler_name
        if scheduler:
            payload["scheduler"] = scheduler
        if payload:
            overrides[variant_key] = payload
    return overrides


def _dedupe(values: List[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        key = str(value or "").strip()
        if key and key not in result:
            result.append(key)
    return result


def _remove_variant_artifacts(manager: CharacterLibraryManager, character_id: str, variant_key: str) -> List[str]:
    removed: List[str] = []
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


def _purge_variants(manager: CharacterLibraryManager, character_id: str, variant_keys: List[str]) -> Dict[str, List[str]]:
    removed: Dict[str, List[str]] = {}
    entry = manager.library.get(character_id)
    if not entry:
        return removed

    for variant_key in variant_keys:
        for image in entry.images.pop(variant_key, []) or []:
            image_path = Path(
                manager._canonicalize_character_image_path(
                    character_id,
                    str(getattr(image, "path", "") or ""),
                )
            )
            if image_path.exists():
                image_path.unlink(missing_ok=True)
                removed.setdefault(variant_key, []).append(str(image_path))
        removed.setdefault(variant_key, []).extend(_remove_variant_artifacts(manager, character_id, variant_key))

    entry.total_images = sum(len(images) for images in entry.images.values())
    manager._save_library()
    manager.build_character_sheet(character_id, save=True)
    return removed


def _rebase_entry_paths(manager: CharacterLibraryManager, character_id: str) -> None:
    entry = manager.library.get(character_id)
    if not entry:
        return
    changed = False
    for images in entry.images.values():
        for image in images:
            raw_path = str(getattr(image, "path", "") or "")
            canonical = manager._canonicalize_character_image_path(character_id, raw_path)
            if canonical and canonical != raw_path:
                image.path = canonical
                changed = True
    if changed:
        manager._save_library()


def _clone_library_workspace(source_root: Path, character_id: str, workspace_pack_dir: Path) -> None:
    workspace_pack_dir.mkdir(parents=True, exist_ok=True)
    manifest_src = source_root / "library.json"
    if manifest_src.exists():
        shutil.copy2(manifest_src, workspace_pack_dir / "library.json")
    char_src = source_root / character_id
    if char_src.exists():
        shutil.copytree(char_src, workspace_pack_dir / character_id, dirs_exist_ok=True)


def _sort_variant_entry(manager: CharacterLibraryManager, character_id: str, variant_key: str) -> None:
    entry = manager.library.get(character_id)
    if not entry:
        return
    images = entry.images.get(variant_key) or []
    if not images:
        return
    entry.images[variant_key] = manager._sort_images_for_consistency(images)
    manager._save_library()
    manager.build_character_sheet(character_id, save=True)


def _create_contact_sheet(
    manager: CharacterLibraryManager,
    character_id: str,
    variant_keys: List[str],
    candidate_dir: Path,
) -> Dict[str, str]:
    font = ImageFont.load_default()
    char_dir = manager.library_path / character_id
    boxes = manager._get_character_face_part_boxes(character_id)

    variant_to_files: Dict[str, List[Path]] = {}
    max_cols = 1
    for variant_key in variant_keys:
        files = sorted(char_dir.glob(f"{variant_key}_*.png"))
        variant_to_files[variant_key] = files
        if len(files) > max_cols:
            max_cols = len(files)

    full_cell_w = 280
    full_cell_h = 400
    face_cell_w = 240
    face_cell_h = 280
    row_label_w = 180

    full_sheet = Image.new(
        "RGB",
        (row_label_w + max_cols * full_cell_w, max(1, len(variant_keys)) * full_cell_h),
        (24, 24, 28),
    )
    face_sheet = Image.new(
        "RGB",
        (row_label_w + max_cols * face_cell_w, max(1, len(variant_keys)) * face_cell_h),
        (26, 26, 30),
    )

    for row, variant_key in enumerate(variant_keys):
        files = variant_to_files.get(variant_key, [])
        y_full = row * full_cell_h
        y_face = row * face_cell_h

        label_tile_full = Image.new("RGB", (row_label_w, full_cell_h), (36, 36, 42))
        label_tile_face = Image.new("RGB", (row_label_w, face_cell_h), (36, 36, 42))
        ImageDraw.Draw(label_tile_full).text((16, 20), variant_key, fill=(240, 240, 240), font=font)
        ImageDraw.Draw(label_tile_face).text((16, 20), variant_key, fill=(240, 240, 240), font=font)
        full_sheet.paste(label_tile_full, (0, y_full))
        face_sheet.paste(label_tile_face, (0, y_face))

        for col, path in enumerate(files):
            x_full = row_label_w + col * full_cell_w
            x_face = row_label_w + col * face_cell_w

            tile_full = Image.new("RGB", (full_cell_w - 8, full_cell_h - 8), (250, 250, 250))
            tile_face = Image.new("RGB", (face_cell_w - 8, face_cell_h - 8), (250, 250, 250))
            img = Image.open(path).convert("RGBA")

            fit_full = ImageOps.contain(img, (tile_full.width - 24, tile_full.height - 64))
            full_x = (tile_full.width - fit_full.width) // 2
            full_y = 36 + (tile_full.height - 50 - fit_full.height) // 2
            tile_full.paste(fit_full, (full_x, full_y), fit_full)
            ImageDraw.Draw(tile_full).text((14, 12), path.stem, fill=(20, 20, 20), font=font)

            variant_meta = {"face_part_boxes": boxes, "rig": {}}
            crop_box = manager._get_variant_face_crop_box(str(path), variant_meta, part_kind="face")
            crop = img.crop(crop_box) if crop_box else img
            fit_face = ImageOps.contain(crop, (tile_face.width - 24, tile_face.height - 48))
            face_x = (tile_face.width - fit_face.width) // 2
            face_y = 30 + (tile_face.height - 36 - fit_face.height) // 2
            tile_face.paste(fit_face, (face_x, face_y), fit_face)
            ImageDraw.Draw(tile_face).text((14, 10), path.stem, fill=(20, 20, 20), font=font)

            full_sheet.paste(tile_full, (x_full + 4, y_full + 4))
            face_sheet.paste(tile_face, (x_face + 4, y_face + 4))

    full_path = candidate_dir / f"{character_id}_candidate_contact.png"
    face_path = candidate_dir / f"{character_id}_candidate_face_contact.png"
    full_sheet.save(full_path)
    face_sheet.save(face_path)
    return {
        "variant_contact": str(full_path),
        "face_contact": str(face_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate QA-only character candidate sheets in a separate workspace.")
    parser.add_argument("--pack-id", required=True, help="Pack id, e.g. senior_life_saguk")
    parser.add_argument("--character-id", required=True, help="Character id, e.g. young_woman")
    parser.add_argument(
        "--variants",
        default=",".join(DEFAULT_VARIANTS),
        help="Comma-separated variant keys to regenerate in QA workspace.",
    )
    parser.add_argument("--count", type=int, default=4, help="Images per variant.")
    parser.add_argument("--sd-url", default="http://127.0.0.1:7860", help="Stable Diffusion API URL.")
    parser.add_argument("--anchor-image", default="", help="Optional absolute or relative image path to use as img2img anchor.")
    parser.add_argument(
        "--anchor-variants",
        default="",
        help="Comma-separated variant keys to force through the anchor image. Defaults to all requested variants when --anchor-image is set.",
    )
    parser.add_argument(
        "--anchor-denoising",
        type=float,
        default=None,
        help="Optional denoising strength override for anchor img2img. If omitted, variant-specific defaults are used.",
    )
    parser.add_argument(
        "--anchor-prompt-suffix",
        default=DEFAULT_ANCHOR_PROMPT_SUFFIX,
        help="Extra positive suffix appended when anchor img2img is active.",
    )
    parser.add_argument(
        "--anchor-negative-suffix",
        default="",
        help="Extra negative suffix appended when anchor img2img is active.",
    )
    parser.add_argument(
        "--prompt-suffix",
        default="",
        help="Extra positive suffix appended for all targeted variants, even without img2img anchor.",
    )
    parser.add_argument(
        "--negative-suffix",
        default="",
        help="Extra negative suffix appended for all targeted variants, even without img2img anchor.",
    )
    parser.add_argument(
        "--disable-reference-img2img",
        action="store_true",
        help="Disable automatic reference-image img2img fallback from existing library variants inside the QA workspace.",
    )
    parser.add_argument(
        "--consistency-image",
        default="",
        help="Optional absolute or relative reference image path to apply through IP-Adapter/ControlNet consistency.",
    )
    parser.add_argument(
        "--consistency-variants",
        default="",
        help="Comma-separated variant keys to receive the consistency reference. Defaults to all requested variants when --consistency-image is set.",
    )
    parser.add_argument(
        "--consistency-mode",
        default="face_plus",
        help="IP-Adapter consistency mode: face, full, or face_plus.",
    )
    parser.add_argument(
        "--consistency-weight",
        type=float,
        default=0.72,
        help="Optional IP-Adapter consistency weight override.",
    )
    parser.add_argument(
        "--pose-image",
        default="",
        help="Optional absolute or relative image path to apply as an additional ControlNet pose/reference guide.",
    )
    parser.add_argument(
        "--pose-variants",
        default="",
        help="Comma-separated variant keys to receive the pose guide. Defaults to all requested variants when --pose-image is set.",
    )
    parser.add_argument(
        "--pose-module",
        default="reference_only",
        help="Additional ControlNet module for pose guidance, e.g. reference_only or reference_adain+attn.",
    )
    parser.add_argument(
        "--pose-weight",
        type=float,
        default=0.6,
        help="Optional additional ControlNet pose-guide weight override.",
    )
    parser.add_argument(
        "--pose-control-mode",
        default="My prompt is more important",
        help="Additional ControlNet pose-guide control mode.",
    )
    parser.add_argument(
        "--pose-start-step",
        type=float,
        default=0.0,
        help="Additional ControlNet pose-guide guidance start step.",
    )
    parser.add_argument(
        "--pose-end-step",
        type=float,
        default=0.9,
        help="Additional ControlNet pose-guide guidance end step.",
    )
    parser.add_argument(
        "--checkpoint-override",
        default="",
        help="Optional SD checkpoint override for this QA batch.",
    )
    parser.add_argument("--width", type=int, default=None, help="Optional generation width override.")
    parser.add_argument("--height", type=int, default=None, help="Optional generation height override.")
    parser.add_argument("--steps", type=int, default=None, help="Optional generation steps override.")
    parser.add_argument("--cfg-scale", type=float, default=None, help="Optional CFG scale override.")
    parser.add_argument("--sampler-name", default="", help="Optional sampler override.")
    parser.add_argument("--scheduler", default="", help="Optional scheduler override.")
    parser.add_argument("--max-retries", type=int, default=None, help="Optional override for QA generation retries per image.")
    parser.add_argument("--min-quality-score", type=float, default=None, help="Optional override for QA acceptance threshold.")
    args = parser.parse_args()

    variant_keys = _dedupe([value.strip() for value in str(args.variants or "").split(",")])
    if not variant_keys:
        raise ValueError("At least one variant key is required.")
    anchor_variants = _dedupe([value.strip() for value in str(args.anchor_variants or "").split(",")])
    consistency_variants = _dedupe([value.strip() for value in str(args.consistency_variants or "").split(",")])
    pose_variants = _dedupe([value.strip() for value in str(args.pose_variants or "").split(",")])

    load_pack_by_id(args.pack_id)

    sd_client = create_sd_client(args.sd_url)
    components = visual_director.init_v59_pipeline(
        pack_id=args.pack_id,
        genre=str(getattr(ACTIVE_PACK, "genre", "senior") or "senior"),
        sd_api=sd_client,
        gemini_client=None,
    )
    base_manager = components["char_library"]
    prompt_composer = components["prompt_composer"]

    source_root = Path(base_manager.library_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workspace_root = ensure_data_path(
        "outputs",
        "candidates",
        "character_qa",
        sanitize_for_path(args.pack_id, max_length=120),
        sanitize_for_path(args.character_id, max_length=120),
        timestamp,
    )
    workspace_pack_dir = workspace_root / args.pack_id
    _clone_library_workspace(source_root, args.character_id, workspace_pack_dir)

    manager = CharacterLibraryManager(
        pack_id=args.pack_id,
        library_base_path=str(workspace_pack_dir),
        sd_api_url=args.sd_url,
        prompt_composer=prompt_composer,
        config=base_manager.config,
    )
    checkpoint_override = str(args.checkpoint_override or "").strip()
    if checkpoint_override:
        manager.config.checkpoint_override = checkpoint_override
    if args.max_retries is not None:
        manager.config.max_retries = max(1, int(args.max_retries))
    if args.min_quality_score is not None:
        manager.config.min_quality_score = max(0.0, float(args.min_quality_score))
    if args.disable_reference_img2img:
        manager._get_reference_variant_image = lambda entry, pose: None
    _rebase_entry_paths(manager, args.character_id)
    effective_prompt_suffix = str(args.prompt_suffix or "").strip()
    if not effective_prompt_suffix:
        effective_prompt_suffix = str(args.anchor_prompt_suffix or "").strip()
    effective_negative_suffix = str(args.negative_suffix or "").strip()
    if not effective_negative_suffix:
        effective_negative_suffix = str(args.anchor_negative_suffix or "").strip()
    anchor_overrides = _build_anchor_overrides(
        variant_keys=variant_keys,
        anchor_image=args.anchor_image,
        anchor_variants=anchor_variants,
        anchor_denoising=args.anchor_denoising,
        anchor_prompt_suffix=effective_prompt_suffix,
        anchor_negative_suffix=effective_negative_suffix,
        consistency_image=args.consistency_image,
        consistency_variants=consistency_variants,
        consistency_mode=args.consistency_mode,
        consistency_weight=args.consistency_weight,
        pose_image=args.pose_image,
        pose_variants=pose_variants,
        pose_module=args.pose_module,
        pose_weight=args.pose_weight,
        pose_control_mode=args.pose_control_mode,
        pose_start_step=args.pose_start_step,
        pose_end_step=args.pose_end_step,
        width=args.width,
        height=args.height,
        steps=args.steps,
        cfg_scale=args.cfg_scale,
        sampler_name=args.sampler_name,
        scheduler=args.scheduler,
    )

    char_defs = {
        getattr(char_def, "id", ""): char_def
        for char_def in getattr(getattr(ACTIVE_PACK, "visual_storytelling", None), "characters", []) or []
    }
    if args.character_id not in char_defs:
        raise KeyError(f"Character definition not found: {args.character_id}")

    removed = _purge_variants(manager, args.character_id, variant_keys)

    phase_one = [key for key in variant_keys if key == "neutral_standing"]
    phase_two = [key for key in variant_keys if key not in phase_one]
    generated_paths: List[str] = []

    if phase_one:
        success, paths = manager.generate_character_library(
            character_def=char_defs[args.character_id],
            variant_keys=phase_one,
            images_per_combo=args.count,
            generation_overrides_by_variant={key: anchor_overrides[key] for key in phase_one if key in anchor_overrides},
        )
        if not success:
            raise RuntimeError(f"Failed to generate phase-one variants: {phase_one}")
        generated_paths.extend(paths)
        _sort_variant_entry(manager, args.character_id, "neutral_standing")

    if phase_two:
        success, paths = manager.generate_character_library(
            character_def=char_defs[args.character_id],
            variant_keys=phase_two,
            images_per_combo=args.count,
            generation_overrides_by_variant={key: anchor_overrides[key] for key in phase_two if key in anchor_overrides},
        )
        if not success:
            raise RuntimeError(f"Failed to generate phase-two variants: {phase_two}")
        generated_paths.extend(paths)

    for key in variant_keys:
        _sort_variant_entry(manager, args.character_id, key)

    sheet = manager.build_character_sheet(args.character_id, save=True)
    contacts = _create_contact_sheet(manager, args.character_id, variant_keys, workspace_root)

    summary = {
        "workspace_root": str(workspace_root),
        "workspace_pack_dir": str(workspace_pack_dir),
        "character_dir": str(workspace_pack_dir / args.character_id),
        "sheet_path": str(workspace_pack_dir / args.character_id / "sheet_manifest.json"),
        "variant_keys": variant_keys,
        "images_per_variant": args.count,
        "anchor_image": str(args.anchor_image or ""),
        "anchor_variants": anchor_variants or variant_keys if str(args.anchor_image or "").strip() else [],
        "consistency_image": str(args.consistency_image or ""),
        "consistency_variants": consistency_variants or variant_keys if str(args.consistency_image or "").strip() else [],
        "consistency_mode": str(args.consistency_mode or ""),
        "consistency_weight": float(args.consistency_weight) if args.consistency_weight is not None else None,
        "pose_image": str(args.pose_image or ""),
        "pose_variants": pose_variants or variant_keys if str(args.pose_image or "").strip() else [],
        "pose_module": str(args.pose_module or ""),
        "pose_weight": float(args.pose_weight) if args.pose_weight is not None else None,
        "pose_control_mode": str(args.pose_control_mode or ""),
        "pose_start_step": float(args.pose_start_step) if args.pose_start_step is not None else None,
        "pose_end_step": float(args.pose_end_step) if args.pose_end_step is not None else None,
        "prompt_suffix": effective_prompt_suffix,
        "negative_suffix": effective_negative_suffix,
        "disable_reference_img2img": bool(args.disable_reference_img2img),
        "checkpoint_override": checkpoint_override,
        "max_retries": int(getattr(manager.config, "max_retries", 0) or 0),
        "min_quality_score": float(getattr(manager.config, "min_quality_score", 0.0) or 0.0),
        "anchor_overrides": anchor_overrides,
        "generated_count": len(generated_paths),
        "generated_paths": generated_paths,
        "removed_artifacts": removed,
        "contact_sheets": contacts,
        "best_variants": {
            key: (sheet.get("variants", {}).get(key, {}) or {}).get("image_path", "")
            for key in variant_keys
        },
    }

    summary_path = workspace_root / "qa_generation_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
