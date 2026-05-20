from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.pack_config import ACTIVE_PACK, load_pack_by_id
from modules_pro.character_library_manager import (
    CharacterImage,
    CharacterLibraryEntry,
    CharacterLibraryManager,
)
from utils.runtime_utils import ensure_data_path, sanitize_for_path


def _dedupe(values: List[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        key = str(value or "").strip()
        if key and key not in result:
            result.append(key)
    return result


def _resolve_workspace_pack_dir(workspace_root: Path, pack_id: str) -> Path:
    direct_manifest = workspace_root / "library.json"
    if direct_manifest.exists():
        return workspace_root
    nested = workspace_root / pack_id
    if (nested / "library.json").exists():
        return nested
    raise FileNotFoundError(f"QA workspace manifest not found under: {workspace_root}")


def _resolve_candidate_path(workspace_root: Path, raw_path: str) -> Path:
    candidate = Path(str(raw_path or "").strip())
    if not str(candidate):
        raise ValueError("Variant path cannot be empty.")
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()
    workspace_candidate = (workspace_root / candidate).resolve()
    if workspace_candidate.exists():
        return workspace_candidate
    cwd_candidate = (Path.cwd() / candidate).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    raise FileNotFoundError(f"Candidate image not found: {raw_path}")


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


def _sort_variant_entry(manager: CharacterLibraryManager, character_id: str, variant_key: str) -> None:
    entry = manager.library.get(character_id)
    if not entry:
        return
    images = entry.images.get(variant_key) or []
    if not images:
        return
    entry.images[variant_key] = manager._sort_images_for_consistency(images)
    manager._save_library()


def _backup_production_state(manager: CharacterLibraryManager, character_id: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ensure_data_path(
        "backups",
        "character_promotions",
        sanitize_for_path(manager.pack_id, max_length=120),
        sanitize_for_path(character_id, max_length=120),
        timestamp,
    )
    backup_dir = Path(backup_dir)

    char_dir = manager.library_path / character_id
    if char_dir.exists():
        shutil.copytree(char_dir, backup_dir / character_id, dirs_exist_ok=True)
    if manager.manifest_path.exists():
        shutil.copy2(manager.manifest_path, backup_dir / "library.json")
    return str(backup_dir)


def _character_def_by_id(character_id: str):
    chars = getattr(getattr(ACTIVE_PACK, "visual_storytelling", None), "characters", []) or []
    for char_def in chars:
        if getattr(char_def, "id", "") == character_id:
            return char_def
    return None


def _ensure_character_entry(
    target_manager: CharacterLibraryManager,
    source_manager: CharacterLibraryManager,
    character_id: str,
) -> CharacterLibraryEntry:
    existing = target_manager.library.get(character_id)
    if existing:
        return existing

    source_entry = source_manager.library.get(character_id)
    if source_entry:
        entry = CharacterLibraryEntry(
            character_id=source_entry.character_id,
            character_name=source_entry.character_name,
            base_prompt=source_entry.base_prompt,
            negative_prompt=source_entry.negative_prompt,
            role_aliases=list(source_entry.role_aliases or []),
            total_images=source_entry.total_images,
            last_generated=source_entry.last_generated,
            generation_seed=source_entry.generation_seed,
        )
    else:
        char_def = _character_def_by_id(character_id)
        negative_parts = [
            str(getattr(char_def, "gender_negative", "") or "").strip(),
            str(getattr(char_def, "age_negative", "") or "").strip(),
        ]
        entry = CharacterLibraryEntry(
            character_id=character_id,
            character_name=str(getattr(char_def, "name", character_id) or character_id),
            base_prompt=str(getattr(char_def, "base_prompt", "") or ""),
            negative_prompt=", ".join(part for part in negative_parts if part),
        )

    target_manager.library[character_id] = entry
    target_manager._save_library()
    return entry


def _normalize_path(path: str) -> str:
    try:
        return str(Path(path).resolve()).lower()
    except Exception:
        return str(path or "").strip().lower()


def _find_source_image(
    manager: CharacterLibraryManager,
    character_id: str,
    variant_key: str,
    source_path: Path,
) -> Optional[CharacterImage]:
    entry = manager.library.get(character_id)
    if not entry:
        return None

    exact_target = _normalize_path(str(source_path))
    basename = source_path.name.lower()
    pools: List[CharacterImage] = []
    pools.extend(entry.images.get(variant_key, []) or [])
    for key, images in entry.images.items():
        if key == variant_key:
            continue
        pools.extend(images or [])

    fallback: Optional[CharacterImage] = None
    for image in pools:
        resolved = manager._canonicalize_character_image_path(character_id, str(getattr(image, "path", "") or ""))
        if not resolved:
            continue
        resolved_norm = _normalize_path(resolved)
        if resolved_norm == exact_target:
            return image
        if not fallback and Path(resolved).name.lower() == basename:
            fallback = image
    return fallback


def _build_promoted_image(
    source_image: Optional[CharacterImage],
    dest_path: Path,
    variant_key: str,
) -> CharacterImage:
    expression, pose = variant_key.split("_", 1) if "_" in variant_key else (variant_key, "standing")
    stat = dest_path.stat()
    created_at = (
        str(getattr(source_image, "created_at", "") or "").strip()
        if source_image
        else ""
    ) or datetime.now().isoformat()
    return CharacterImage(
        path=str(dest_path),
        expression=expression,
        pose=pose,
        seed=int(getattr(source_image, "seed", -1) or -1) if source_image else -1,
        prompt=str(getattr(source_image, "prompt", "") or "") if source_image else "",
        negative_prompt=str(getattr(source_image, "negative_prompt", "") or "") if source_image else "",
        created_at=created_at,
        quality_score=float(getattr(source_image, "quality_score", 0.0) or 0.0) if source_image else 0.0,
        face_detected=bool(getattr(source_image, "face_detected", True)) if source_image else True,
        blur_score=float(getattr(source_image, "blur_score", 0.0) or 0.0) if source_image else 0.0,
        file_size_kb=max(1, int(round(stat.st_size / 1024))),
    )


def _parse_variant_assignment(value: str) -> Tuple[str, str]:
    raw = str(value or "").strip()
    if "=" not in raw:
        raise ValueError(f"Variant mapping must use variant_key=path format: {value}")
    variant_key, path_value = raw.split("=", 1)
    variant_key = variant_key.strip()
    path_value = path_value.strip()
    if not variant_key or not path_value:
        raise ValueError(f"Variant mapping must use variant_key=path format: {value}")
    return variant_key, path_value


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote selected QA character variants into the production character library.")
    parser.add_argument("--pack-id", required=True, help="Pack id, e.g. senior_scam_alert")
    parser.add_argument("--character-id", required=True, help="Character id, e.g. grandma")
    parser.add_argument(
        "--workspace-root",
        required=True,
        help="QA workspace root returned by generate_character_qa_candidates.py",
    )
    parser.add_argument(
        "--variant",
        action="append",
        required=True,
        help="Variant mapping in variant_key=path form. May be repeated.",
    )
    args = parser.parse_args()

    variant_map: Dict[str, str] = {}
    for raw_value in args.variant:
        variant_key, path_value = _parse_variant_assignment(raw_value)
        variant_map[variant_key] = path_value
    variant_keys = _dedupe(list(variant_map.keys()))
    if not variant_keys:
        raise ValueError("At least one variant mapping is required.")

    load_pack_by_id(args.pack_id)

    workspace_root = Path(args.workspace_root).resolve()
    workspace_pack_dir = _resolve_workspace_pack_dir(workspace_root, args.pack_id)
    source_manager = CharacterLibraryManager(
        pack_id=args.pack_id,
        library_base_path=str(workspace_pack_dir),
    )
    target_manager = CharacterLibraryManager(pack_id=args.pack_id)

    backup_dir = _backup_production_state(target_manager, args.character_id)
    target_entry = _ensure_character_entry(target_manager, source_manager, args.character_id)
    removed = _purge_variants(target_manager, args.character_id, variant_keys)

    char_dir = target_manager.library_path / args.character_id
    char_dir.mkdir(parents=True, exist_ok=True)

    promoted: Dict[str, Dict[str, object]] = {}
    for variant_key in variant_keys:
        source_path = _resolve_candidate_path(workspace_root, variant_map[variant_key])
        if source_path.suffix.lower() != ".png":
            raise ValueError(f"Promoted asset must be a PNG: {source_path}")

        dest_path = char_dir / f"{variant_key}_01.png"
        shutil.copy2(source_path, dest_path)

        source_image = _find_source_image(source_manager, args.character_id, variant_key, source_path)
        promoted_image = _build_promoted_image(source_image, dest_path, variant_key)
        target_entry.images[variant_key] = [promoted_image]
        parts = target_manager.prime_motiontoon_parts(str(dest_path))
        promoted[variant_key] = {
            "source_path": str(source_path),
            "target_path": str(dest_path),
            "metadata_found": source_image is not None,
            "quality_score": float(getattr(promoted_image, "quality_score", 0.0) or 0.0),
            "seed": int(getattr(promoted_image, "seed", -1) or -1),
            "parts_generated": sorted(list(parts.keys())) if isinstance(parts, dict) else [],
        }

    target_entry.total_images = sum(len(images) for images in target_entry.images.values())
    target_entry.last_generated = datetime.now().isoformat()
    target_manager._save_library()

    for variant_key in variant_keys:
        _sort_variant_entry(target_manager, args.character_id, variant_key)

    sheet = target_manager.build_character_sheet(args.character_id, save=True)
    audit = target_manager.audit_character_sheet(args.character_id, sheet=sheet)

    summary_dir = ensure_data_path(
        "outputs",
        "reports",
        "character_promotions",
        sanitize_for_path(args.pack_id, max_length=120),
        sanitize_for_path(args.character_id, max_length=120),
    )
    summary_dir = Path(summary_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = {
        "pack_id": args.pack_id,
        "character_id": args.character_id,
        "workspace_root": str(workspace_root),
        "workspace_pack_dir": str(workspace_pack_dir),
        "backup_dir": backup_dir,
        "removed_artifacts": removed,
        "promoted_variants": promoted,
        "sheet_path": str(char_dir / "sheet_manifest.json"),
        "audit": audit,
    }

    timestamp_path = summary_dir / f"{timestamp}.json"
    latest_path = summary_dir / "latest.json"
    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    timestamp_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
