import json
import importlib.util
import hashlib
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
    assert manifest["archive_integrity"] == {
        "status": "pass",
        "contains_git_metadata": False,
        "contains_unsafe_paths": False,
        "count_matches_tracked_files": True,
    }
    assert manifest["release_guidance"] == {
        "distribution_path": "history_free_export",
        "use_archive_for_public_distribution": True,
        "existing_repo_history_included": False,
        "existing_repo_history_requires_review": True,
        "next_actions": [
            "Distribute the generated source archive, not the private-history checkout.",
            "Run public_verify.py with --with-history-scan before publishing existing repository history.",
        ],
    }
    assert manifest["workspace_state"]["status"] == "pass"
    assert manifest["public_snapshot"]["status"] == "pass"
    assert str(tmp_path.resolve()) not in json.dumps(manifest)
    assert any(command[:3] == ["git", "archive", "--format=zip"] for command in commands)


def test_public_export_blocks_archive_integrity_failures(tmp_path, monkeypatch):
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
        archive_path = Path(command[4])
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("README.md", "# demo\n")
            archive.writestr(".git/config", "[core]\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(public_export, "_load_public_snapshot_check", lambda: SnapshotCheck())
    monkeypatch.setattr(public_export, "_git_stdout", fake_git)
    monkeypatch.setattr(public_export.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="archive integrity check failed"):
        public_export.create_public_export(tmp_path)

    assert not (tmp_path / "public_export_manifest.json").exists()


def test_public_export_manifest_records_archive_sha256(tmp_path, monkeypatch):
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
        if args == ["rev-parse", "HEAD"]:
            return "abc123\n"
        if args == ["rev-parse", "HEAD^{tree}"]:
            return "def456\n"
        if args == ["ls-files"]:
            return "README.md\n"
        if args == ["status", "--porcelain=v1", "--untracked-files=normal"]:
            return ""
        raise AssertionError(args)

    def fake_run(command, **kwargs):
        archive_path = Path(command[4])
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("README.md", "# demo\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(public_export, "_load_public_snapshot_check", lambda: SnapshotCheck())
    monkeypatch.setattr(public_export, "_git_stdout", fake_git)
    monkeypatch.setattr(public_export.subprocess, "run", fake_run)

    manifest = public_export.create_public_export(tmp_path)
    archive_bytes = (tmp_path / "reverie-public-snapshot.zip").read_bytes()

    assert manifest["archive_sha256"] == hashlib.sha256(archive_bytes).hexdigest()


def test_public_export_verify_passes_for_matching_archive(tmp_path):
    archive_path = tmp_path / "reverie-public-snapshot.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("README.md", "# demo\n")
    manifest = {
        "schema": "reverie.public_export.v1",
        "archive_path": "reverie-public-snapshot.zip",
        "manifest_path": "public_export_manifest.json",
        "tracked_file_count": 1,
        "archive_file_count": 1,
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "archive_integrity": {
            "status": "pass",
            "contains_git_metadata": False,
            "contains_unsafe_paths": False,
            "count_matches_tracked_files": True,
        },
        "release_guidance": {
            "distribution_path": "history_free_export",
            "use_archive_for_public_distribution": True,
            "existing_repo_history_included": False,
            "existing_repo_history_requires_review": True,
            "next_actions": [
                "Distribute the generated source archive, not the private-history checkout.",
                "Run public_verify.py with --with-history-scan before publishing existing repository history.",
            ],
        },
        "git_history_included": False,
        "workspace_state": {"status": "pass", "dirty_count": 0},
        "public_snapshot": {"status": "pass", "finding_count": 0},
    }
    (tmp_path / "public_export_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = public_export.verify_public_export(tmp_path)

    assert report["schema"] == "reverie.public_export.verify.v1"
    assert report["status"] == "pass"
    assert report["archive_path"] == "reverie-public-snapshot.zip"
    assert report["checks"]["archive_sha256"]["status"] == "pass"
    assert report["checks"]["archive_integrity"]["status"] == "pass"
    assert report["checks"]["release_guidance"]["status"] == "pass"
    assert report["checks"]["release_guidance"]["expected_distribution_path"] == "history_free_export"
    assert report["checks"]["release_guidance"]["actual_distribution_path"] == "history_free_export"
    assert report["checks"]["release_guidance"]["expected_existing_repo_history_requires_review"] is True
    assert report["checks"]["release_guidance"]["actual_existing_repo_history_requires_review"] is True
    assert str(tmp_path.resolve()) not in json.dumps(report)


def test_public_export_verify_fails_without_release_guidance(tmp_path):
    archive_path = tmp_path / "reverie-public-snapshot.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("README.md", "# demo\n")
    manifest = {
        "schema": "reverie.public_export.v1",
        "archive_path": "reverie-public-snapshot.zip",
        "manifest_path": "public_export_manifest.json",
        "tracked_file_count": 1,
        "archive_file_count": 1,
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "archive_integrity": {
            "status": "pass",
            "contains_git_metadata": False,
            "contains_unsafe_paths": False,
            "count_matches_tracked_files": True,
        },
        "git_history_included": False,
        "workspace_state": {"status": "pass", "dirty_count": 0},
        "public_snapshot": {"status": "pass", "finding_count": 0},
    }
    (tmp_path / "public_export_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = public_export.verify_public_export(tmp_path)

    assert report["status"] == "fail"
    assert report["checks"]["release_guidance"]["status"] == "fail"
    assert report["checks"]["release_guidance"]["expected_distribution_path"] == "history_free_export"
    assert report["checks"]["release_guidance"]["actual_distribution_path"] == "missing"
    assert report["checks"]["release_guidance"]["expected_existing_repo_history_requires_review"] is True
    assert report["checks"]["release_guidance"]["actual_existing_repo_history_requires_review"] == "missing"


def test_public_export_verify_summarizes_unexpected_release_guidance_without_echoing_raw_values(tmp_path):
    archive_path = tmp_path / "reverie-public-snapshot.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("README.md", "# demo\n")
    manifest = {
        "schema": "reverie.public_export.v1",
        "archive_path": "reverie-public-snapshot.zip",
        "manifest_path": "public_export_manifest.json",
        "tracked_file_count": 1,
        "archive_file_count": 1,
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "archive_integrity": {
            "status": "pass",
            "contains_git_metadata": False,
            "contains_unsafe_paths": False,
            "count_matches_tracked_files": True,
        },
        "release_guidance": {
            "distribution_path": "C:/Users/private/checkouts",
            "existing_repo_history_requires_review": "publish everything",
        },
        "git_history_included": False,
        "workspace_state": {"status": "pass", "dirty_count": 0},
        "public_snapshot": {"status": "pass", "finding_count": 0},
    }
    (tmp_path / "public_export_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = public_export.verify_public_export(tmp_path)
    serialized = json.dumps(report)

    assert report["status"] == "fail"
    assert report["checks"]["release_guidance"]["actual_distribution_path"] == "unexpected"
    assert report["checks"]["release_guidance"]["actual_existing_repo_history_requires_review"] == "unexpected"
    assert "C:/Users/private/checkouts" not in serialized
    assert "publish everything" not in serialized


def test_public_export_verify_fails_for_checksum_mismatch(tmp_path):
    archive_path = tmp_path / "reverie-public-snapshot.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("README.md", "# demo\n")
    manifest = {
        "schema": "reverie.public_export.v1",
        "archive_path": "reverie-public-snapshot.zip",
        "manifest_path": "public_export_manifest.json",
        "tracked_file_count": 1,
        "archive_file_count": 1,
        "archive_sha256": "0" * 64,
        "archive_integrity": {
            "status": "pass",
            "contains_git_metadata": False,
            "contains_unsafe_paths": False,
            "count_matches_tracked_files": True,
        },
        "git_history_included": False,
        "workspace_state": {"status": "pass", "dirty_count": 0},
        "public_snapshot": {"status": "pass", "finding_count": 0},
    }
    (tmp_path / "public_export_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = public_export.verify_public_export(tmp_path)

    assert report["status"] == "fail"
    assert report["checks"]["archive_sha256"]["status"] == "fail"
    assert report["checks"]["archive_sha256"]["expected"] == "0" * 64
    assert report["checks"]["archive_sha256"]["actual"] != "0" * 64


def test_public_export_cli_prints_release_guidance_for_created_export(tmp_path, monkeypatch, capsys):
    def fake_create_public_export(output_dir, allow_repo_output=False):
        return {
            "schema": "reverie.public_export.v1",
            "archive_path": "reverie-public-snapshot.zip",
            "manifest_path": "public_export_manifest.json",
            "archive_file_count": 2,
            "archive_sha256": "1" * 64,
            "release_guidance": public_export.RELEASE_GUIDANCE,
            "git_history_included": False,
        }

    monkeypatch.setattr(public_export, "create_public_export", fake_create_public_export)

    exit_code = public_export.main(["--out", str(tmp_path)])

    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert "Release guidance:" in stdout
    assert "distribution_path: history_free_export" in stdout
    assert "existing_repo_history_requires_review: true" in stdout
    assert "git_history_included: false" in stdout


def test_public_export_verify_cli_prints_release_guidance_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        public_export,
        "verify_public_export",
        lambda output_dir: {
            "schema": "reverie.public_export.verify.v1",
            "status": "pass",
            "archive_path": "reverie-public-snapshot.zip",
            "manifest_path": "public_export_manifest.json",
            "release_guidance": public_export.RELEASE_GUIDANCE,
            "checks": {
                "release_guidance": {"status": "pass"},
                "git_history_included": {"status": "pass"},
            },
        },
    )

    exit_code = public_export.main(["--verify", "--out", str(tmp_path)])

    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert "Release guidance:" in stdout
    assert "distribution_path: history_free_export" in stdout
    assert "release_guidance check: pass" in stdout
    assert "git_history_included check: pass" in stdout
