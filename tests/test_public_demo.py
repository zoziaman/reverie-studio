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


def test_public_demo_writes_videotoon_actor_template_props(tmp_path):
    manifest = run_demo(DEFAULT_PACK_PATH, tmp_path)
    props_path = tmp_path / "video_toon_actor_template.remotion_props.json"

    props = json.loads(props_path.read_text(encoding="utf-8"))
    image = props["images"][0]
    serialized = json.dumps(props)

    assert any(stage["name"] == "videotoon_actor_template" for stage in manifest["stages"])
    assert props["schema"] == "reverie.remotion.radio_drama_props.v1"
    assert props["motiontoon"]["mode"] == "layered_actor_pool_v1"
    assert props["motiontoon"]["renderPlan"]["schema"] == "reverie.pack.videotoon_render_plan.v1"
    assert image["foregroundPath"] == "actor_models/demo_fixed_actor_01/variants/talking_standing.png"
    assert image["eyesClosedPath"] == "actor_models/demo_fixed_actor_01/face_parts/eyes_closed.png"
    assert image["mouthClosedPath"] == "actor_models/demo_fixed_actor_01/face_parts/mouth_closed.png"
    assert image["mouthOpenPath"] == "actor_models/demo_fixed_actor_01/face_parts/mouth_small_open.png"
    assert image["mouthCues"][:2] == [{"frame": 0, "mouth": 0}, {"frame": 4, "mouth": 1}]
    assert image["motion"]["face_rig"] is True
    assert props["public_release_boundary"]["contains_generated_media"] is False
    assert "C:" + "/Users/" not in serialized
    assert "C:" + "\\Users\\" not in serialized


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
