import json
import importlib.util
import subprocess
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_public_export():
    spec = importlib.util.spec_from_file_location("public_export", ROOT / "scripts" / "public_export.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


public_export = _load_public_export()


def test_public_export_refuses_repo_output_by_default():
    with pytest.raises(ValueError, match="outside the repository"):
        public_export.create_public_export(public_export.REPO_ROOT / "tmp-public-export")


def test_public_export_blocks_when_snapshot_check_fails(tmp_path, monkeypatch):
    class SnapshotCheck:
        def run_check(self, root):
            return ["config/client_secret_alice.json: blocked filename pattern: client_secret_alice.json"]

        def build_json_report(self, findings):
            return {
                "schema": "reverie.public_snapshot_check.v1",
                "status": "fail",
                "finding_count": len(findings),
                "finding_types": {"blocked filename pattern": 1},
                "finding_fingerprints": [{"reason": "blocked filename pattern", "fingerprint": "abc123"}],
                "truncated_finding_fingerprints": 0,
            }

    monkeypatch.setattr(public_export, "_load_public_snapshot_check", lambda: SnapshotCheck())

    with pytest.raises(RuntimeError, match="public snapshot check failed"):
        public_export.create_public_export(tmp_path)

    assert not (tmp_path / "reverie-public-snapshot.zip").exists()


def test_public_export_blocks_dirty_workspace(tmp_path, monkeypatch):
    class SnapshotCheck:
        def run_check(self, root):
            return []

        def build_json_report(self, findings):
            return {
                "schema": "reverie.public_snapshot_check.v1",
                "status": "pass",
                "finding_count": 0,
                "finding_types": {},
                "finding_fingerprints": [],
                "truncated_finding_fingerprints": 0,
            }

    def fake_git(args):
        if args == ["status", "--porcelain=v1", "--untracked-files=normal"]:
            return " M README.md\n"
        raise AssertionError(args)

    monkeypatch.setattr(public_export, "_load_public_snapshot_check", lambda: SnapshotCheck())
    monkeypatch.setattr(public_export, "_git_stdout", fake_git)

    with pytest.raises(RuntimeError, match="workspace is not clean"):
        public_export.create_public_export(tmp_path)

    assert not (tmp_path / "reverie-public-snapshot.zip").exists()


def test_public_export_writes_archive_and_manifest(tmp_path, monkeypatch):
    commands = []

    class SnapshotCheck:
        def run_check(self, root):
            return []

        def build_json_report(self, findings):
            return {
                "schema": "reverie.public_snapshot_check.v1",
                "status": "pass",
                "finding_count": 0,
                "finding_types": {},
                "finding_fingerprints": [],
                "truncated_finding_fingerprints": 0,
            }

    def fake_git(args):
        commands.append(args)
        if args == ["rev-parse", "HEAD"]:
            return "abc123\n"
        if args == ["rev-parse", "HEAD^{tree}"]:
            return "def456\n"
        if args == ["ls-files"]:
            return "README.md\nsrc/reverie_demo.py\n"
        if args == ["status", "--porcelain=v1", "--untracked-files=normal"]:
            return ""
        raise AssertionError(args)

    def fake_run(command, **kwargs):
        commands.append(command)
        archive_path = Path(command[4])
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("README.md", "# demo\n")
            archive.writestr("src/reverie_demo.py", "print('demo')\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(public_export, "_load_public_snapshot_check", lambda: SnapshotCheck())
    monkeypatch.setattr(public_export, "_git_stdout", fake_git)
    monkeypatch.setattr(public_export.subprocess, "run", fake_run)

    manifest = public_export.create_public_export(tmp_path)
    saved = json.loads((tmp_path / "public_export_manifest.json").read_text(encoding="utf-8"))

    assert manifest == saved
    assert manifest["schema"] == "reverie.public_export.v1"
    assert manifest["archive_path"] == "reverie-public-snapshot.zip"
    assert manifest["manifest_path"] == "public_export_manifest.json"
    assert manifest["git_history_included"] is False
    assert manifest["source_commit"] == "abc123"
    assert manifest["source_tree"] == "def456"
    assert manifest["tracked_file_count"] == 2
    assert manifest["archive_file_count"] == 2
    assert manifest["workspace_state"]["status"] == "pass"
    assert manifest["public_snapshot"]["status"] == "pass"
    assert str(tmp_path.resolve()) not in json.dumps(manifest)
    assert any(command[:3] == ["git", "archive", "--format=zip"] for command in commands)
