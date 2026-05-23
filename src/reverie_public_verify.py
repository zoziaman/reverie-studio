"""One-command public verification for the Reverie Studio snapshot.

The verifier is intentionally public-safe: it does not read credentials, start
local services, call cloud APIs, or create generated media. It writes reports
outside the repository by default.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from reverie_demo import DEFAULT_PACK_PATH, run_demo
from reverie_doctor import build_environment_report


REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_CHECK_PATH = REPO_ROOT / "scripts" / "public_snapshot_check.py"
DEFAULT_VERIFY_OUT = Path(tempfile.gettempdir()) / "reverie-public-verify"


def _load_public_snapshot_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("public_snapshot_check", SNAPSHOT_CHECK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SNAPSHOT_CHECK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _tail(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def _run_pytest(pytest_args: list[str], timeout_seconds: int) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", *pytest_args]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "status": "pass" if completed.returncode == 0 else "fail",
            "command": command,
            "returncode": completed.returncode,
            "stdout_tail": _tail(completed.stdout or ""),
            "stderr_tail": _tail(completed.stderr or ""),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "command": command,
            "returncode": None,
            "stdout_tail": _tail(exc.stdout or ""),
            "stderr_tail": _tail(exc.stderr or ""),
            "timeout_seconds": timeout_seconds,
        }


def run_public_verification(
    output_dir: Path | str = DEFAULT_VERIFY_OUT,
    *,
    backend_profile_id: str = "local_dry_run",
    quality_threshold: float = 0.75,
    with_pytest: bool = False,
    pytest_args: list[str] | None = None,
    pytest_timeout_seconds: int = 300,
    allow_repo_output: bool = False,
) -> dict[str, Any]:
    """Run the public-safe verification bundle and return its report."""

    out = Path(output_dir).resolve()
    repo_root = REPO_ROOT.resolve()
    if _is_relative_to(out, repo_root) and not allow_repo_output:
        raise ValueError(
            "public verification output must be outside the repository "
            "(pass --allow-repo-output only for intentional local debugging)"
        )

    out.mkdir(parents=True, exist_ok=True)
    demo_out = out / "public_demo"

    snapshot_check = _load_public_snapshot_check()
    snapshot_findings = snapshot_check.run_check(repo_root)
    environment_report = build_environment_report(repo_root)
    demo_manifest = run_demo(
        DEFAULT_PACK_PATH,
        demo_out,
        backend_profile_id=backend_profile_id,
        quality_threshold=quality_threshold,
    )

    pytest_report = None
    if with_pytest:
        pytest_report = _run_pytest(pytest_args or ["-q"], pytest_timeout_seconds)

    failures: list[str] = []
    warnings: list[str] = []
    if snapshot_findings:
        failures.append("public_snapshot_check reported release-blocking findings")

    demo_safety = demo_manifest.get("safety", {})
    if demo_safety.get("uses_credentials") or demo_safety.get("calls_external_services"):
        failures.append("public demo attempted credential or external-service behavior")
    if demo_safety.get("creates_media") or demo_safety.get("starts_upload"):
        failures.append("public demo attempted media generation or upload behavior")
    if demo_manifest.get("final_status") != "needs_human_review":
        failures.append("public demo did not preserve the manual review gate")

    if environment_report.get("overall_status") == "needs_setup":
        warnings.append("local tool setup is incomplete on this machine")
    elif environment_report.get("overall_status") != "pass":
        failures.append("environment doctor returned an unexpected blocking status")

    if pytest_report and pytest_report["status"] != "pass":
        failures.append(f"pytest returned {pytest_report['status']}")

    if failures:
        overall_status = "fail"
    elif warnings:
        overall_status = "needs_setup"
    else:
        overall_status = "pass"

    report = {
        "schema": "reverie.public_verify.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "output_dir": str(out),
        "overall_status": overall_status,
        "failures": failures,
        "warnings": warnings,
        "checks": {
            "public_snapshot": {
                "status": "pass" if not snapshot_findings else "fail",
                "finding_count": len(snapshot_findings),
                "findings": snapshot_findings,
            },
            "environment_doctor": {
                "status": environment_report.get("overall_status"),
                "report_path": str(demo_out / "environment_report.json"),
            },
            "public_demo": {
                "status": demo_manifest.get("final_status"),
                "quality_status": demo_manifest.get("quality_gate", {}).get("status"),
                "report_path": str(demo_out / "run_manifest.json"),
                "safety": demo_safety,
            },
            "pytest": pytest_report or {"status": "not_run"},
        },
    }
    (out / "public_verify_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run public-safe Reverie Studio verification checks.")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_VERIFY_OUT,
        help="Output directory for verification reports. Defaults outside the repository.",
    )
    parser.add_argument("--backend-profile", default="local_dry_run", help="Dry-run backend profile.")
    parser.add_argument("--quality-threshold", type=float, default=0.75, help="Dry-run quality threshold.")
    parser.add_argument("--with-pytest", action="store_true", help="Also run pytest after public safety checks.")
    parser.add_argument(
        "--pytest-arg",
        action="append",
        dest="pytest_args",
        help="Extra pytest argument. Repeat for multiple args. Defaults to -q when --with-pytest is used.",
    )
    parser.add_argument("--pytest-timeout", type=int, default=300, help="Pytest timeout in seconds.")
    parser.add_argument("--allow-repo-output", action="store_true", help="Allow report output inside the repo.")
    parser.add_argument("--json", action="store_true", help="Print the full verification report JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_public_verification(
            args.out,
            backend_profile_id=args.backend_profile,
            quality_threshold=args.quality_threshold,
            with_pytest=args.with_pytest,
            pytest_args=args.pytest_args,
            pytest_timeout_seconds=args.pytest_timeout,
            allow_repo_output=args.allow_repo_output,
        )
    except ValueError as exc:
        print(f"Public verification: BLOCKED - {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Public verification: {report['overall_status'].upper()}")
        print(f"Report: {Path(report['output_dir']) / 'public_verify_report.json'}")
        for failure in report["failures"]:
            print(f"- FAIL: {failure}")
        for warning in report["warnings"]:
            print(f"- WARN: {warning}")
    return 1 if report["overall_status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
