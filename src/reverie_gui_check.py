"""Safe GUI entrypoint import check for a local Reverie Studio checkout."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from utils.secret_redaction import redact_sensitive_text


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "reverie.local.gui_check.v1"
GUI_LAUNCHERS = ("run_reverie.bat", "run_reverie_silent.bat")


def _check(check_id: str, label: str, status: str, detail: str, *, required: bool = True) -> dict:
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "required": required,
        "detail": redact_sensitive_text(detail),
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_import_check(root: Path, module_name: str) -> dict:
    check_id = f"import_{module_name.rsplit('.', 1)[-1]}"
    env = os.environ.copy()
    src_path = str(root / "src")
    env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONWARNINGS"] = "ignore::FutureWarning"
    completed = subprocess.run(
        [sys.executable, "-c", f"import importlib; importlib.import_module({module_name!r})"],
        cwd=str(root),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    safe_output = redact_sensitive_text(output).strip()
    if completed.returncode == 0:
        return _check(
            check_id,
            f"Import {module_name}",
            "pass",
            f"{module_name} imports without starting the GUI event loop",
        )
    return _check(
        check_id,
        f"Import {module_name}",
        "missing",
        safe_output or f"{module_name} import failed with exit code {completed.returncode}",
    )


def _overall_status(checks: list[dict]) -> str:
    if any(check["required"] and check["status"] != "pass" for check in checks):
        return "needs_setup"
    if any(check["status"] == "warning" for check in checks):
        return "warnings"
    return "ready"


def build_gui_check_report(repo_root: Path | str | None = None, output_dir: Path | str | None = None) -> dict:
    """Check GUI import readiness without opening a window."""

    root = Path(repo_root or REPO_ROOT).resolve()
    out = Path(output_dir or Path(tempfile.gettempdir()) / "reverie-gui-check").resolve()
    missing_launchers = [name for name in GUI_LAUNCHERS if not (root / name).exists()]
    checks = [
        _check(
            "main_gui_file",
            "GUI entrypoint file",
            "pass" if (root / "src" / "main_gui.py").exists() else "missing",
            "src/main_gui.py exists" if (root / "src" / "main_gui.py").exists() else "src/main_gui.py is missing",
        ),
        _check(
            "main_window_file",
            "GUI main window file",
            "pass" if (root / "src" / "gui" / "main_window.py").exists() else "missing",
            "src/gui/main_window.py exists"
            if (root / "src" / "gui" / "main_window.py").exists()
            else "src/gui/main_window.py is missing",
        ),
        _check(
            "gui_launchers",
            "GUI launchers",
            "pass" if not missing_launchers else "missing",
            "all GUI launchers exist" if not missing_launchers else f"missing launchers: {', '.join(missing_launchers)}",
        ),
    ]
    if checks[0]["status"] == "pass":
        checks.append(_run_import_check(root, "main_gui"))
    if checks[1]["status"] == "pass":
        checks.append(_run_import_check(root, "gui.main_window"))

    report = {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root),
        "output_dir": str(out),
        "overall_status": _overall_status(checks),
        "checks": checks,
        "artifacts": {
            "json": str(out / "gui_check_report.json"),
        },
        "safety": {
            "opens_windows": False,
            "starts_gui_event_loop": False,
            "calls_external_services": False,
            "starts_local_services": False,
            "creates_media": False,
            "starts_upload": False,
            "prints_secret_values": False,
        },
    }
    _write_json(out / "gui_check_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check Reverie GUI import readiness without opening a window.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Repository root to inspect.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(os.environ.get("REVERIE_GUI_CHECK_OUT", tempfile.gettempdir())) / "reverie-gui-check",
        help="Output directory for the GUI check report.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full report JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_gui_check_report(args.repo_root, args.out)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Reverie GUI check: {report['overall_status']}")
        print(f"Report: {report['artifacts']['json']}")
    return 0 if report["overall_status"] in {"ready", "warnings"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
