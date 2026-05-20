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
from utils.runtime_utils import ensure_report_output_dir


def _character_ids_from_active_pack(manager: CharacterLibraryManager) -> list[str]:
    characters = getattr(getattr(ACTIVE_PACK, "visual_storytelling", None), "characters", []) or []
    ids: list[str] = []
    for character in characters:
        char_id = str(getattr(character, "id", "") or "").strip()
        has_library_entry = bool(manager.get_character(char_id))
        has_sheet = manager._character_sheet_path(char_id).exists()
        if char_id and char_id not in ids and (has_library_entry or has_sheet):
            ids.append(char_id)
    return ids


def _render_markdown(pack_id: str, audit_rows: list[dict]) -> str:
    lines = [f"# Character Sheet Audit - {pack_id}", ""]
    for row in audit_rows:
        lines.append(f"## {row['character_id']} [{row['status']}]")
        coverage = row.get("coverage", {})
        lines.append(
            f"- coverage: {len(coverage.get('existing_keys', []))}/{len(coverage.get('required_keys', []))}"
        )
        if coverage.get("missing_keys"):
            lines.append(f"- missing variants: {', '.join(coverage['missing_keys'])}")
        if row.get("issues"):
            lines.append("- issues:")
            for issue in row["issues"]:
                label = str(issue.get("variant_key", "") or "").strip()
                prefix = f"  - [{label}] " if label else "  - "
                lines.append(f"{prefix}{issue.get('code')}: {issue.get('message')}")
        if row.get("warnings"):
            lines.append("- warnings:")
            for warning in row["warnings"]:
                label = str(warning.get("variant_key", "") or "").strip()
                prefix = f"  - [{label}] " if label else "  - "
                lines.append(f"{prefix}{warning.get('code')}: {warning.get('message')}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def audit_pack(pack_id: str) -> dict:
    load_pack_by_id(pack_id)
    manager = CharacterLibraryManager(pack_id=pack_id)
    rows = [manager.audit_character_sheet(character_id) for character_id in _character_ids_from_active_pack(manager)]
    status = "pass"
    if any(row.get("status") == "fail" for row in rows):
        status = "fail"
    elif any(row.get("status") == "warning" for row in rows):
        status = "warning"
    return {
        "pack_id": pack_id,
        "status": status,
        "characters": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit production character sheets for required assets.")
    parser.add_argument(
        "--pack",
        action="append",
        dest="packs",
        help="Pack ID to audit. Can be provided multiple times.",
    )
    args = parser.parse_args()

    pack_ids = list(dict.fromkeys(args.packs or ["senior_scam_alert", "senior_life_saguk"]))
    reports: list[dict] = [audit_pack(pack_id) for pack_id in pack_ids]

    out_dir = ensure_report_output_dir("character_audit")
    json_path = out_dir / "character_sheet_audit_latest.json"
    md_path = out_dir / "character_sheet_audit_latest.md"
    json_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(
        "\n\n".join(_render_markdown(report["pack_id"], report["characters"]) for report in reports),
        encoding="utf-8",
    )
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "status": [r["status"] for r in reports]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
