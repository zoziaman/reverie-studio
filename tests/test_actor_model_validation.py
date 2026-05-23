import importlib
import json
import tomllib
from pathlib import Path

import pytest

from config.pack_validator import PackValidator


ROOT = Path(__file__).resolve().parents[1]
ACTOR_MODEL_PATH = ROOT / "assets" / "actor_models" / "actor_adult_woman_01" / "actor.json"
ACTOR_POOL_SCHEMA_PATH = ROOT / "schemas" / "video_toon_actor_pool.schema.json"
PYPROJECT_PATH = ROOT / "pyproject.toml"


def _actor_model_module():
    try:
        return importlib.import_module("utils.actor_model")
    except ModuleNotFoundError as exc:
        pytest.fail(f"utils.actor_model module is required for actor model package validation: {exc}")


def _base_settings(actor_pool):
    return {
        "visual_storytelling": {"enabled": False},
        "tts": {"character_mapping": {"narrator": "narrator_female"}},
        "sd": {"positive": "test"},
        "visual": {"safe_fallbacks": ["fallback"]},
        "motiontoon": {
            "enabled": True,
            "video_toon_local_enabled": True,
            "video_toon_generation_backend": "comfyui",
            "video_toon_workflow_template": "layered_actor_pool_v1",
            "actor_pool": actor_pool,
            "cast_slots": {
                "lead": {"actor_id": next(iter(actor_pool.keys()))},
            },
        },
    }


def test_validate_actor_model_package_accepts_public_safe_template():
    actor_model = _actor_model_module()

    result = actor_model.validate_actor_model_package(ACTOR_MODEL_PATH, repo_root=ROOT)

    assert result.is_valid is True
    assert result.errors == []
    assert result.actor_id == "actor_adult_woman_01"
    assert "neutral_standing" in result.required_variants


def test_pack_validator_accepts_actor_model_path_when_contract_matches():
    validator = PackValidator(repo_root=ROOT)

    result = validator.validate_settings(
        _base_settings(
            {
                "actor_adult_woman_01": {
                    "actor_model_path": "assets/actor_models/actor_adult_woman_01/actor.json",
                    "visual_identity": "adult Korean woman reusable video-toon actor",
                    "voice_profile": "female_01",
                    "required_variants": ["neutral_standing", "talking_standing"],
                }
            }
        )
    )

    assert result.is_valid is True
    assert result.errors == []


def test_pack_validator_rejects_actor_model_path_actor_id_mismatch():
    validator = PackValidator(repo_root=ROOT)

    result = validator.validate_settings(
        _base_settings(
            {
                "actor_other_99": {
                    "actor_model_path": "assets/actor_models/actor_adult_woman_01/actor.json",
                    "visual_identity": "mismatched reusable actor",
                    "voice_profile": "female_01",
                    "required_variants": ["neutral_standing"],
                }
            }
        )
    )

    assert result.is_valid is False
    assert any("actor_id" in error and "actor_other_99" in error for error in result.errors)


def test_pack_validator_default_repo_root_validates_actor_model_path():
    validator = PackValidator()

    result = validator.validate_settings(
        _base_settings(
            {
                "actor_other_99": {
                    "actor_model_path": "assets/actor_models/actor_adult_woman_01/actor.json",
                    "visual_identity": "mismatched reusable actor",
                    "voice_profile": "female_01",
                    "required_variants": ["neutral_standing"],
                }
            }
        )
    )

    assert result.is_valid is False
    assert not any("repo_root is unavailable" in warning for warning in result.warnings)
    assert any("actor_id" in error and "actor_other_99" in error for error in result.errors)


def test_pack_validator_rejects_required_variant_missing_from_actor_model():
    validator = PackValidator(repo_root=ROOT)

    result = validator.validate_settings(
        _base_settings(
            {
                "actor_adult_woman_01": {
                    "actor_model_path": "assets/actor_models/actor_adult_woman_01/actor.json",
                    "visual_identity": "adult Korean woman reusable video-toon actor",
                    "voice_profile": "female_01",
                    "required_variants": ["neutral_standing", "impossible_pose"],
                }
            }
        )
    )

    assert result.is_valid is False
    assert any("impossible_pose" in error and "actor_model" in error for error in result.errors)


def test_actor_pool_schema_documents_actor_model_path():
    schema = json.loads(ACTOR_POOL_SCHEMA_PATH.read_text(encoding="utf-8"))

    actor_properties = schema["additionalProperties"]["properties"]

    assert actor_properties["actor_model_path"]["type"] == "string"
    assert actor_properties["actor_model_path"]["minLength"] == 1


def test_build_actor_asset_request_manifest_expands_variants_and_face_parts():
    actor_model = _actor_model_module()
    actor = json.loads(ACTOR_MODEL_PATH.read_text(encoding="utf-8"))

    manifest = actor_model.build_actor_asset_request_manifest(ACTOR_MODEL_PATH, repo_root=ROOT)
    requests = manifest["requests"]
    variants = [request for request in requests if request["request_type"] == "variant"]
    mouths = [request for request in requests if request["request_type"] == "mouth_shape"]
    eyes = [request for request in requests if request["request_type"] == "eye_shape"]

    assert manifest["schema"] == "reverie.actor_model.asset_requests.v1"
    assert manifest["actor_id"] == "actor_adult_woman_01"
    assert manifest["source_actor_model_path"] == "assets/actor_models/actor_adult_woman_01/actor.json"
    assert len(variants) == len(actor["required_variants"])
    assert len(mouths) == len(actor["mouth_shapes"])
    assert len(eyes) == len(actor["eye_shapes"])
    assert variants[0]["request_id"] == "actor_adult_woman_01__variant__neutral_standing"
    assert variants[0]["target_relative_path"] == "variants/neutral_standing.png"
    assert "actor_adult_woman_01" in variants[0]["prompt"]
    assert "neutral_standing" in variants[0]["prompt"]
    assert "identity drift" in variants[0]["negative_prompt"]
    assert mouths[0]["target_relative_path"].startswith("face_parts/")
    assert eyes[0]["target_relative_path"].startswith("face_parts/")
    assert all(request["public_safe"] is True for request in requests)


def test_write_actor_asset_request_manifest_creates_json(tmp_path):
    actor_model = _actor_model_module()
    output_path = tmp_path / "actor_adult_woman_01.asset_requests.json"

    written_path = actor_model.write_actor_asset_request_manifest(
        ACTOR_MODEL_PATH,
        output_path,
        repo_root=ROOT,
    )
    manifest = json.loads(output_path.read_text(encoding="utf-8"))

    assert written_path == output_path
    assert manifest["actor_id"] == "actor_adult_woman_01"
    assert manifest["requests"]
    private_path_prefix = "C:" + "/Users/"
    assert not any(private_path_prefix in json.dumps(request) for request in manifest["requests"])


def test_actor_asset_request_manifest_without_repo_root_avoids_private_paths():
    actor_model = _actor_model_module()

    manifest = actor_model.build_actor_asset_request_manifest(ACTOR_MODEL_PATH)
    serialized = json.dumps(manifest)
    private_path_prefixes = ("C:" + "/Users/", "C:" + "\\Users\\")

    assert all(prefix not in serialized for prefix in private_path_prefixes)


def test_actor_model_cli_writes_asset_request_manifest(tmp_path, capsys):
    actor_model = _actor_model_module()
    output_path = tmp_path / "requests.json"

    exit_code = actor_model.main(
        [
            "asset-requests",
            str(ACTOR_MODEL_PATH),
            "--repo-root",
            str(ROOT),
            "--output",
            str(output_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert output_path.exists()
    assert "actor_adult_woman_01" in captured.out


def test_pyproject_exposes_actor_model_request_cli():
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts["reverie-actor-model-requests"] == "utils.actor_model:main"
