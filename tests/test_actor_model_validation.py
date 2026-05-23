import importlib
import json
from pathlib import Path

import pytest

from config.pack_validator import PackValidator


ROOT = Path(__file__).resolve().parents[1]
ACTOR_MODEL_PATH = ROOT / "assets" / "actor_models" / "actor_adult_woman_01" / "actor.json"
ACTOR_POOL_SCHEMA_PATH = ROOT / "schemas" / "video_toon_actor_pool.schema.json"


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
