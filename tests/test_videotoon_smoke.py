import importlib
import json
import tomllib
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"


def _smoke_module():
    return importlib.import_module("utils.videotoon_smoke")


def test_local_videotoon_smoke_bundle_creates_ready_render_inputs(tmp_path):
    smoke = _smoke_module()
    output_dir = tmp_path / "smoke"

    manifest = smoke.write_local_videotoon_smoke_bundle(
        output_dir,
        source_repo_root=ROOT,
        fps=30,
        duration_seconds=10,
    )

    actor_png = output_dir / "actor_models" / "actor_adult_woman_01" / "variants" / "happy_standing.png"
    background_png = output_dir / "backgrounds" / "daily_life_toon" / "street_day_00.png"
    prepare_path = output_dir / "prepare" / "daily_life_toon_ep001.prepare_report.json"
    render_plan_path = output_dir / "prepare" / "daily_life_toon_ep001.render_plan.json"
    props_path = output_dir / "prepare" / "daily_life_toon_ep001.remotion_props.json"

    prepare = json.loads(prepare_path.read_text(encoding="utf-8"))
    render_plan = json.loads(render_plan_path.read_text(encoding="utf-8"))
    props = json.loads(props_path.read_text(encoding="utf-8"))
    serialized_manifest = json.dumps(manifest)

    assert manifest["schema"] == "reverie.local.videotoon_smoke_bundle.v1"
    assert manifest["pack_id"] == "daily_life_toon"
    assert manifest["episode_id"] == "daily_life_toon_ep001"
    assert manifest["ready_for_render"] is True
    assert manifest["creates_media"] is True
    assert manifest["calls_external_services"] is False
    assert manifest["duration_seconds"] == 10
    assert manifest["total_frames"] == 300
    assert manifest["actor_sample_assets"]["created_count"] == 18
    assert manifest["background_sample_assets"]["asset_count"] == 1
    assert prepare["ready_for_render"] is True
    assert prepare["missing_count"] == 0
    assert render_plan["ready_for_render"] is True
    assert props["schema"] == "reverie.remotion.radio_drama_props.v1"
    assert props["totalFrames"] == 300
    assert props["images"][0]["foregroundPath"] == "variants/happy_standing.png"
    assert props["images"][0]["backgroundPath"] == "street_day_00.png"
    assert props["images"][0]["mouthCues"][-1] == {"frame": 299, "mouth": 0}
    assert "C:" + "/Users/" not in serialized_manifest
    assert "C:" + "\\Users\\" not in serialized_manifest

    with Image.open(actor_png) as image:
        assert image.mode == "RGBA"
        assert image.size == (1024, 1536)
    with Image.open(background_png) as image:
        assert image.mode == "RGBA"
        assert image.size == (1024, 576)


def test_videotoon_smoke_cli_writes_manifest(tmp_path, capsys):
    smoke = _smoke_module()
    output_dir = tmp_path / "smoke"

    exit_code = smoke.main(
        [
            "local",
            "--source-repo-root",
            str(ROOT),
            "--output-dir",
            str(output_dir),
            "--duration-seconds",
            "10",
        ]
    )
    captured = capsys.readouterr()
    manifest = json.loads((output_dir / "smoke_manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert manifest["ready_for_render"] is True
    assert manifest["artifacts"]["remotion_props"] == "prepare/daily_life_toon_ep001.remotion_props.json"
    assert "video-toon smoke bundle" in captured.out


def test_stage_smoke_bundle_for_remotion_copies_public_assets_and_rewrites_props(tmp_path):
    smoke = _smoke_module()
    output_dir = tmp_path / "smoke"
    remotion_project = tmp_path / "remotion-poc"
    smoke.write_local_videotoon_smoke_bundle(
        output_dir,
        source_repo_root=ROOT,
        fps=30,
        duration_seconds=10,
    )

    report = smoke.stage_smoke_bundle_for_remotion(
        output_dir / "smoke_manifest.json",
        remotion_project,
    )

    staged_props_path = output_dir / "prepare" / "daily_life_toon_ep001.remotion_staged_props.json"
    staged_props = json.loads(staged_props_path.read_text(encoding="utf-8"))
    image = staged_props["images"][0]

    assert report["schema"] == "reverie.local.videotoon_remotion_stage.v1"
    assert report["ready_for_remotion"] is True
    assert report["copied_asset_count"] == 6
    assert len(report["copied_assets"]) == report["copied_asset_count"]
    assert report["missing_asset_count"] == 0
    assert report["staged_props"] == "prepare/daily_life_toon_ep001.remotion_staged_props.json"
    assert image["backgroundPath"] == "videotoon_smoke/daily_life_toon_ep001/backgrounds/street_day_00.png"
    assert image["foregroundPath"] == (
        "videotoon_smoke/daily_life_toon_ep001/"
        "actor_models/actor_adult_woman_01/variants/happy_standing.png"
    )
    assert image["eyesClosedPath"].endswith("actor_models/actor_adult_woman_01/face_parts/eyes_closed.png")
    assert (
        remotion_project
        / "public"
        / "videotoon_smoke"
        / "daily_life_toon_ep001"
        / "backgrounds"
        / "street_day_00.png"
    ).exists()
    assert (
        remotion_project
        / "public"
        / "videotoon_smoke"
        / "daily_life_toon_ep001"
        / "actor_models"
        / "actor_adult_woman_01"
        / "face_parts"
        / "mouth_small_open.png"
    ).exists()
    assert report["command_preview"]["composition_id"] == "RadioDrama"
    assert "remotion render RadioDrama" in report["command_preview"]["render"]


def test_videotoon_smoke_cli_stage_remotion_writes_report(tmp_path, capsys):
    smoke = _smoke_module()
    output_dir = tmp_path / "smoke"
    remotion_project = tmp_path / "remotion-poc"
    smoke.write_local_videotoon_smoke_bundle(output_dir, source_repo_root=ROOT)

    exit_code = smoke.main(
        [
            "stage-remotion",
            str(output_dir / "smoke_manifest.json"),
            "--remotion-project",
            str(remotion_project),
        ]
    )
    captured = capsys.readouterr()
    report = json.loads((output_dir / "prepare" / "daily_life_toon_ep001.remotion_stage.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["ready_for_remotion"] is True
    assert "Remotion smoke assets" in captured.out


def test_pyproject_exposes_videotoon_smoke_cli():
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts["reverie-videotoon-smoke"] == "utils.videotoon_smoke:main"
