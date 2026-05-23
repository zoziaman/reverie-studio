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
    report_text = report_path.read_text(encoding="utf-8")
    serialized = json.dumps(saved)

    assert saved["pack_id"] == "public_demo"
    assert saved["pack_path"] == "examples/public_demo_pack.json"
    assert any(stage["name"] == "upload_gate" for stage in saved["stages"])
    assert any(stage["status"] == "blocked_for_review" for stage in saved["stages"])
    assert "Output directory: `<public_demo_output>`" in report_text
    assert str(DEFAULT_PACK_PATH.resolve()) not in serialized
    assert str(Path(tmp_path).resolve()) not in report_text


def test_public_demo_writes_named_stage_artifacts(tmp_path):
    run_demo(DEFAULT_PACK_PATH, tmp_path)

    expected_artifacts = {
        "pack.public_demo.json",
        "storyboard.plan.json",
        "placeholder_frames.manifest.json",
        "placeholder_voice.manifest.json",
        "captions.preview.json",
        "render.command.preview.json",
        "metadata.review.json",
        "youtube.private_upload.not_started.json",
    }
    created_names = {path.name for path in Path(tmp_path).iterdir() if path.is_file()}
    storyboard = json.loads((tmp_path / "storyboard.plan.json").read_text(encoding="utf-8"))
    metadata = json.loads((tmp_path / "metadata.review.json").read_text(encoding="utf-8"))
    render_preview = json.loads((tmp_path / "render.command.preview.json").read_text(encoding="utf-8"))

    assert expected_artifacts.issubset(created_names)
    assert storyboard["schema"] == "reverie.public_demo.storyboard_plan.v1"
    assert storyboard["scene_count"] == len(storyboard["scenes"])
    assert metadata["upload_allowed"] is False
    assert metadata["requires_human_review"] is True
    assert render_preview["executes_command"] is False
    assert render_preview["would_use_props"] == "video_toon_actor_template.remotion_props.json"


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


def test_public_demo_writes_videotoon_actor_asset_work_order(tmp_path):
    run_demo(DEFAULT_PACK_PATH, tmp_path)
    work_order_path = tmp_path / "video_toon_actor_template.asset_work_order.json"

    work_order = json.loads(work_order_path.read_text(encoding="utf-8"))
    serialized = json.dumps(work_order)
    targets = {asset["target_relative_path"]: asset for asset in work_order["assets"]}

    assert work_order["schema"] == "reverie.public_demo.videotoon_actor_asset_work_order.v1"
    assert work_order["actor_id"] == "demo_fixed_actor_01"
    assert work_order["asset_count"] == len(work_order["assets"])
    assert work_order["creates_media"] is False
    assert targets["actor_models/demo_fixed_actor_01/variants/talking_standing.png"]["asset_type"] == "variant_base"
    assert targets["actor_models/demo_fixed_actor_01/face_parts/mouth_closed.png"]["asset_type"] == "mouth_layer"
    assert targets["actor_models/demo_fixed_actor_01/face_parts/mouth_small_open.png"]["asset_type"] == "mouth_layer"
    assert targets["actor_models/demo_fixed_actor_01/face_parts/eyes_closed.png"]["asset_type"] == "eye_layer"
    assert targets["backgrounds/demo_neighborhood_day.png"]["asset_type"] == "background_plate"
    assert all(asset["status"] == "needs_local_generation" for asset in work_order["assets"])
    assert all(asset["public_safe"] is True for asset in work_order["assets"])
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
