import json
from pathlib import Path

from reverie_demo import DEFAULT_PACK_PATH, run_demo


def test_public_demo_writes_safe_report_files(tmp_path):
    manifest = run_demo(DEFAULT_PACK_PATH, tmp_path)

    assert manifest["mode"] == "dry_run"
    assert manifest["final_status"] == "needs_human_review"
    assert manifest["safety"] == {
        "uses_credentials": False,
        "calls_external_services": False,
        "creates_media": False,
        "starts_upload": False,
    }

    manifest_path = tmp_path / "run_manifest.json"
    log_path = tmp_path / "stage_log.jsonl"
    report_path = tmp_path / "pipeline_report.md"

    assert manifest_path.exists()
    assert log_path.exists()
    assert report_path.exists()

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["pack_id"] == "public_demo"
    assert any(stage["name"] == "upload_gate" for stage in saved["stages"])
    assert any(stage["status"] == "blocked_for_review" for stage in saved["stages"])


def test_public_demo_does_not_create_media_or_secret_files(tmp_path):
    run_demo(DEFAULT_PACK_PATH, tmp_path)

    blocked_suffixes = {
        ".mp4",
        ".mov",
        ".avi",
        ".wav",
        ".mp3",
        ".flac",
        ".ogg",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".pickle",
        ".pkl",
        ".db",
        ".sqlite",
    }
    blocked_names = {".env", "credentials.json", "token.pickle", "firebase_credentials.json"}

    created_files = [path for path in Path(tmp_path).rglob("*") if path.is_file()]
    assert created_files
    assert all(path.suffix.lower() not in blocked_suffixes for path in created_files)
    assert all(path.name.lower() not in blocked_names for path in created_files)
