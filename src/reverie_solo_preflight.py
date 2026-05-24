"""One-command safe daily preflight for a solo Reverie Studio checkout."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from reverie_demo import DEFAULT_PACK_PATH, run_demo
from reverie_doctor import build_environment_report
from reverie_solo_status import build_solo_status_report


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "reverie.local.solo_preflight.v1"


def _status_from_checks(solo_status: str, doctor_status: str, dry_run_status: str) -> str:
    if dry_run_status != "pass" or solo_status == "needs_setup":
        return "needs_setup"
    if doctor_status == "needs_setup" or solo_status == "warnings":
        return "warnings"
    return "ready"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_solo_preflight(repo_root: Path | str | None = None, output_dir: Path | str | None = None) -> dict:
    """Run safe local status, doctor, and dry-run checks."""

    root = Path(repo_root or REPO_ROOT).resolve()
    out = Path(output_dir or Path(tempfile.gettempdir()) / "reverie-solo-preflight").resolve()
    out.mkdir(parents=True, exist_ok=True)

    solo_report = build_solo_status_report(root)
    doctor_report = build_environment_report(root)
    dry_run_dir = out / "dry_run"
    demo_manifest = run_demo(
        DEFAULT_PACK_PATH,
        dry_run_dir,
        backend_profile_id="local_dry_run",
        quality_threshold=0.75,
    )
    dry_run_passed = (
        demo_manifest.get("quality_gate", {}).get("status") == "pass"
        and demo_manifest.get("safety", {}).get("calls_external_services") is False
        and demo_manifest.get("safety", {}).get("creates_media") is False
        and demo_manifest.get("safety", {}).get("starts_upload") is False
    )
    dry_run_status = "pass" if dry_run_passed else "failed"

    report = {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root),
        "output_dir": str(out),
        "overall_status": _status_from_checks(
            solo_report.get("overall_status", "needs_setup"),
            doctor_report.get("overall_status", "needs_setup"),
            dry_run_status,
        ),
        "checks": {
            "solo_status": {
                "status": solo_report.get("overall_status", "needs_setup"),
                "next_actions": solo_report.get("next_actions", []),
            },
            "environment_doctor": {
                "status": doctor_report.get("overall_status", "needs_setup"),
            },
            "dry_run": {
                "status": dry_run_status,
                "final_status": demo_manifest.get("final_status", ""),
                "quality_gate": demo_manifest.get("quality_gate", {}).get("status", ""),
            },
        },
        "counts": {
            "pack_directory_count": solo_report.get("counts", {}).get("pack_directory_count", 0),
            "dry_run_stage_count": demo_manifest.get("stage_count", 0),
        },
        "artifacts": {
            "solo_preflight_report": str(out / "solo_preflight_report.json"),
            "dry_run_manifest": str(dry_run_dir / "run_manifest.json"),
            "dry_run_report": str(dry_run_dir / "pipeline_report.md"),
        },
        "safety": {
            "reads_env_values": False,
            "prints_secret_values": False,
            "calls_external_services": False,
            "starts_local_services": False,
            "creates_media": False,
            "starts_upload": False,
        },
    }
    _write_json(out / "solo_status.json", solo_report)
    _write_json(out / "environment_report.json", doctor_report)
    _write_json(out / "solo_preflight_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run safe solo-use daily checks for Reverie Studio.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Repository root to inspect.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(os.environ.get("REVERIE_SOLO_PREFLIGHT_OUT", tempfile.gettempdir()))
        / "reverie-solo-preflight",
        help="Output directory for preflight reports.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full report JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_solo_preflight(args.repo_root, args.out)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Reverie solo preflight: {report['overall_status']}")
        print(f"Reports: {report['output_dir']}")
    return 0 if report["overall_status"] in {"ready", "warnings"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
