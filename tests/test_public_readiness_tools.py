import json
from pathlib import Path

from reverie_backends import get_backend_profile, list_backend_profiles
from reverie_demo import DEFAULT_PACK_PATH, run_demo
from reverie_doctor import build_environment_report
from reverie_quality import evaluate_quality_gate


def test_backend_profiles_explain_local_setup_choices():
    profiles = {profile["id"]: profile for profile in list_backend_profiles()}

    assert "local_dry_run" in profiles
    assert "local_comfyui_sovits" in profiles
    assert "local_comfyui_supertonic" in profiles

    supertonic = get_backend_profile("local_comfyui_supertonic")
    assert supertonic["tts"]["provider"] == "Supertonic 3"
    assert supertonic["upload"]["default_mode"] == "manual_private_review"
    assert supertonic["safety"]["requires_user_credentials"] is False


def test_environment_report_marks_missing_local_tools_without_calling_services(tmp_path):
    report = build_environment_report(
        repo_root=tmp_path,
        tool_versions={"ffmpeg": None, "node": "v24.0.0", "npm": "11.0.0"},
        service_status={"comfyui": False, "tts": False},
    )

    assert report["overall_status"] == "needs_setup"
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["ffmpeg"]["status"] == "missing"
    assert checks["node"]["status"] == "pass"
    assert checks["comfyui_service"]["status"] == "not_running"
    assert report["safety"]["reads_credentials"] is False
    assert report["safety"]["calls_external_services"] is False


def test_quality_gate_scores_public_demo_without_media_generation():
    pack = json.loads(DEFAULT_PACK_PATH.read_text(encoding="utf-8"))
    result = evaluate_quality_gate(
        pack=pack,
        stages=[
            {"name": "pack_load", "status": "pass"},
            {"name": "story_plan", "status": "pass"},
            {"name": "caption_plan", "status": "pass"},
            {"name": "metadata_gate", "status": "pass"},
            {"name": "upload_gate", "status": "blocked_for_review"},
        ],
        backend_profile=get_backend_profile("local_dry_run"),
        threshold=0.75,
    )

    assert result["status"] == "pass"
    assert result["score"] >= 0.75
    assert result["requires_human_review"] is True
    assert "manual_upload_review" in result["required_reviews"]


def test_public_demo_writes_backend_doctor_and_quality_reports(tmp_path):
    manifest = run_demo(
        DEFAULT_PACK_PATH,
        tmp_path,
        backend_profile_id="local_dry_run",
        quality_threshold=0.75,
    )

    assert manifest["backend_profile"]["id"] == "local_dry_run"
    assert manifest["quality_gate"]["status"] == "pass"
    assert manifest["environment_report"]["overall_status"] in {"pass", "needs_setup"}
    assert any(stage["name"] == "environment_doctor" for stage in manifest["stages"])
    assert any(stage["name"] == "quality_gate" for stage in manifest["stages"])

    assert (tmp_path / "backend_profile.json").exists()
    assert (tmp_path / "environment_report.json").exists()
    assert (tmp_path / "quality_gate.json").exists()


def test_codex_setup_prompt_is_present_for_non_developer_onboarding():
    guide = Path("docs/CODEX_SETUP_PROMPT.md")

    assert guide.exists()
    text = guide.read_text(encoding="utf-8")
    assert "Codex" in text
    assert "python scripts/public_verify.py" in text
    assert "python -m reverie_doctor" in text
    assert "python -m reverie_demo" in text
    assert "do not paste real api keys" in text.lower()


def test_security_and_release_docs_use_public_verify_gate():
    security = Path("SECURITY_PUBLIC_CHECK.md").read_text(encoding="utf-8")
    checklist = Path("PUBLIC_RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/test.yml").read_text(encoding="utf-8")

    assert "python scripts\\public_verify.py --with-pytest --with-functions-audit" in security
    assert "publish_gate.manual_review_items" in checklist
    assert "9 moderate" in security
    assert "scripts/public_verify.py" in workflow
    assert "tests/test_public_verify.py" in workflow


def test_public_demo_docs_include_videotoon_actor_template_output():
    readme = Path("README.md").read_text(encoding="utf-8")
    public_demo = Path("docs/PUBLIC_DEMO.md").read_text(encoding="utf-8")

    assert "video_toon_actor_template.remotion_props.json" in readme
    assert "video_toon_actor_template.remotion_props.json" in public_demo
    assert "video_toon_actor_template.asset_work_order.json" in readme
    assert "asset work order" in public_demo
    assert "storyboard.plan.json" in readme
    assert "metadata.review.json" in public_demo
    assert "mouthCues" in public_demo
