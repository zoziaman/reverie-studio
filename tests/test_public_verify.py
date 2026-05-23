import json
from pathlib import Path

import pytest

import reverie_public_verify as public_verify


@pytest.fixture(autouse=True)
def _python_compile_passes(monkeypatch):
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
    monkeypatch.setattr(
        public_verify,
        "_run_workspace_state",
        lambda: {
            "status": "pass",
            "command": ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
            "returncode": 0,
            "dirty_count": 0,
            "changed_paths": [],
            "truncated_changed_paths": 0,
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
    assert report["checks"]["public_snapshot"]["status"] == "pass"
    assert report["checks"]["workspace_state"]["status"] == "pass"
    assert report["checks"]["python_compile"]["status"] == "pass"
    assert report["checks"]["pytest"]["status"] == "not_run"
    assert report["publish_gate"]["status"] == "review_required"
    check_ids = {check["id"] for check in report["publish_gate"]["machine_checks"]}
    assert "workspace_state" in check_ids
    review_ids = {item["id"] for item in report["publish_gate"]["manual_review_items"]}
    assert "existing_git_history" in review_ids
    assert "firebase_functions_dependency_audit" in review_ids
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
        lambda: type("S", (), {"run_check": lambda self, root: ["secret.txt: blocked filename"]})(),
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
    assert report["checks"]["public_snapshot"]["finding_count"] == 1
    assert "public_snapshot_check" in report["failures"][0]


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
            "changed_paths": ["M README.md", "?? local.secret"],
            "truncated_changed_paths": 0,
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
    summary = (tmp_path / "public_verify_summary.md").read_text(encoding="utf-8")
    assert "Optional Functions Audit" in summary
    assert "Moderate: `9`" in summary
    assert "Force-fix targets: `firebase-admin@10.3.0, firebase-functions@4.9.0`" in summary
    functions_check = [
        check for check in report["publish_gate"]["machine_checks"]
        if check["id"] == "firebase_functions_dependency_audit"
    ][0]
    assert "total=9" in functions_check["evidence"]
    assert "force_fix_required=true" in functions_check["evidence"]
