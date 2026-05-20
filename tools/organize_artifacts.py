from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_ROOT = ROOT / "data" / "outputs"
TEMP_ROOT = ROOT / "data" / "temp_images"

STRUCTURED_OUTPUT_DIRS = {"archive", "candidates", "current", "debug", "reports"}
STRUCTURED_TEMP_DIRS = {"archive"}

CURRENT_OUTPUT_RULES = {
    "Senior_life_saguk_final_check_v2": [
        "life_saguk_final_check_v2",
        "life_saguk_still_frame",
        "life_saguk_woman_check_frame",
        "life_saguk_check_t",
        "life_saguk_frame_",
    ],
    "life_saguk_gishini_finalcheck_v8": [
        "life_saguk_gishini_finalcheck_v8",
    ],
    "Senior_scam_alert_final_check_v1": [
        "scam_alert_final_check_v1",
    ],
    "scam_alert_gishini_finalcheck_v5": [
        "scam_alert_gishini_finalcheck_v5",
    ],
}

CURATION_MARKERS = (
    "candidate",
    "compare",
    "retry",
    "model_sweep",
    "contact",
)
DEBUG_MARKERS = (
    "debug",
    "mask",
)

CHANNEL_CURRENT_PROJECTS = {
    "생활 사극 채널": "Senior_life_saguk_final_check_v2",
    "사기 경보 드라마 채널": "Senior_scam_alert_final_check_v1",
}


def _dedupe_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 1
    while True:
        candidate = parent / f"{stem}__dup{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _move_entry(src: Path, dst: Path, dry_run: bool, moves: list[dict[str, str]]) -> None:
    if not src.exists():
        return
    if src.resolve() == dst.resolve():
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    final_dst = dst
    if final_dst.exists():
        if final_dst.is_dir() and not any(final_dst.iterdir()):
            final_dst.rmdir()
        else:
            final_dst = _dedupe_destination(final_dst)

    moves.append({"from": str(src), "to": str(final_dst)})
    if dry_run:
        return
    shutil.move(str(src), str(final_dst))


def _classify_output_entry(entry: Path) -> Path:
    name = entry.name
    lower = name.lower()

    for project_name, prefixes in CURRENT_OUTPUT_RULES.items():
        if any(lower.startswith(prefix.lower()) for prefix in prefixes):
            return OUTPUTS_ROOT / "current" / project_name / name

    if any(marker in lower for marker in DEBUG_MARKERS):
        return OUTPUTS_ROOT / "debug" / name

    if any(marker in lower for marker in CURATION_MARKERS):
        return OUTPUTS_ROOT / "candidates" / name

    if entry.suffix.lower() == ".json":
        return OUTPUTS_ROOT / "reports" / "legacy" / name

    if (
        entry.suffix.lower() in {".mp4", ".png", ".jpg", ".jpeg"}
        and ("probe" in lower or "finalcheck" in lower or "final_check" in lower or "frame" in lower)
    ):
        return OUTPUTS_ROOT / "archive" / "runs" / name

    if entry.is_dir() and ("probe" in lower or "frames" in lower or "finalcheck" in lower or "final_check" in lower):
        return OUTPUTS_ROOT / "archive" / "runs" / name

    return OUTPUTS_ROOT / "archive" / "misc" / name


def reorganize_outputs(dry_run: bool, moves: list[dict[str, str]]) -> None:
    for entry in sorted(OUTPUTS_ROOT.iterdir(), key=lambda item: item.name.lower()):
        if entry.name in STRUCTURED_OUTPUT_DIRS:
            continue
        destination = _classify_output_entry(entry)
        _move_entry(entry, destination, dry_run=dry_run, moves=moves)


def _move_channel_children(channel_dir: Path, current_project: str, dry_run: bool, moves: list[dict[str, str]]) -> None:
    current_root = channel_dir / "current"
    archive_root = channel_dir / "archive"
    if not dry_run:
        current_root.mkdir(parents=True, exist_ok=True)
        archive_root.mkdir(parents=True, exist_ok=True)

    for child in sorted(channel_dir.iterdir(), key=lambda item: item.name.lower()):
        if child.name in {"archive", "current"}:
            continue
        if child.name == current_project:
            destination = current_root / child.name
        else:
            destination = archive_root / child.name
        _move_entry(child, destination, dry_run=dry_run, moves=moves)


def reorganize_temp_images(dry_run: bool, moves: list[dict[str, str]]) -> None:
    archive_root = TEMP_ROOT / "archive" / "top_level"
    if not dry_run:
        archive_root.mkdir(parents=True, exist_ok=True)

    for entry in sorted(TEMP_ROOT.iterdir(), key=lambda item: item.name.lower()):
        if entry.name in STRUCTURED_TEMP_DIRS:
            continue
        if entry.name in CHANNEL_CURRENT_PROJECTS:
            _move_channel_children(
                channel_dir=entry,
                current_project=CHANNEL_CURRENT_PROJECTS[entry.name],
                dry_run=dry_run,
                moves=moves,
            )
            continue
        destination = archive_root / entry.name
        _move_entry(entry, destination, dry_run=dry_run, moves=moves)


def write_summary(moves: list[dict[str, str]], dry_run: bool) -> Path:
    reports_dir = OUTPUTS_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = reports_dir / f"artifact_reorg_{timestamp}.json"
    payload = {
        "dry_run": dry_run,
        "moved_count": len(moves),
        "moves": moves,
    }
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Organize Reverie output and temp artifact folders without deleting files.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned moves and write a summary report without moving files.",
    )
    args = parser.parse_args()

    moves: list[dict[str, str]] = []
    reorganize_outputs(dry_run=args.dry_run, moves=moves)
    reorganize_temp_images(dry_run=args.dry_run, moves=moves)
    summary_path = write_summary(moves, dry_run=args.dry_run)
    print(
        json.dumps(
            {
                "dry_run": args.dry_run,
                "moved_count": len(moves),
                "summary_path": str(summary_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
