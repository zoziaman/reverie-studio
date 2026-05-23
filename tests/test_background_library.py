import json
import tomllib
from pathlib import Path

from modules_pro import background_library
from modules_pro.background_library import BackgroundLibrary, build_background_library_config


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"


def test_match_location_supports_life_saguk_aliases():
    bg = BackgroundLibrary(pack_id="test_pack", genre="senior", base_path="assets/backgrounds/test_pack")

    assert bg._match_location("한옥 마당") == "집"
    assert bg._match_location("사랑방") == "집"
    assert bg._match_location("대문 앞") == "집"
    assert bg._match_location("시장 골목") == "시장"
    assert bg._match_location("장터 입구") == "시장"
    assert bg._match_location("hanok courtyard") == "집"
    assert bg._match_location("market alley") == "시장"


def test_generate_background_library_normalizes_requested_locations(tmp_path):
    bg = BackgroundLibrary(pack_id="test_pack", genre="senior", base_path=str(tmp_path))

    captured = []

    def fake_generate_single_background(sd_api, prompt, negative_prompt, seed, location, time, index):
        captured.append((location, time, index))
        return str(tmp_path / f"{location}_{time}_{index:02d}.png")

    bg._generate_single_background = fake_generate_single_background

    result = bg.generate_background_library(
        sd_api=object(),
        locations=["한옥 마당", "시장 골목"],
        images_per_location=2,
        time_variants=False,
    )

    assert "집" in result
    assert "시장" in result
    assert all(location in {"집", "시장"} for location, _time, _index in captured)


def test_generate_single_background_saves_base64_result(tmp_path):
    bg = BackgroundLibrary(pack_id="test_pack", genre="senior", base_path=str(tmp_path))

    class FakeApi:
        def txt2img(self, **_kwargs):
            return {
                "images": [
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0ioAAAAASUVORK5CYII="
                ]
            }

    path = bg._generate_single_background(
        sd_api=FakeApi(),
        prompt="test",
        negative_prompt="test",
        seed=1,
        location="집",
        time="any",
        index=0,
    )

    assert path is not None
    assert tmp_path.joinpath("집_any_00.png").exists()


def test_background_asset_request_manifest_expands_templates_without_generation(tmp_path):
    config = build_background_library_config(
        genre="daily_life_toon",
        config_data={
            "style_prompt": "clean reusable video-toon background",
            "negative_prompt": "people, readable text",
            "location_templates": {
                "home": {
                    "id": "home",
                    "name_ko": "home",
                    "name_en": "home",
                    "base_prompt": "small Korean apartment living room, no people",
                    "keywords": ["living room"],
                }
            },
            "time_modifiers": {"day": "soft daylight"},
        },
        library_path="assets/backgrounds/test_pack",
    )
    bg = BackgroundLibrary(pack_id="test_pack", genre="daily_life_toon", config=config, base_path=str(tmp_path))

    manifest = bg.build_asset_request_manifest(
        locations=["living room"],
        images_per_location=2,
        times=["day"],
    )
    requests = manifest["requests"]
    serialized = str(manifest)

    assert manifest["schema"] == "reverie.background_library.asset_requests.v1"
    assert manifest["pack_id"] == "test_pack"
    assert manifest["target_base_path"] == "assets/backgrounds/test_pack"
    assert manifest["request_count"] == 2
    assert len(requests) == 2
    assert requests[0]["request_type"] == "background_plate"
    assert requests[0]["location_id"] == "home"
    assert requests[0]["time"] == "day"
    assert requests[0]["target_relative_path"] == "home_day_00.png"
    assert "small Korean apartment living room" in requests[0]["prompt"]
    assert "soft daylight" in requests[0]["prompt"]
    assert "people" in requests[0]["negative_prompt"]
    assert requests[0]["public_safe"] is True
    assert not any(tmp_path.rglob("*.png"))
    assert "C:" + "/Users/" not in serialized
    assert "C:" + "\\Users\\" not in serialized


def test_background_asset_coverage_report_tracks_requested_background_files(tmp_path):
    config = build_background_library_config(
        genre="daily_life_toon",
        config_data={
            "location_templates": {
                "street": {
                    "id": "street",
                    "name_ko": "street",
                    "name_en": "street",
                    "base_prompt": "quiet Korean neighborhood street, no people",
                }
            }
        },
        library_path="assets/backgrounds/test_pack",
    )
    bg = BackgroundLibrary(pack_id="test_pack", genre="daily_life_toon", config=config, base_path=str(tmp_path))
    manifest = bg.build_asset_request_manifest(locations=["street"], images_per_location=1, times=["night"])

    missing_report = bg.build_asset_coverage_report(manifest)
    target = tmp_path / manifest["requests"][0]["target_relative_path"]
    target.write_bytes(b"local background placeholder")
    ready_report = bg.build_asset_coverage_report(manifest)

    assert missing_report["schema"] == "reverie.background_library.asset_coverage.v1"
    assert missing_report["expected_count"] == 1
    assert missing_report["existing_count"] == 0
    assert missing_report["missing_count"] == 1
    assert missing_report["ready_for_render"] is False
    assert ready_report["existing_count"] == 1
    assert ready_report["missing_count"] == 0
    assert ready_report["coverage_ratio"] == 1.0
    assert ready_report["ready_for_render"] is True


def test_background_episode_asset_coverage_filters_manifest_to_scene_locations(tmp_path):
    config = build_background_library_config(
        genre="daily_life_toon",
        config_data={
            "location_templates": {
                "home": {
                    "id": "home",
                    "name_ko": "home",
                    "name_en": "home",
                    "base_prompt": "small Korean apartment living room, no people",
                    "keywords": ["living room"],
                },
                "street": {
                    "id": "street",
                    "name_ko": "street",
                    "name_en": "street",
                    "base_prompt": "quiet Korean neighborhood street, no people",
                    "keywords": ["neighborhood street"],
                },
            }
        },
        library_path="assets/backgrounds/test_pack",
    )
    bg = BackgroundLibrary(pack_id="test_pack", genre="daily_life_toon", config=config, base_path=str(tmp_path))
    manifest = bg.build_asset_request_manifest(images_per_location=1, times=["day", "night"])
    episode = {
        "episode_id": "ep001",
        "scenes": [
            {"scene_id": "s001", "background_id": "street", "time": "night"},
            {"scene_id": "s002", "location": "living room", "time": "day"},
        ],
    }
    (tmp_path / "street_night_00.png").write_bytes(b"local background placeholder")

    report = bg.build_episode_asset_coverage_report(manifest, episode)

    assert report["schema"] == "reverie.background_library.episode_asset_coverage.v1"
    assert report["episode_id"] == "ep001"
    assert report["scene_count"] == 2
    assert report["expected_count"] == 2
    assert report["existing_count"] == 1
    assert report["missing_count"] == 1
    assert report["ready_for_render"] is False
    assert report["scene_backgrounds"][0]["target_relative_path"] == "street_night_00.png"
    assert report["scene_backgrounds"][1]["target_relative_path"] == "home_day_00.png"
    assert report["missing_assets"] == ["s002:home_day_00.png"]


def test_background_library_cli_writes_asset_requests_and_coverage(tmp_path, capsys):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        """
{
  "background_library": {
    "style_prompt": "clean reusable video-toon background",
    "location_templates": {
      "shop": {
        "id": "shop",
        "name_ko": "shop",
        "name_en": "shop",
        "base_prompt": "small Korean shop front, no people"
      }
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    request_path = tmp_path / "shop_background_requests.json"
    coverage_path = tmp_path / "shop_background_coverage.json"
    background_root = tmp_path / "backgrounds"

    request_code = background_library.main(
        [
            "asset-requests",
            str(settings_path),
            "--pack-id",
            "test_pack",
            "--background-root",
            str(background_root),
            "--time",
            "day",
            "--images-per-location",
            "1",
            "--output",
            str(request_path),
        ]
    )
    coverage_code = background_library.main(
        [
            "coverage",
            str(request_path),
            "--background-root",
            str(background_root),
            "--output",
            str(coverage_path),
        ]
    )
    captured = capsys.readouterr()
    manifest = background_library._load_json_object(request_path, "request manifest")
    coverage = background_library._load_json_object(coverage_path, "coverage report")

    assert request_code == 0
    assert coverage_code == 0
    assert manifest["schema"] == "reverie.background_library.asset_requests.v1"
    assert manifest["request_count"] == 1
    assert coverage["schema"] == "reverie.background_library.asset_coverage.v1"
    assert coverage["missing_count"] == 1
    assert "background asset requests" in captured.out
    assert "background asset coverage" in captured.out


def test_background_library_cli_writes_episode_asset_coverage(tmp_path, capsys):
    request_path = tmp_path / "background_requests.json"
    episode_path = tmp_path / "episode.json"
    coverage_path = tmp_path / "episode_background_coverage.json"
    background_root = tmp_path / "backgrounds"
    (background_root / "test_pack").mkdir(parents=True)
    request_path.write_text(
        json.dumps(
            {
                "schema": "reverie.background_library.asset_requests.v1",
                "pack_id": "test_pack",
                "genre": "daily_life_toon",
                "target_base_path": "assets/backgrounds/test_pack",
                "locations": [
                    {
                        "location_id": "street",
                        "template_id": "street",
                        "name_ko": "street",
                        "name_en": "street",
                        "keywords": ["street"],
                    }
                ],
                "requests": [
                    {
                        "request_id": "test_pack__background_plate__street__day__00",
                        "request_type": "background_plate",
                        "location_id": "street",
                        "time": "day",
                        "target_relative_path": "street_day_00.png",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    episode_path.write_text(
        json.dumps({"episode_id": "ep001", "scenes": [{"scene_id": "s001", "background_id": "street", "time": "day"}]}),
        encoding="utf-8",
    )

    exit_code = background_library.main(
        [
            "episode-coverage",
            str(request_path),
            str(episode_path),
            "--background-root",
            str(background_root),
            "--output",
            str(coverage_path),
            "--fail-on-missing",
        ]
    )
    captured = capsys.readouterr()
    report = background_library._load_json_object(coverage_path, "episode coverage report")

    assert exit_code == 1
    assert report["schema"] == "reverie.background_library.episode_asset_coverage.v1"
    assert report["missing_count"] == 1
    assert "episode background asset coverage" in captured.out


def test_pyproject_exposes_background_library_request_cli():
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts["reverie-background-library-requests"] == "modules_pro.background_library:main"


def test_build_background_library_config_uses_custom_templates():
    config = build_background_library_config(
        genre="senior",
        config_data={
            "profile": "yadam",
            "style_prompt": "custom joseon style",
            "location_templates": {
                "집": {
                    "id": "hanok_home",
                    "name_ko": "집",
                    "name_en": "hanok home",
                    "base_prompt": "joseon hanok interior, no people",
                    "keywords": ["한옥", "사랑방"],
                }
            },
        },
        library_path="assets/backgrounds/test_pack",
    )

    assert config.style_prompt == "custom joseon style"
    assert "집" in config.location_templates
    assert config.location_templates["집"].id == "hanok_home"
    assert "한옥" in config.location_templates["집"].keywords
