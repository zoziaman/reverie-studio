"""Create a local .env file from .env.example without overwriting secrets."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "reverie.local.env_bootstrap.v1"


def _report(
    repo_root: Path,
    status: str,
    message: str,
    *,
    exit_code: int,
    next_action: str = "",
    created_path: Path | None = None,
) -> dict:
    return {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "status": status,
        "message": message,
        "created_path": str(created_path) if created_path else "",
        "next_action": next_action,
        "exit_code": exit_code,
        "safety": {
            "reads_env_values": False,
            "prints_secret_values": False,
            "overwrites_existing_env": False,
        },
    }


def bootstrap_env_file(repo_root: Path | str | None = None) -> dict:
    """Copy .env.example to .env if .env is missing."""

    root = Path(repo_root or REPO_ROOT).resolve()
    template = root / ".env.example"
    target = root / ".env"

    if not template.exists():
        return _report(
            root,
            "missing_template",
            ".env.example is missing",
            exit_code=1,
            next_action="Restore .env.example from git before creating .env",
        )

    if target.exists():
        return _report(
            root,
            "exists",
            ".env already exists; leaving it untouched",
            exit_code=0,
            next_action="Edit .env manually if local paths or keys need changes",
            created_path=target,
        )

    shutil.copyfile(template, target)
    return _report(
        root,
        "created",
        "Created .env from .env.example",
        exit_code=0,
        next_action="Edit .env and fill only the local values you need",
        created_path=target,
    )


def write_bootstrap_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a local .env file from .env.example without overwriting it.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Repository root to update.")
    parser.add_argument("--out", type=Path, help="Optional JSON report output path.")
    parser.add_argument("--json", action="store_true", help="Print the full report JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = bootstrap_env_file(args.repo_root)
    if args.out:
        write_bootstrap_report(args.out, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Reverie env bootstrap: {report['status']}")
        print(report["message"])
        if report["next_action"]:
            print(f"Next: {report['next_action']}")
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
