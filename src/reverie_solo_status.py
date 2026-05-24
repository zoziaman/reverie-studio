"""Solo-use readiness report for a local Reverie Studio checkout.

This report is intentionally local and non-secret: it checks whether files,
folders, and launchers exist, but it never prints credential values from .env.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "reverie.local.solo_status.v1"
EXPECTED_ENV_KEYS = (
    "GEMINI_API_KEY",
    "SD_URL",
    "SOVITS_URL",
    "COMFYUI_URL",
    "TTS_ENGINE",
    "VIDEOTOON_WORKSPACE_ROOT",
)
GUI_LAUNCHERS = ("run_reverie.bat", "run_reverie_silent.bat")
PERSONAL_LAUNCHERS = (
    "run_reverie_doctor.bat",
    "run_reverie_solo_status.bat",
    "run_reverie_demo_dry_run.bat",
    "run_reverie_videotoon_smoke.bat",
)


def _check(
    check_id: str,
    label: str,
    status: str,
    detail: str,
    *,
    required: bool = False,
    next_action: str = "",
) -> dict:
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "required": required,
        "detail": detail,
        "next_action": next_action,
    }


def _missing_names(root: Path, names: tuple[str, ...]) -> list[str]:
    return [name for name in names if not (root / name).exists()]


def _env_key_names(env_path: Path) -> set[str]:
    if not env_path.exists():
        return set()

    keys: set[str] = set()
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def _status_for_path(path: Path) -> str:
    return "pass" if path.exists() else "missing"


def _count_pack_directories(root: Path) -> int:
    packs = root / "assets" / "packs"
    if not packs.exists():
        return 0
    return sum(1 for child in packs.iterdir() if child.is_dir())


def _overall_status(checks: list[dict]) -> str:
    if any(check["required"] and check["status"] != "pass" for check in checks):
        return "needs_setup"
    if any(check["status"] == "warning" for check in checks):
        return "warnings"
    return "ready"


def _next_actions(checks: list[dict]) -> list[str]:
    actions = []
    for check in checks:
        action = check.get("next_action")
        if action and action not in actions:
            actions.append(action)
    return actions


def build_solo_status_report(repo_root: Path | str | None = None) -> dict:
    """Build a local-only personal readiness report without secret values."""

    root = Path(repo_root or REPO_ROOT).resolve()
    env_template = root / ".env.example"
    env_file = root / ".env"
    env_keys = _env_key_names(env_file)
    missing_expected_env_keys = [key for key in EXPECTED_ENV_KEYS if key not in env_keys]

    gui_missing = _missing_names(root, GUI_LAUNCHERS)
    personal_missing = _missing_names(root, PERSONAL_LAUNCHERS)

    checks = [
        _check(
            "env_template",
            "Local env template",
            _status_for_path(env_template),
            ".env.example exists" if env_template.exists() else ".env.example is missing",
            required=True,
            next_action="Restore .env.example from git" if not env_template.exists() else "",
        ),
        _check(
            "local_env_file",
            "Local .env file",
            "pass" if env_file.exists() else "warning",
            ".env exists; values were not read" if env_file.exists() else ".env is missing",
            next_action="Copy .env.example to .env" if not env_file.exists() else "",
        ),
        _check(
            "expected_env_keys",
            "Expected .env keys",
            "pass" if not missing_expected_env_keys or not env_file.exists() else "warning",
            (
                f"{len(EXPECTED_ENV_KEYS) - len(missing_expected_env_keys)}/{len(EXPECTED_ENV_KEYS)} expected key names present"
                if env_file.exists()
                else "skipped because .env is missing"
            ),
            next_action=(
                "Review .env.example and fill missing local key names"
                if env_file.exists() and missing_expected_env_keys
                else ""
            ),
        ),
        _check(
            "config_dir",
            "Config directory",
            _status_for_path(root / "config"),
            "config directory exists" if (root / "config").exists() else "config directory is missing",
            required=True,
        ),
        _check(
            "data_dir",
            "Data directory",
            _status_for_path(root / "data"),
            "data directory exists" if (root / "data").exists() else "data directory is missing",
            required=True,
        ),
        _check(
            "packs_dir",
            "Content packs directory",
            _status_for_path(root / "assets" / "packs"),
            f"{_count_pack_directories(root)} pack directories found",
            required=True,
        ),
        _check(
            "public_demo_pack",
            "Public demo pack",
            _status_for_path(root / "examples" / "public_demo_pack.json"),
            "examples/public_demo_pack.json exists"
            if (root / "examples" / "public_demo_pack.json").exists()
            else "examples/public_demo_pack.json is missing",
            required=True,
        ),
        _check(
            "gui_entrypoint",
            "GUI entrypoint",
            _status_for_path(root / "src" / "main_gui.py"),
            "src/main_gui.py exists" if (root / "src" / "main_gui.py").exists() else "src/main_gui.py is missing",
            required=True,
        ),
        _check(
            "gui_launchers",
            "GUI launchers",
            "pass" if not gui_missing else "missing",
            "all GUI launchers exist" if not gui_missing else f"missing launchers: {', '.join(gui_missing)}",
            required=True,
        ),
        _check(
            "personal_launchers",
            "Personal-use launchers",
            "pass" if not personal_missing else "warning",
            "all personal launchers exist"
            if not personal_missing
            else f"missing launchers: {', '.join(personal_missing)}",
            next_action="Restore missing run_reverie_*.bat launchers" if personal_missing else "",
        ),
        _check(
            "remotion_project",
            "Remotion project",
            _status_for_path(root / "remotion-poc" / "package.json"),
            "remotion-poc/package.json exists"
            if (root / "remotion-poc" / "package.json").exists()
            else "remotion-poc/package.json is missing",
            required=True,
        ),
    ]

    return {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root),
        "overall_status": _overall_status(checks),
        "checks": checks,
        "counts": {
            "pack_directory_count": _count_pack_directories(root),
            "expected_env_key_count": len(EXPECTED_ENV_KEYS),
            "present_expected_env_key_count": len(EXPECTED_ENV_KEYS) - len(missing_expected_env_keys)
            if env_file.exists()
            else 0,
        },
        "next_actions": _next_actions(checks),
        "safety": {
            "reads_env_values": False,
            "prints_secret_values": False,
            "calls_external_services": False,
            "starts_local_services": False,
            "writes_generated_media": False,
        },
    }


def write_solo_status_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check solo-use readiness for a local Reverie Studio checkout.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Repository root to inspect.")
    parser.add_argument("--out", type=Path, help="Optional JSON output path.")
    parser.add_argument("--json", action="store_true", help="Print the full report JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_solo_status_report(args.repo_root)
    if args.out:
        write_solo_status_report(args.out, report)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Reverie solo status: {report['overall_status']}")
        for check in report["checks"]:
            print(f"- {check['id']}: {check['status']} ({check['detail']})")
    return 0 if report["overall_status"] in {"ready", "warnings"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
