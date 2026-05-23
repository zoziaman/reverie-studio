import json
from pathlib import Path

import pytest

import reverie_public_verify as public_verify


@pytest.fixture(autouse=True)
def _default_machine_checks_pass(monkeypatch, request):
    monkeypatch.setattr(
        public_verify,
        "_run_python_compile",
        lambda timeout_seconds=60: {
            "status": "pass",
            "command": ["python", "-m", "compileall", "-q", "src", "scripts"],
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
        },
        raising=False,
    )
    if request.node.name == "test_workspace_state_does_not_report_raw_local_paths":
        return
    monkeypatch.setattr(
        public_verify,
        "_run_workspace_state",
        lambda: {
            "status": "pass",
            "command": ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
            "returncode": 0,
            "dirty_count": 0,
            "status_counts": {},
            "changed_path_fingerprints": [],
            "truncated_changed_path_fingerprints": 0,
        },
        raising=False,
    )


def _safe_demo_manifest() -> dict:
    return {
        "final_status": "needs_human_review",
        "quality_gate": {"status": "pass"},
        "safety": {
            "uses_credentials": False,
            "calls_external_services": False,
            "creates_media": False,
            "starts_upload": False,
        },
    }


def test_public_verify_writes_public_safe_report(tmp_path, monkeypatch):
    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: type("S", (), {"run_check": lambda self, root: []})())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())

    report = public_verify.run_public_verification(tmp_path)

    assert report["overall_status"] == "pass"
    assert report["checks"]["public_snapshot"]["schema"] == "reverie.public_snapshot_check.v1"
    assert report["checks"]["public_snapshot"]["status"] == "pass"
    assert report["checks"]["workspace_state"]["status"] == "pass"
    assert report["checks"]["python_compile"]["status"] == "pass"
    assert report["checks"]["pytest"]["status"] == "not_run"
    assert report["checks"]["public_export"]["status"] == "not_run"
    assert report["checks"]["functions_syntax"]["status"] == "not_run"
    assert report["publish_gate"]["status"] == "review_required"
    check_ids = {check["id"] for check in report["publish_gate"]["machine_checks"]}
    assert "workspace_state" in check_ids
    assert "history_free_public_export" in check_ids
    assert "firebase_functions_syntax" in check_ids
    review_ids = {item["id"] for item in report["publish_gate"]["manual_review_items"]}
    assert "existing_git_history" in review_ids
    assert "firebase_functions_dependency_audit" in review_ids
    functions_review = [
        item for item in report["publish_gate"]["manual_review_items"]
        if item["id"] == "firebase_functions_dependency_audit"
    ][0]
    assert "--with-functions-audit" in functions_review["evidence"]
    assert "9 moderate" not in functions_review["evidence"]
    written = json.loads((tmp_path / "public_verify_report.json").read_text(encoding="utf-8"))
    assert written["schema"] == "reverie.public_verify.v1"
    summary = (tmp_path / "public_verify_summary.md").read_text(encoding="utf-8")
    assert "Overall status: `pass`" in summary
    assert "Publish gate: `review_required`" in summary
    assert "Manual Review Before Publishing" in summary
    assert "public_demo/pipeline_report.md" in summary


def test_public_verify_fails_on_snapshot_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(
        public_verify,
        "_load_public_snapshot_check",
        lambda: type("S", (), {"run_check": lambda self, root: ["config/client_secret_alice.json: blocked filename pattern: client_secret_alice.json"]})(),
    )
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())

    report = public_verify.run_public_verification(tmp_path)

    assert report["overall_status"] == "fail"
    assert report["publish_gate"]["status"] == "blocked"
    assert report["checks"]["public_snapshot"]["schema"] == "reverie.public_snapshot_check.v1"
    assert report["checks"]["public_snapshot"]["status"] == "fail"
    assert report["checks"]["public_snapshot"]["finding_count"] == 1
    assert report["checks"]["public_snapshot"]["finding_types"] == {
        "blocked filename pattern": 1,
    }
    assert report["checks"]["public_snapshot"]["finding_fingerprints"][0]["fingerprint"]
    assert "public_snapshot_check" in report["failures"][0]
    serialized = json.dumps(report)
    assert "client_secret_alice.json" not in serialized


def test_public_verify_can_include_history_filename_scan(tmp_path, monkeypatch):
    class SnapshotCheck:
        def run_check(self, root):
            return []

        def run_history_filename_check(self, root):
            return []

        def build_json_report(self, findings):
            return {
                "schema": "reverie.public_snapshot_check.v1",
                "status": "fail" if findings else "pass",
                "finding_count": len(findings),
                "finding_types": {},
                "finding_fingerprints": [],
                "truncated_finding_fingerprints": 0,
            }

    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: SnapshotCheck())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())

    report = public_verify.run_public_verification(tmp_path, with_history_scan=True)

    assert report["overall_status"] == "pass"
    assert report["checks"]["git_history_filenames"]["schema"] == "reverie.public_history_filename_check.v1"
    assert report["checks"]["git_history_filenames"]["status"] == "pass"
    history_check = [
        check for check in report["publish_gate"]["machine_checks"]
        if check["id"] == "git_history_filenames"
    ][0]
    assert history_check["status"] == "pass"
    assert "finding_count=0" in history_check["evidence"]


def test_public_verify_blocks_on_history_filename_findings(tmp_path, monkeypatch):
    class SnapshotCheck:
        def run_check(self, root):
            return []

        def run_history_filename_check(self, root):
            return ["config/client_secret_alice.json: historical blocked filename pattern: client_secret_alice.json"]

        def build_json_report(self, findings):
            return {
                "schema": "reverie.public_snapshot_check.v1",
                "status": "fail" if findings else "pass",
                "finding_count": len(findings),
                "finding_types": {"historical blocked filename pattern": len(findings)},
                "finding_fingerprints": [{"reason": "historical blocked filename pattern", "fingerprint": "abc123"}],
                "truncated_finding_fingerprints": 0,
            }

    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: SnapshotCheck())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())

    report = public_verify.run_public_verification(tmp_path, with_history_scan=True)

    assert report["overall_status"] == "fail"
    assert report["publish_gate"]["status"] == "blocked"
    assert report["checks"]["git_history_filenames"]["status"] == "fail"
    assert report["checks"]["git_history_filenames"]["finding_count"] == 1
    assert "git history filename scan" in report["failures"][0]
    serialized = json.dumps(report)
    assert "client_secret_alice.json" not in serialized


def test_public_verify_summary_explains_history_block_release_options(tmp_path, monkeypatch):
    class SnapshotCheck:
        def run_check(self, root):
            return []

        def run_history_filename_check(self, root):
            return ["private/data.wav: historical blocked extension: .wav"]

        def build_json_report(self, findings):
            return {
                "schema": "reverie.public_snapshot_check.v1",
                "status": "fail" if findings else "pass",
                "finding_count": len(findings),
                "finding_types": {"historical blocked extension": len(findings)},
                "finding_fingerprints": [{"reason": "historical blocked extension", "fingerprint": "abc123"}],
                "truncated_finding_fingerprints": 0,
            }

    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: SnapshotCheck())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())

    report = public_verify.run_public_verification(tmp_path, with_history_scan=True)

    summary = (tmp_path / "public_verify_summary.md").read_text(encoding="utf-8")
    release_options = report["publish_gate"]["release_options"]

    assert report["publish_gate"]["status"] == "blocked"
    assert any(option["id"] == "history_free_export" for option in release_options)
    assert any(option["id"] == "existing_repo_history" for option in release_options)
    assert "Public Release Options" in summary
    assert "history-free public export" in summary
    assert "Do not make the existing repository public" in summary


def test_public_verify_fails_on_python_compile_error(tmp_path, monkeypatch):
    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: type("S", (), {"run_check": lambda self, root: []})())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())
    monkeypatch.setattr(
        public_verify,
        "_run_python_compile",
        lambda timeout_seconds=60: {
            "status": "fail",
            "command": ["python", "-m", "compileall", "-q", "src", "scripts"],
            "returncode": 1,
            "stdout_tail": "",
            "stderr_tail": "SyntaxError: invalid syntax",
        },
    )

    report = public_verify.run_public_verification(tmp_path)

    assert report["overall_status"] == "fail"
    assert report["publish_gate"]["status"] == "blocked"
    assert report["checks"]["python_compile"]["status"] == "fail"
    assert any("python_compile failed" in failure for failure in report["failures"])


def test_public_verify_reports_dirty_workspace_for_release_review(tmp_path, monkeypatch):
    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: type("S", (), {"run_check": lambda self, root: []})())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())
    monkeypatch.setattr(
        public_verify,
        "_run_workspace_state",
        lambda: {
            "status": "review_required",
            "command": ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
            "returncode": 0,
            "dirty_count": 2,
            "status_counts": {"M": 1, "??": 1},
            "changed_path_fingerprints": [
                {"status": "M", "fingerprint": "abc123"},
                {"status": "??", "fingerprint": "def456"},
            ],
            "truncated_changed_path_fingerprints": 0,
        },
    )

    report = public_verify.run_public_verification(tmp_path)

    assert report["overall_status"] == "pass"
    assert report["checks"]["workspace_state"]["status"] == "review_required"
    workspace_check = [
        check for check in report["publish_gate"]["machine_checks"]
        if check["id"] == "workspace_state"
    ][0]
    assert workspace_check["status"] == "review_required"
    assert "dirty_count=2" in workspace_check["evidence"]
    summary = (tmp_path / "public_verify_summary.md").read_text(encoding="utf-8")
    assert "`workspace_state`: `review_required`" in summary


def test_workspace_state_does_not_report_raw_local_paths(monkeypatch):
    class Completed:
        returncode = 0
        stdout = "?? C:/Users/alice/local.secret\n M docs/PUBLIC_DEMO.md\n"
        stderr = ""

    monkeypatch.setattr(public_verify.subprocess, "run", lambda *args, **kwargs: Completed())

    report = public_verify._run_workspace_state()
    serialized = json.dumps(report)

    assert report["status"] == "review_required"
    assert report["dirty_count"] == 2
    assert report["status_counts"] == {"??": 1, "M": 1}
    assert "changed_paths" not in report
    assert report["changed_path_fingerprints"][0]["fingerprint"]
    assert "local.secret" not in serialized
    assert "C:/Users/alice" not in serialized
    assert "docs/PUBLIC_DEMO.md" not in serialized


def test_public_verify_report_does_not_include_raw_local_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: type("S", (), {"run_check": lambda self, root: []})())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())

    report = public_verify.run_public_verification(tmp_path)
    written = json.loads((tmp_path / "public_verify_report.json").read_text(encoding="utf-8"))
    serialized = json.dumps(written)

    assert report["repo_root"] == "<repo_root>"
    assert report["output_dir"] == "<verification_output>"
    assert report["checks"]["environment_doctor"]["report_path"] == "public_demo/environment_report.json"
    assert report["checks"]["public_demo"]["report_path"] == "public_demo/run_manifest.json"
    assert str(public_verify.REPO_ROOT.resolve()) not in serialized
    assert str(tmp_path.resolve()) not in serialized


def test_public_verify_refuses_repo_output_by_default():
    repo_output = public_verify.REPO_ROOT / "tmp-public-verify"

    with pytest.raises(ValueError, match="outside the repository"):
        public_verify.run_public_verification(repo_output)


def test_public_verify_can_run_pytest_when_requested(tmp_path, monkeypatch):
    class Completed:
        returncode = 0
        stdout = "1 passed"
        stderr = ""

    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: type("S", (), {"run_check": lambda self, root: []})())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())
    monkeypatch.setattr(public_verify.subprocess, "run", lambda *args, **kwargs: Completed())

    report = public_verify.run_public_verification(
        tmp_path,
        with_pytest=True,
        pytest_args=["tests/test_public_verify.py", "-q"],
    )

    assert report["overall_status"] == "pass"
    assert report["checks"]["pytest"]["status"] == "pass"
    assert report["checks"]["pytest"]["stdout_tail"] == "1 passed"


def test_public_verify_can_include_functions_audit(tmp_path, monkeypatch):
    captured_commands = []
    functions_dir = tmp_path / "functions"
    functions_dir.mkdir()
    (functions_dir / "package-lock.json").write_text(
        json.dumps({
            "packages": {
                "": {
                    "dependencies": {
                        "firebase-admin": "^13.6.0",
                        "firebase-functions": "^7.0.0",
                    }
                },
                "node_modules/firebase-admin": {"version": "13.10.0"},
                "node_modules/firebase-functions": {"version": "7.2.5"},
            }
        }),
        encoding="utf-8",
    )

    class Completed:
        returncode = 1
        stdout = json.dumps({
            "metadata": {
                "vulnerabilities": {
                    "info": 0,
                    "low": 0,
                    "moderate": 9,
                    "high": 0,
                    "critical": 0,
                    "total": 9,
                }
            },
            "vulnerabilities": {
                "firebase-admin": {
                    "severity": "moderate",
                    "fixAvailable": {
                        "name": "firebase-admin",
                        "version": "10.3.0",
                        "isSemVerMajor": True,
                    },
                },
                "uuid": {
                    "severity": "moderate",
                    "fixAvailable": {
                        "name": "firebase-admin",
                        "version": "10.3.0",
                        "isSemVerMajor": True,
                    },
                },
                "firebase-functions": {
                    "severity": "moderate",
                    "fixAvailable": {
                        "name": "firebase-functions",
                        "version": "4.9.0",
                        "isSemVerMajor": True,
                    },
                },
                "gaxios": {
                    "severity": "moderate",
                    "fixAvailable": True,
                },
            },
        })
        stderr = ""

    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: type("S", (), {"run_check": lambda self, root: []})())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())
    monkeypatch.setattr(public_verify.shutil, "which", lambda command: "npm")
    monkeypatch.setattr(public_verify, "FUNCTIONS_DIR", functions_dir)

    def fake_run(command, *args, **kwargs):
        captured_commands.append(command)
        return Completed()

    monkeypatch.setattr(public_verify.subprocess, "run", fake_run)

    report = public_verify.run_public_verification(tmp_path, with_functions_audit=True)

    assert "--package-lock-only" in captured_commands[0]
    assert report["overall_status"] == "pass"
    assert report["publish_gate"]["status"] == "review_required"
    assert report["checks"]["functions_audit"]["status"] == "review_required"
    assert report["checks"]["functions_audit"]["vulnerabilities"]["moderate"] == 9
    assert report["checks"]["functions_audit"]["fix_advice"] == {
        "direct_fix_count": 1,
        "force_fix_required": True,
        "force_fix_targets": ["firebase-admin@10.3.0", "firebase-functions@4.9.0"],
    }
    assert report["checks"]["functions_audit"]["direct_dependency_versions"] == {
        "firebase-admin": {"declared": "^13.6.0", "installed": "13.10.0"},
        "firebase-functions": {"declared": "^7.0.0", "installed": "7.2.5"},
    }
    assert report["checks"]["functions_audit"]["command"] == [
        "npm",
        "--prefix",
        "functions",
        "audit",
        "--package-lock-only",
        "--omit=dev",
        "--json",
    ]
    assert "stdout_tail" not in report["checks"]["functions_audit"]
    assert "stderr_tail" not in report["checks"]["functions_audit"]
    assert str(public_verify.FUNCTIONS_DIR) not in json.dumps(report["checks"]["functions_audit"])
    summary = (tmp_path / "public_verify_summary.md").read_text(encoding="utf-8")
    assert "Optional Functions Audit" in summary
    assert "Moderate: `9`" in summary
    assert "Force-fix targets: `firebase-admin@10.3.0, firebase-functions@4.9.0`" in summary
    assert (
        "Direct dependency versions: `firebase-admin ^13.6.0 -> 13.10.0, "
        "firebase-functions ^7.0.0 -> 7.2.5`"
    ) in summary
    functions_check = [
        check for check in report["publish_gate"]["machine_checks"]
        if check["id"] == "firebase_functions_dependency_audit"
    ][0]
    assert "total=9" in functions_check["evidence"]
    assert "force_fix_required=true" in functions_check["evidence"]
    assert "direct_dependency_versions=firebase-admin:^13.6.0->13.10.0|firebase-functions:^7.0.0->7.2.5" in functions_check["evidence"]


def test_public_verify_can_include_functions_syntax(tmp_path, monkeypatch):
    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: type("S", (), {"run_check": lambda self, root: []})())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())
    monkeypatch.setattr(
        public_verify,
        "_run_functions_syntax_check",
        lambda timeout_seconds: {
            "status": "pass",
            "command": ["node", "-e", "require('./functions/index.js')"],
            "returncode": 0,
            "detail": "functions module loaded",
        },
    )

    report = public_verify.run_public_verification(tmp_path, with_functions_syntax=True)

    assert report["overall_status"] == "pass"
    assert report["checks"]["functions_syntax"]["status"] == "pass"
    syntax_check = [
        check for check in report["publish_gate"]["machine_checks"]
        if check["id"] == "firebase_functions_syntax"
    ][0]
    assert syntax_check["status"] == "pass"
    assert "loaded with node" in syntax_check["evidence"]
    summary = (tmp_path / "public_verify_summary.md").read_text(encoding="utf-8")
    assert "Optional Functions Syntax" in summary
    assert "functions module loaded" in summary


def test_public_verify_blocks_when_functions_syntax_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: type("S", (), {"run_check": lambda self, root: []})())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())
    monkeypatch.setattr(
        public_verify,
        "_run_functions_syntax_check",
        lambda timeout_seconds: {
            "status": "fail",
            "command": ["node", "-e", "require('./functions/index.js')"],
            "returncode": 1,
            "detail": "functions module did not load",
        },
    )

    report = public_verify.run_public_verification(tmp_path, with_functions_syntax=True)

    assert report["overall_status"] == "fail"
    assert report["publish_gate"]["status"] == "blocked"
    assert report["checks"]["functions_syntax"]["status"] == "fail"
    assert "Firebase Functions module did not load" in report["failures"]


def test_public_verify_can_include_public_export(tmp_path, monkeypatch):
    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: type("S", (), {"run_check": lambda self, root: []})())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())
    monkeypatch.setattr(
        public_verify,
        "_run_public_export",
        lambda out, allow_repo_output=False: {
            "status": "pass",
            "archive_path": "public_export/reverie-public-snapshot.zip",
            "manifest_path": "public_export/public_export_manifest.json",
            "manifest": {
                "schema": "reverie.public_export.v1",
                "source_commit": "abc123",
                "source_tree": "def456",
                "tracked_file_count": 2,
                "archive_file_count": 2,
                "archive_sha256": "1" * 64,
                "archive_integrity": {"status": "pass"},
                "git_history_included": False,
                "workspace_state": {"status": "pass", "dirty_count": 0},
                "public_snapshot": {"status": "pass", "finding_count": 0},
            },
            "verify": {"status": "pass"},
        },
    )

    report = public_verify.run_public_verification(tmp_path, with_public_export=True)

    assert report["overall_status"] == "pass"
    assert report["checks"]["public_export"]["status"] == "pass"
    assert report["checks"]["public_export"]["archive_path"] == "public_export/reverie-public-snapshot.zip"
    assert report["checks"]["public_export"]["manifest"]["git_history_included"] is False
    assert str(tmp_path.resolve()) not in json.dumps(report["checks"]["public_export"])
    export_check = [
        check for check in report["publish_gate"]["machine_checks"]
        if check["id"] == "history_free_public_export"
    ][0]
    assert export_check["status"] == "pass"
    assert "verify_status=pass" in export_check["evidence"]
    summary = (tmp_path / "public_verify_summary.md").read_text(encoding="utf-8")
    assert "Optional Public Export" in summary
    assert "public_export/reverie-public-snapshot.zip" in summary


def test_public_verify_blocks_when_public_export_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(public_verify, "_load_public_snapshot_check", lambda: type("S", (), {"run_check": lambda self, root: []})())
    monkeypatch.setattr(
        public_verify,
        "build_environment_report",
        lambda root: {"overall_status": "pass", "checks": [], "safety": {}},
    )
    monkeypatch.setattr(public_verify, "run_demo", lambda *args, **kwargs: _safe_demo_manifest())
    monkeypatch.setattr(
        public_verify,
        "_run_public_export",
        lambda out, allow_repo_output=False: {
            "status": "fail",
            "error_type": "RuntimeError",
            "detail": "workspace is not clean; refusing to create export archive from HEAD",
        },
    )

    report = public_verify.run_public_verification(tmp_path, with_public_export=True)

    assert report["overall_status"] == "fail"
    assert report["publish_gate"]["status"] == "blocked"
    assert report["checks"]["public_export"]["status"] == "fail"
    assert any("history-free public export" in failure for failure in report["failures"])
    export_check = [
        check for check in report["publish_gate"]["machine_checks"]
        if check["id"] == "history_free_public_export"
    ][0]
    assert export_check["status"] == "fail"
