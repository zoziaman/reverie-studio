"""Safe handoff report for continuing a solo Reverie Studio session."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from reverie_solo_preflight import run_solo_preflight
from reverie_solo_status import build_solo_status_report


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "reverie.local.solo_handoff.v1"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _git_lines(root: Path, *args: str) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    return [line.rstrip() for line in completed.stdout.splitlines() if line.strip()]


def _git_scalar(root: Path, *args: str) -> str:
    lines = _git_lines(root, *args)
    return lines[0] if lines else ""


def build_git_context(root: Path) -> dict:
    status_short = _git_lines(root, "status", "--short")
    return {
        "branch": _git_scalar(root, "branch", "--show-current") or "(detached or unavailable)",
        "head": _git_scalar(root, "rev-parse", "--short", "HEAD"),
        "dirty": bool(status_short),
        "status_short": status_short,
        "recent_commits": _git_lines(root, "log", "--oneline", "-8"),
    }


def _overall_status(solo_status: str, preflight_status: str, dirty: bool) -> str:
    if solo_status == "needs_setup" or preflight_status == "needs_setup":
        return "needs_setup"
    if dirty or solo_status == "warnings" or preflight_status == "warnings":
        return "warnings"
    return "ready"


def _next_actions(report: dict) -> list[str]:
    actions = list(report["checks"]["solo_status"].get("next_actions", []))
    if report["checks"]["preflight"]["status"] == "needs_setup":
        actions.append("Run run_reverie_daily_check.bat and inspect the preflight report.")
    if report["git"]["dirty"]:
        actions.append("Review git status --short before handing this session to another agent.")
    return actions


def render_markdown(report: dict) -> str:
    git = report["git"]
    lines = [
        "# Reverie Solo Handoff",
        "",
        f"Created: {report['created_at']}",
        f"Repository: {report['repo_root']}",
        f"Overall status: {report['overall_status']}",
        "",
        "## Plain Meaning",
        "",
        "- This is a personal continuation snapshot, not a public release report.",
        f"- Local readiness check: {report['checks']['solo_status']['status']}.",
        f"- Daily safe preflight: {report['checks']['preflight']['status']}.",
        f"- Git branch: {git['branch']}.",
        "- No .env values, credentials, generated media, or uploads are included.",
        "",
        "## Next Session Start",
        "",
        "1. Open this repository root.",
        "2. Read docs/SOLO_USE_RUNBOOK.md if the session context is unclear.",
        "3. Run run_reverie_daily_check.bat before changing runtime behavior.",
        "4. Check git status --short before editing files.",
        "",
        "## Git Snapshot",
        "",
        f"- Branch: {git['branch']}",
        f"- Head: {git['head']}",
        f"- Dirty worktree: {str(git['dirty']).lower()}",
        "",
        "Status lines:",
    ]
    lines.extend([f"- {line}" for line in git["status_short"]] or ["- clean"])
    lines.extend(["", "Recent commits:"])
    lines.extend([f"- {line}" for line in git["recent_commits"]] or ["- unavailable"])
    lines.extend(["", "## Next Actions", ""])
    lines.extend([f"- {action}" for action in report["next_actions"]] or ["- none"])
    lines.extend(
        [
            "",
            "## Reports",
            "",
            f"- JSON: {report['artifacts']['json']}",
            f"- Markdown: {report['artifacts']['markdown']}",
            f"- Preflight: {report['artifacts']['preflight_report']}",
            "",
        ]
    )
    return "\n".join(lines)


def build_solo_handoff_report(repo_root: Path | str | None = None, output_dir: Path | str | None = None) -> dict:
    """Build and write a safe continuation report for another local session."""

    root = Path(repo_root or REPO_ROOT).resolve()
    out = Path(output_dir or Path(tempfile.gettempdir()) / "reverie-solo-handoff").resolve()
    out.mkdir(parents=True, exist_ok=True)

    solo_report = build_solo_status_report(root)
    preflight_report = run_solo_preflight(root, out / "preflight")
    git_context = build_git_context(root)

    report = {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root),
        "output_dir": str(out),
        "overall_status": _overall_status(
            solo_report.get("overall_status", "needs_setup"),
            preflight_report.get("overall_status", "needs_setup"),
            git_context["dirty"],
        ),
        "checks": {
            "solo_status": {
                "status": solo_report.get("overall_status", "needs_setup"),
                "next_actions": solo_report.get("next_actions", []),
            },
            "preflight": {
                "status": preflight_report.get("overall_status", "needs_setup"),
                "dry_run": preflight_report.get("checks", {}).get("dry_run", {}),
            },
        },
        "git": git_context,
        "next_actions": [],
        "artifacts": {
            "json": str(out / "solo_handoff_report.json"),
            "markdown": str(out / "solo_handoff.md"),
            "preflight_report": preflight_report.get("artifacts", {}).get("solo_preflight_report", ""),
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
    report["next_actions"] = _next_actions(report)
    _write_json(out / "solo_handoff_report.json", report)
    _write_text(out / "solo_handoff.md", render_markdown(report))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write a safe solo-use session handoff report.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Repository root to inspect.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(os.environ.get("REVERIE_SOLO_HANDOFF_OUT", tempfile.gettempdir()))
        / "reverie-solo-handoff",
        help="Output directory for handoff reports.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full report JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_solo_handoff_report(args.repo_root, args.out)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Reverie solo handoff: {report['overall_status']}")
        print(f"Reports: {report['output_dir']}")
    return 0 if report["overall_status"] in {"ready", "warnings"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
