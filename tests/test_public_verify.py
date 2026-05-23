import json
from pathlib import Path

import pytest

import reverie_public_verify as public_verify


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
    assert report["checks"]["pytest"]["status"] == "not_run"
    written = json.loads((tmp_path / "public_verify_report.json").read_text(encoding="utf-8"))
    assert written["schema"] == "reverie.public_verify.v1"


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
    assert report["checks"]["public_snapshot"]["finding_count"] == 1
    assert "public_snapshot_check" in report["failures"][0]


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
