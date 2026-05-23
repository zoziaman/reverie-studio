import json
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"


def _preflight_module():
    try:
        from utils import videotoon_preflight
    except ModuleNotFoundError as exc:
        pytest.fail(f"utils.videotoon_preflight module is required: {exc}")
    return videotoon_preflight


def _actor_coverage(*, ready=True, missing_count=0):
    return {
        "schema": "reverie.pack.actor_episode.asset_coverage.v1",
        "pack_id": "daily_life_toon",
        "episode_id": "ep001",
        "ready_for_render": ready,
        "expected_count": 3,
        "existing_count": 3 - missing_count,
        "missing_count": missing_count,
        "coverage_ratio": 1.0 if not missing_count else 0.6667,
        "missing_assets": ["s001:actor_daily_adult_man_01:variant:happy_standing"] if missing_count else [],
        "errors": [],
    }


def _background_coverage(*, ready=True, missing_count=0):
    return {
        "schema": "reverie.background_library.asset_coverage.v1",
        "pack_id": "daily_life_toon",
        "ready_for_render": ready,
        "expected_count": 1,
        "existing_count": 1 - missing_count,
        "missing_count": missing_count,
        "coverage_ratio": 1.0 if not missing_count else 0.0,
        "missing_assets": ["apartment_living_room_day_00.png"] if missing_count else [],
        "errors": [],
    }


def test_videotoon_episode_preflight_combines_actor_and_background_readiness():
    preflight = _preflight_module()

    report = preflight.build_videotoon_episode_preflight_report(
        _actor_coverage(ready=False, missing_count=1),
        _background_coverage(ready=True, missing_count=0),
    )

    assert report["schema"] == "reverie.pack.videotoon_episode_preflight.v1"
    assert report["pack_id"] == "daily_life_toon"
    assert report["episode_id"] == "ep001"
    assert report["ready_for_render"] is False
    assert report["actor_assets"]["ready_for_render"] is False
    assert report["background_assets"]["ready_for_render"] is True
    assert report["missing_count"] == 1
    assert report["missing_assets"] == [
        {
            "domain": "actor",
            "asset": "s001:actor_daily_adult_man_01:variant:happy_standing",
        }
    ]
    assert report["public_release_boundary"]["contains_generated_media"] is False


def test_videotoon_episode_preflight_cli_writes_report_and_can_fail(tmp_path, capsys):
    preflight = _preflight_module()
    actor_path = tmp_path / "actor_coverage.json"
    background_path = tmp_path / "background_coverage.json"
    output_path = tmp_path / "episode_preflight.json"
    actor_path.write_text(json.dumps(_actor_coverage(ready=True, missing_count=0)), encoding="utf-8")
    background_path.write_text(json.dumps(_background_coverage(ready=False, missing_count=1)), encoding="utf-8")

    exit_code = preflight.main(
        [
            "episode",
            "--actor-coverage",
            str(actor_path),
            "--background-coverage",
            str(background_path),
            "--output",
            str(output_path),
            "--fail-on-not-ready",
        ]
    )
    captured = capsys.readouterr()
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["schema"] == "reverie.pack.videotoon_episode_preflight.v1"
    assert report["ready_for_render"] is False
    assert report["background_assets"]["missing_count"] == 1
    assert "video-toon episode preflight" in captured.out


def test_pyproject_exposes_videotoon_preflight_cli():
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts["reverie-videotoon-preflight"] == "utils.videotoon_preflight:main"
