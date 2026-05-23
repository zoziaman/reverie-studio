"""Create a history-free public source export for Reverie Studio."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_CHECK_PATH = REPO_ROOT / "scripts" / "public_snapshot_check.py"
DEFAULT_EXPORT_OUT = Path(tempfile.gettempdir()) / "reverie-public-export"
ARCHIVE_NAME = "reverie-public-snapshot.zip"
MANIFEST_NAME = "public_export_manifest.json"


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


def _git_stdout(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout


def _archive_file_count(archive_path: Path) -> int:
    with zipfile.ZipFile(archive_path, "r") as archive:
        return len([name for name in archive.namelist() if not name.endswith("/")])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_integrity_report(archive_path: Path, tracked_file_count: int) -> dict[str, Any]:
    with zipfile.ZipFile(archive_path, "r") as archive:
        file_names = [name.replace("\\", "/") for name in archive.namelist() if not name.endswith("/")]
    contains_git_metadata = any(
        name == ".git" or name.startswith(".git/") or "/.git/" in name
        for name in file_names
    )
    contains_unsafe_paths = any(
        name.startswith("/") or name == ".." or name.startswith("../") or "/../" in name
        for name in file_names
    )
    count_matches_tracked_files = len(file_names) == tracked_file_count
    status = (
        "pass"
        if not contains_git_metadata and not contains_unsafe_paths and count_matches_tracked_files
        else "fail"
    )
    return {
        "status": status,
        "contains_git_metadata": contains_git_metadata,
        "contains_unsafe_paths": contains_unsafe_paths,
        "count_matches_tracked_files": count_matches_tracked_files,
    }


def _workspace_state() -> dict[str, Any]:
    changed_paths = [
        line for line in _git_stdout(["status", "--porcelain=v1", "--untracked-files=normal"]).splitlines()
        if line.strip()
    ]
    return {
        "status": "review_required" if changed_paths else "pass",
        "dirty_count": len(changed_paths),
    }


def create_public_export(
    output_dir: Path | str = DEFAULT_EXPORT_OUT,
    *,
    allow_repo_output: bool = False,
) -> dict[str, Any]:
    out = Path(output_dir).resolve()
    repo_root = REPO_ROOT.resolve()
    if _is_relative_to(out, repo_root) and not allow_repo_output:
        raise ValueError(
            "public export output must be outside the repository "
            "(pass --allow-repo-output only for intentional local debugging)"
        )

    out.mkdir(parents=True, exist_ok=True)
    archive_path = out / ARCHIVE_NAME
    manifest_path = out / MANIFEST_NAME

    snapshot_check = _load_public_snapshot_check()
    snapshot_findings = snapshot_check.run_check(repo_root)
    snapshot_report = snapshot_check.build_json_report(snapshot_findings)
    if snapshot_report.get("status") != "pass":
        raise RuntimeError("public snapshot check failed; refusing to create export archive")
    workspace_state = _workspace_state()
    if workspace_state["status"] != "pass":
        raise RuntimeError("workspace is not clean; refusing to create export archive from HEAD")

    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive_path), "HEAD"],
        cwd=repo_root,
        capture_output=True,
        check=True,
        text=True,
    )
    tracked_files = [line for line in _git_stdout(["ls-files"]).splitlines() if line.strip()]
    archive_file_count = _archive_file_count(archive_path)
    archive_integrity = _archive_integrity_report(archive_path, len(tracked_files))
    if archive_integrity["status"] != "pass":
        raise RuntimeError("archive integrity check failed; refusing to write export manifest")
    manifest = {
        "schema": "reverie.public_export.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "archive_path": ARCHIVE_NAME,
        "manifest_path": MANIFEST_NAME,
        "source_commit": _git_stdout(["rev-parse", "HEAD"]).strip(),
        "source_tree": _git_stdout(["rev-parse", "HEAD^{tree}"]).strip(),
        "tracked_file_count": len(tracked_files),
        "archive_file_count": archive_file_count,
        "archive_sha256": _sha256_file(archive_path),
        "archive_integrity": archive_integrity,
        "git_history_included": False,
        "workspace_state": workspace_state,
        "public_snapshot": snapshot_report,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def _check_status(condition: bool) -> str:
    return "pass" if condition else "fail"


def verify_public_export(output_dir: Path | str = DEFAULT_EXPORT_OUT) -> dict[str, Any]:
    out = Path(output_dir).resolve()
    manifest_path = out / MANIFEST_NAME
    archive_path = out / ARCHIVE_NAME
    if not manifest_path.exists():
        return {
            "schema": "reverie.public_export.verify.v1",
            "status": "fail",
            "archive_path": ARCHIVE_NAME,
            "manifest_path": MANIFEST_NAME,
            "checks": {
                "manifest_exists": {"status": "fail"},
                "archive_exists": {"status": "pass" if archive_path.exists() else "fail"},
            },
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive_exists = archive_path.exists()
    actual_sha = _sha256_file(archive_path) if archive_exists else ""
    expected_sha = str(manifest.get("archive_sha256") or "")
    tracked_file_count = int(manifest.get("tracked_file_count") or 0)
    actual_archive_count = _archive_file_count(archive_path) if archive_exists else 0
    expected_archive_count = int(manifest.get("archive_file_count") or 0)
    actual_integrity = (
        _archive_integrity_report(archive_path, tracked_file_count)
        if archive_exists
        else {
            "status": "fail",
            "contains_git_metadata": False,
            "contains_unsafe_paths": False,
            "count_matches_tracked_files": False,
        }
    )
    checks = {
        "manifest_exists": {"status": "pass"},
        "archive_exists": {"status": "pass" if archive_exists else "fail"},
        "manifest_schema": {
            "status": _check_status(manifest.get("schema") == "reverie.public_export.v1"),
        },
        "archive_path": {
            "status": _check_status(manifest.get("archive_path") == ARCHIVE_NAME),
        },
        "archive_sha256": {
            "status": _check_status(bool(expected_sha) and expected_sha == actual_sha),
            "expected": expected_sha,
            "actual": actual_sha,
        },
        "archive_file_count": {
            "status": _check_status(expected_archive_count == actual_archive_count),
            "expected": expected_archive_count,
            "actual": actual_archive_count,
        },
        "archive_integrity": actual_integrity,
        "git_history_included": {
            "status": _check_status(manifest.get("git_history_included") is False),
        },
        "public_snapshot": {
            "status": _check_status((manifest.get("public_snapshot") or {}).get("status") == "pass"),
        },
    }
    status = "pass" if all(check.get("status") == "pass" for check in checks.values()) else "fail"
    return {
        "schema": "reverie.public_export.verify.v1",
        "status": status,
        "archive_path": ARCHIVE_NAME,
        "manifest_path": MANIFEST_NAME,
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a history-free Reverie Studio public source export.")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_EXPORT_OUT,
        help="Output directory for the source archive and manifest. Defaults outside the repository.",
    )
    parser.add_argument("--allow-repo-output", action="store_true", help="Allow export output inside the repo.")
    parser.add_argument("--verify", action="store_true", help="Verify an existing export archive and manifest.")
    parser.add_argument("--json", action="store_true", help="Print the export manifest JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verify:
        report = verify_public_export(args.out)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(f"Public export verify: {report['status'].upper()}")
        return 0 if report["status"] == "pass" else 1

    try:
        manifest = create_public_export(args.out, allow_repo_output=args.allow_repo_output)
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Public export: BLOCKED - {exc}")
        return 1

    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        output_dir = Path(args.out).resolve()
        print("Public export: PASS")
        print(f"Archive: {output_dir / ARCHIVE_NAME}")
        print(f"Manifest: {output_dir / MANIFEST_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
