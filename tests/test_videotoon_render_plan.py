import json
import tomllib
from pathlib import Path

import pytest

from utils import actor_model, videotoon_episode_prepare


ROOT = Path(__file__).resolve().parents[1]
ACTOR_PRESET_CATALOG_PATH = ROOT / "assets" / "actor_model_presets" / "catalog.json"
PYPROJECT_PATH = ROOT / "pyproject.toml"


def _render_plan_module():
    try:
        from utils import videotoon_render_plan
    except ModuleNotFoundError as exc:
        pytest.fail(f"utils.videotoon_render_plan module is required: {exc}")
    return videotoon_render_plan


def _write_prepare_bundle(tmp_path):
    actor_root = tmp_path / "actor_models"
    output_dir = tmp_path / "prepare"
    background_root = tmp_path / "backgrounds"
    roster_path = tmp_path / "daily_life_toon.actor_roster_plan.json"
    episode_path = tmp_path / "daily_life_toon_ep001.json"
    settings_path = tmp_path / "settings.json"

    roster_plan = actor_model.build_pack_actor_roster_plan(
        "daily_life_toon",
        [
            {
                "role_id": "protagonist",
                "preset_id": "daily_adult_man",
                "actor_id": "actor_daily_adult_man_01",
            }
        ],
        catalog_path=ACTOR_PRESET_CATALOG_PATH,
    )
    actor_model.scaffold_actor_models_from_roster_plan(
        roster_plan,
        actor_root=actor_root,
        catalog_path=ACTOR_PRESET_CATALOG_PATH,
    )
    roster_path.write_text(json.dumps(roster_plan), encoding="utf-8")
    episode_path.write_text(
        json.dumps(
            {
                "episode_id": "daily_life_toon_ep001",
                "role_casting": roster_plan["episode_cast_seed"]["role_casting"],
                "scenes": [
                    {
                        "scene_id": "s001",
                        "role_id": "protagonist",
                        "actor_id": "actor_daily_adult_man_01",
                        "emotion": "happy",
                        "pose": "standing",
                        "shot_type": "medium",
                        "line": "I can explain everything.",
                        "background_id": "street",
                        "time": "day",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    settings_path.write_text(
        json.dumps(
            {
                "background_library": {
                    "style_prompt": "clean reusable video-toon background",
                    "location_templates": {
                        "street": {
                            "id": "street",
                            "name_ko": "street",
                            "name_en": "street",
                            "base_prompt": "quiet Korean neighborhood street, no people",
                            "keywords": ["street"],
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    videotoon_episode_prepare.write_videotoon_episode_prepare_bundle(
        roster_path,
        episode_path,
        settings_path,
        output_dir,
        actor_root=actor_root,
        background_root=background_root,
    )
    return output_dir / "daily_life_toon_ep001.prepare_report.json"


def test_build_videotoon_render_plan_from_prepare_report(tmp_path):
    render_plan = _render_plan_module()
    prepare_report_path = _write_prepare_bundle(tmp_path)

    plan = render_plan.build_videotoon_render_plan_from_prepare_report(prepare_report_path)
    serialized = json.dumps(plan)
    scene = plan["scenes"][0]
    layer_types = [layer["layer_type"] for layer in scene["composition_layers"]]

    assert plan["schema"] == "reverie.pack.videotoon_render_plan.v1"
    assert plan["pack_id"] == "daily_life_toon"
    assert plan["episode_id"] == "daily_life_toon_ep001"
    assert plan["ready_for_render"] is False
    assert plan["scene_count"] == 1
    assert plan["source_artifacts"]["actor_layer_specs"] == "daily_life_toon_ep001.actor_layer_specs.json"
    assert layer_types == ["background_plate", "variant_base", "eye_layer", "mouth_layer"]
    assert scene["scene_id"] == "s001"
    assert scene["actor_id"] == "actor_daily_adult_man_01"
    assert scene["background"]["target_relative_path"] == "street_day_00.png"
    assert scene["actor"]["variant_key"] == "happy_standing"
    assert scene["actor"]["mouth_shape_key"] == "mouth_small_open"
    assert scene["actor"]["eye_shape_key"] == "eyes_open"
    assert scene["actor"]["available_mouth_layers"]["mouth_closed"]["target_relative_path"] == "face_parts/mouth_closed.png"
    assert scene["actor"]["available_mouth_layers"]["mouth_small_open"]["target_relative_path"] == "face_parts/mouth_small_open.png"
    assert scene["actor"]["available_eye_layers"]["eyes_closed"]["target_relative_path"] == "face_parts/eyes_closed.png"
    assert scene["composition_layers"][1]["target_relative_path"] == "variants/happy_standing.png"
    assert scene["composition_layers"][2]["anchor_key"] == "eye_center"
    assert scene["composition_layers"][3]["anchor_key"] == "mouth_center"
    assert "C:" + "/Users/" not in serialized
    assert "C:" + "\\Users\\" not in serialized


def test_videotoon_render_plan_cli_writes_manifest(tmp_path, capsys):
    render_plan = _render_plan_module()
    prepare_report_path = _write_prepare_bundle(tmp_path)
    output_path = tmp_path / "daily_life_toon_ep001.render_plan.json"

    exit_code = render_plan.main(
        [
            "from-prepare",
            str(prepare_report_path),
            "--output",
            str(output_path),
        ]
    )
    captured = capsys.readouterr()
    plan = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert plan["schema"] == "reverie.pack.videotoon_render_plan.v1"
    assert plan["scene_count"] == 1
    assert "video-toon render plan" in captured.out


def test_build_remotion_props_from_videotoon_render_plan(tmp_path):
    render_plan = _render_plan_module()
    prepare_report_path = _write_prepare_bundle(tmp_path)
    plan = render_plan.build_videotoon_render_plan_from_prepare_report(prepare_report_path)

    props = render_plan.build_remotion_props_from_videotoon_render_plan(
        plan,
        fps=30,
        scene_duration_frames=90,
        width=1080,
        height=1920,
    )
    serialized = json.dumps(props)
    image = props["images"][0]

    assert props["schema"] == "reverie.remotion.radio_drama_props.v1"
    assert props["fps"] == 30
    assert props["width"] == 1080
    assert props["height"] == 1920
    assert props["totalFrames"] == 90
    assert props["motiontoon"]["enabled"] is True
    assert props["motiontoon"]["mode"] == "layered_actor_pool_v1"
    assert props["motiontoon"]["sourceRenderPlanSchema"] == "reverie.pack.videotoon_render_plan.v1"
    assert props["motiontoon"]["renderPlan"]["episode_id"] == "daily_life_toon_ep001"
    assert image["path"] == "street_day_00.png"
    assert image["backgroundPath"] == "street_day_00.png"
    assert image["foregroundPath"] == "variants/happy_standing.png"
    assert image["eyesOpenPath"] == "face_parts/eyes_open.png"
    assert image["eyesClosedPath"] == "face_parts/eyes_closed.png"
    assert image["mouthClosedPath"] == "face_parts/mouth_closed.png"
    assert image["mouthOpenPath"] == "face_parts/mouth_small_open.png"
    assert image["mouthCues"][:4] == [
        {"frame": 0, "mouth": 0},
        {"frame": 4, "mouth": 1},
        {"frame": 8, "mouth": 0},
        {"frame": 12, "mouth": 1},
    ]
    assert image["startFrame"] == 0
    assert image["durationFrames"] == 90
    assert image["motion"]["scene_type"] == "video_toon_layered_scene"
    assert image["motion"]["use_layered_cutout"] is True
    assert image["motion"]["face_rig"] is True
    assert "subtitle_pulse" in image["motion"]["primitives"]
    assert "C:" + "/Users/" not in serialized
    assert "C:" + "\\Users\\" not in serialized


def test_build_asset_work_order_from_videotoon_render_plan(tmp_path):
    render_plan = _render_plan_module()
    prepare_report_path = _write_prepare_bundle(tmp_path)
    plan = render_plan.build_videotoon_render_plan_from_prepare_report(prepare_report_path)

    work_order = render_plan.build_videotoon_asset_work_order_from_render_plan(plan)
    serialized = json.dumps(work_order)
    targets = {asset["target_relative_path"]: asset for asset in work_order["assets"]}

    assert work_order["schema"] == "reverie.pack.videotoon_asset_work_order.v1"
    assert work_order["pack_id"] == "daily_life_toon"
    assert work_order["episode_id"] == "daily_life_toon_ep001"
    assert work_order["asset_count"] == len(work_order["assets"])
    assert work_order["creates_media"] is False
    assert targets["street_day_00.png"]["asset_type"] == "background_plate"
    assert targets["variants/happy_standing.png"]["asset_type"] == "variant_base"
    assert targets["face_parts/eyes_open.png"]["asset_type"] == "eye_layer"
    assert targets["face_parts/eyes_closed.png"]["asset_type"] == "eye_layer"
    assert targets["face_parts/mouth_closed.png"]["asset_type"] == "mouth_layer"
    assert targets["face_parts/mouth_small_open.png"]["asset_type"] == "mouth_layer"
    assert all(asset["status"] == "needs_local_generation" for asset in work_order["assets"])
    assert all(asset["public_safe"] is True for asset in work_order["assets"])
    assert "C:" + "/Users/" not in serialized
    assert "C:" + "\\Users\\" not in serialized


def test_videotoon_render_plan_cli_writes_asset_work_order(tmp_path, capsys):
    render_plan = _render_plan_module()
    prepare_report_path = _write_prepare_bundle(tmp_path)
    render_plan_path = tmp_path / "daily_life_toon_ep001.render_plan.json"
    output_path = tmp_path / "daily_life_toon_ep001.asset_work_order.json"
    render_plan.write_videotoon_render_plan_from_prepare_report(prepare_report_path, render_plan_path)

    exit_code = render_plan.main(
        [
            "to-asset-work-order",
            str(render_plan_path),
            "--output",
            str(output_path),
        ]
    )
    captured = capsys.readouterr()
    work_order = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert work_order["schema"] == "reverie.pack.videotoon_asset_work_order.v1"
    assert work_order["asset_count"] == 6
    assert "asset work order" in captured.out


def test_videotoon_render_plan_cli_writes_remotion_props(tmp_path, capsys):
    render_plan = _render_plan_module()
    prepare_report_path = _write_prepare_bundle(tmp_path)
    render_plan_path = tmp_path / "daily_life_toon_ep001.render_plan.json"
    output_path = tmp_path / "daily_life_toon_ep001.remotion_props.json"
    render_plan.write_videotoon_render_plan_from_prepare_report(prepare_report_path, render_plan_path)

    exit_code = render_plan.main(
        [
            "to-remotion-props",
            str(render_plan_path),
            "--output",
            str(output_path),
            "--width",
            "1080",
            "--height",
            "1920",
            "--scene-duration-frames",
            "90",
        ]
    )
    captured = capsys.readouterr()
    props = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert props["schema"] == "reverie.remotion.radio_drama_props.v1"
    assert props["images"][0]["foregroundPath"] == "variants/happy_standing.png"
    assert "Remotion props" in captured.out


def test_pyproject_exposes_videotoon_render_plan_cli():
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts["reverie-videotoon-render-plan"] == "utils.videotoon_render_plan:main"
