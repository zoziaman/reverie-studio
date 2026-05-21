"""Local setup doctor for the public Reverie Studio snapshot.

The doctor checks tool availability and public fixture files. It does not read
credential files, contact cloud APIs, or start local AI services.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _detect_tool_version(command: str) -> str | None:
    executable = shutil.which(command)
    if not executable:
        return None
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return "found"
    first_line = (completed.stdout or completed.stderr or "found").splitlines()[0]
    return first_line[:160]


def _status_from_version(version: str | None) -> str:
    return "pass" if version else "missing"


def _service_status(value: bool | None) -> str:
    if value is True:
        return "pass"
    if value is False:
        return "not_running"
    return "not_checked"


def build_environment_report(
    repo_root: Path | str | None = None,
    tool_versions: dict[str, str | None] | None = None,
    service_status: dict[str, bool | None] | None = None,
) -> dict:
    """Build a public-safe local setup report."""

    root = Path(repo_root or REPO_ROOT).resolve()
    if tool_versions is None:
        tool_versions = {
            "ffmpeg": _detect_tool_version("ffmpeg"),
            "node": _detect_tool_version("node"),
            "npm": _detect_tool_version("npm"),
        }
    if service_status is None:
        service_status = {"comfyui": None, "tts": None}

    checks = [
        {
            "id": "python",
            "label": "Python runtime",
            "status": "pass",
            "required": True,
            "detail": sys.version.split()[0],
        },
        {
            "id": "ffmpeg",
            "label": "FFmpeg",
            "status": _status_from_version(tool_versions.get("ffmpeg")),
            "required": True,
            "detail": tool_versions.get("ffmpeg") or "not found on PATH",
        },
        {
            "id": "node",
            "label": "Node.js",
            "status": _status_from_version(tool_versions.get("node")),
            "required": True,
            "detail": tool_versions.get("node") or "not found on PATH",
        },
        {
            "id": "npm",
            "label": "npm",
            "status": _status_from_version(tool_versions.get("npm")),
            "required": True,
            "detail": tool_versions.get("npm") or "not found on PATH",
        },
        {
            "id": "public_demo_pack",
            "label": "Public demo content pack",
            "status": "pass" if (root / "examples" / "public_demo_pack.json").exists() else "missing",
            "required": True,
            "detail": "examples/public_demo_pack.json",
        },
        {
            "id": "local_env_file",
            "label": "Local .env file",
            "status": "warning" if (root / ".env").exists() else "pass",
            "required": False,
            "detail": ".env is not read by this doctor",
        },
        {
            "id": "comfyui_service",
            "label": "ComfyUI local service",
            "status": _service_status(service_status.get("comfyui")),
            "required": False,
            "detail": "not probed unless a caller supplies service status",
        },
        {
            "id": "tts_service",
            "label": "TTS local service",
            "status": _service_status(service_status.get("tts")),
            "required": False,
            "detail": "not probed unless a caller supplies service status",
        },
    ]

    blocking_statuses = {"missing", "error", "not_running"}
    overall_status = "needs_setup" if any(check["status"] in blocking_statuses for check in checks) else "pass"
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall_status,
        "checks": checks,
        "safety": {
            "reads_credentials": False,
            "calls_external_services": False,
            "starts_local_services": False,
            "writes_generated_media": False,
        },
    }


def write_environment_report(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check local prerequisites for Reverie Studio.")
    parser.add_argument(
        "--out",
        type=Path,
        help="Optional JSON output path. The file contains no credentials or generated media.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full report JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_environment_report()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_environment_report(args.out, report)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Reverie doctor status: {report['overall_status']}")
        for check in report["checks"]:
            print(f"- {check['id']}: {check['status']} ({check['detail']})")
    return 0 if report["overall_status"] in {"pass", "needs_setup"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
