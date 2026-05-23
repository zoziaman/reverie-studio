import json
import tomllib
from pathlib import Path

import pytest

from utils import actor_model


ROOT = Path(__file__).resolve().parents[1]
ACTOR_PRESET_CATALOG_PATH = ROOT / "assets" / "actor_model_presets" / "catalog.json"
PYPROJECT_PATH = ROOT / "pyproject.toml"


def _prepare_module():
    try:
        from utils import videotoon_episode_prepare
    except ModuleNotFoundError as exc:
        pytest.fail(f"utils.videotoon_episode_prepare module is required: {exc}")
    return videotoon_episode_prepare


def _write_prepare_inputs(tmp_path):
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
    return actor_root, background_root, output_dir, roster_path, episode_path, settings_path


def test_videotoon_episode_prepare_writes_all_preflight_artifacts(tmp_path):
    prepare = _prepare_module()
    actor_root, background_root, output_dir, roster_path, episode_path, settings_path = _write_prepare_inputs(tmp_path)

    report = prepare.write_videotoon_episode_prepare_bundle(
        roster_path,
        episode_path,
        settings_path,
        output_dir,
        actor_root=actor_root,
        background_root=background_root,
    )
    preflight = json.loads((output_dir / "daily_life_toon_ep001.preflight.json").read_text(encoding="utf-8"))
    background_requests = json.loads(
        (output_dir / "daily_life_toon_ep001.background_requests.json").read_text(encoding="utf-8")
    )
    actor_layer_specs = json.loads(
        (output_dir / "daily_life_toon_ep001.actor_layer_specs.json").read_text(encoding="utf-8")
    )

    assert report["schema"] == "reverie.pack.videotoon_episode_prepare.v1"
    assert report["episode_id"] == "daily_life_toon_ep001"
    assert report["ready_for_render"] is False
    assert report["artifacts"]["actor_layer_specs"] == "daily_life_toon_ep001.actor_layer_specs.json"
    assert report["artifacts"]["actor_asset_plan"] == "daily_life_toon_ep001.actor_asset_plan.json"
    assert report["artifacts"]["actor_asset_coverage"] == "daily_life_toon_ep001.actor_asset_coverage.json"
    assert report["artifacts"]["background_requests"] == "daily_life_toon_ep001.background_requests.json"
    assert report["artifacts"]["background_coverage"] == "daily_life_toon_ep001.background_coverage.json"
    assert report["artifacts"]["preflight"] == "daily_life_toon_ep001.preflight.json"
    assert preflight["missing_count"] == 4
    assert report["missing_assets"] == preflight["missing_assets"]
    assert any(action["action_id"] == "create_missing_actor_assets" for action in report["next_actions"])
    assert any(action["action_id"] == "create_missing_background_assets" for action in report["next_actions"])
    assert any(action["action_id"] == "rerun_prepare" for action in report["next_actions"])
    assert "C:" + "/Users/" not in json.dumps(report)
    assert "C:" + "\\Users\\" not in json.dumps(report)
    assert actor_layer_specs["schema"] == "reverie.pack.actor_roster.layer_specs.v1"
    assert actor_layer_specs["actor_count"] == 1
    assert actor_layer_specs["actors"]["actor_daily_adult_man_01"]["layer_order"] == [
        "variant_base",
        "eye_layer",
        "mouth_layer",
    ]
    assert background_requests["schema"] == "reverie.background_library.episode_asset_requests.v1"
    assert background_requests["request_count"] == 1
    assert not any(output_dir.rglob("*.png"))


def test_videotoon_episode_prepare_cli_writes_report_and_can_fail(tmp_path, capsys):
    prepare = _prepare_module()
    actor_root, background_root, output_dir, roster_path, episode_path, settings_path = _write_prepare_inputs(tmp_path)

    exit_code = prepare.main(
        [
            "episode",
            str(roster_path),
            str(episode_path),
            str(settings_path),
            "--actor-root",
            str(actor_root),
            "--background-root",
            str(background_root),
            "--output-dir",
            str(output_dir),
            "--fail-on-not-ready",
        ]
    )
    captured = capsys.readouterr()
    report = json.loads((output_dir / "daily_life_toon_ep001.prepare_report.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["schema"] == "reverie.pack.videotoon_episode_prepare.v1"
    assert report["ready_for_render"] is False
    assert "video-toon episode prepare bundle" in captured.out
    assert "next actions: create_missing_actor_assets, create_missing_background_assets, rerun_prepare" in captured.out


def test_pyproject_exposes_videotoon_episode_prepare_cli():
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts["reverie-videotoon-prepare"] == "utils.videotoon_episode_prepare:main"
