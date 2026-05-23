import json
from pathlib import Path

from config.pack_validator import PackValidator


def test_pack_validator_allows_extended_channel_type_suffixes():
    validator = PackValidator()
    result = validator.validate_manifest(
        {
            "pack_id": "senior_life_saguk",
            "pack_name": "생활 사극",
            "version": "1.0.0",
            "genre": "senior",
            "channel_type": "senior_life_saguk",
            "reverie_version_min": "1",
        }
    )

    assert result.is_valid is True
    assert not any("channel_type" in warning for warning in result.warnings)


def test_pack_validator_accepts_valid_motiontoon_settings():
    validator = PackValidator()
    result = validator.validate_settings(
        {
            "visual_storytelling": {"enabled": False},
            "tts": {"character_mapping": {"narrator": "narrator_female"}},
            "sd": {"positive": "test"},
            "visual": {"safe_fallbacks": ["fallback"]},
            "motiontoon": {
                "enabled": True,
                "mode": "screen_space",
                "profile": "gishini",
                "overlay_theme": "scam_alert",
                "layered_cutout_enabled": True,
                "layered_cutout_strength": 0.82,
                "prop_overlay_enabled": True,
                "dialogue_panel_enabled": True,
                "snap_zoom_enabled": True,
                "video_toon_local_enabled": True,
                "video_toon_generation_backend": "comfyui",
                "video_toon_layered_assets_required": True,
                "video_toon_workflow_template": "sd15_ipadapter_openpose_v1",
                "scene_motion_rules": {"reveal": ["snap_zoom"]},
                "cast_slots": {
                    "protagonist": {
                        "character_id": "young_woman",
                        "aliases": ["직원", "주인공"],
                    }
                },
            },
        }
    )

    assert result.is_valid is True
    assert not result.errors


def test_pack_validator_rejects_unknown_motiontoon_profile():
    validator = PackValidator()
    result = validator.validate_settings(
        {
            "visual_storytelling": {"enabled": False},
            "tts": {"character_mapping": {"narrator": "narrator_female"}},
            "sd": {"positive": "test"},
            "visual": {"safe_fallbacks": ["fallback"]},
            "motiontoon": {
                "enabled": True,
                "profile": "ultra",
            },
        }
    )

    assert result.is_valid is False
    assert any("settings.motiontoon.profile" in error for error in result.errors)


def test_pack_validator_rejects_invalid_videotoon_backend():
    validator = PackValidator()
    result = validator.validate_settings(
        {
            "visual_storytelling": {"enabled": False},
            "tts": {"character_mapping": {"narrator": "narrator_female"}},
            "sd": {"positive": "test"},
            "visual": {"safe_fallbacks": ["fallback"]},
            "motiontoon": {
                "enabled": True,
                "video_toon_local_enabled": True,
                "video_toon_generation_backend": "browser",
            },
        }
    )

    assert result.is_valid is False
    assert any("settings.motiontoon.video_toon_generation_backend" in error for error in result.errors)


def test_pack_validator_accepts_character_library_lists():
    validator = PackValidator()
    result = validator.validate_settings(
        {
            "visual_storytelling": {
                "enabled": True,
                "characters": {
                    "young_woman": {"base": "korean woman", "style": "motiontoon"},
                    "_default": {"base": "fallback"},
                },
                "sd_model": {"checkpoint": "mistoonAnime_v10Noobai.safetensors"},
                "character_library": {
                    "enabled": True,
                    "preferred_slots": ["protagonist", "elder"],
                    "preferred_expressions": ["neutral", "talking"],
                    "preferred_poses": ["standing", "listening"],
                    "required_variant_keys": ["neutral_standing"],
                    "required_variant_keys_by_slot": {
                        "protagonist": ["neutral_standing", "talking_standing"]
                    },
                },
            },
            "tts": {"character_mapping": {"narrator": "narrator_female"}},
            "sd": {"positive": "test"},
            "visual": {"safe_fallbacks": ["fallback"]},
        }
    )

    assert result.is_valid is True
    assert not result.errors


def test_pack_validator_accepts_script_quality_settings():
    validator = PackValidator()
    result = validator.validate_settings(
        {
            "visual_storytelling": {"enabled": False},
            "tts": {"character_mapping": {"narrator": "narrator_female"}},
            "sd": {"positive": "test"},
            "visual": {"safe_fallbacks": ["fallback"]},
            "script_quality": {
                "min_non_narrator_roles": 3,
                "max_narration_ratio": 0.42,
                "min_turns_for_gate": 20,
                "max_ellipsis_ratio": 0.12,
                "warn_topic_overlap_ratio": 0.25,
            },
        }
    )

    assert result.is_valid is True
    assert not result.errors


def test_pack_validator_accepts_actor_pool_role_casting_contract():
    validator = PackValidator()
    result = validator.validate_settings(
        {
            "visual_storytelling": {
                "enabled": True,
                "characters": {
                    "actor_woman_01": {"base": "fixed Korean woman actor", "style": "webtoon cutout"},
                    "actor_man_01": {"base": "fixed Korean man actor", "style": "webtoon cutout"},
                    "_default": {"base": "fallback actor"},
                },
                "sd_model": {"checkpoint": "mistoonAnime_v10Noobai.safetensors"},
            },
            "tts": {"character_mapping": {"narrator": "narrator_female"}},
            "sd": {"positive": "test"},
            "visual": {"safe_fallbacks": ["fallback"]},
            "motiontoon": {
                "enabled": True,
                "video_toon_local_enabled": True,
                "video_toon_generation_backend": "comfyui",
                "video_toon_workflow_template": "layered_actor_pool_v1",
                "actor_pool": {
                    "actor_woman_01": {
                        "character_id": "actor_woman_01",
                        "visual_identity": "sharp-eyed recurring woman actor with short black hair",
                        "voice_profile": "female_01",
                        "required_variants": ["neutral_front", "fear_front"],
                        "sprite_sheet": {
                            "neutral_front": "assets/characters/actor_woman_01/neutral_front.png",
                            "fear_front": "assets/characters/actor_woman_01/fear_front.png",
                        },
                    },
                    "actor_man_01": {
                        "character_id": "actor_man_01",
                        "visual_identity": "tall recurring man actor with narrow face",
                        "voice_profile": "male_01",
                    },
                },
                "role_casting_contract": {
                    "enabled": True,
                    "strict_actor_refs": True,
                    "allow_background_extras": True,
                    "assignment_key": "role_casting",
                    "required_scene_fields": ["actor_id", "role_id", "emotion", "shot_type"],
                },
                "cast_slots": {
                    "protagonist": {"actor_id": "actor_woman_01", "aliases": ["lead", "victim"]},
                    "suspect": {"actor_id": "actor_man_01", "aliases": ["scammer", "suspect"]},
                },
            },
        }
    )

    assert result.is_valid is True
    assert not result.errors


def test_pack_validator_rejects_cast_slot_actor_missing_from_pool():
    validator = PackValidator()
    result = validator.validate_settings(
        {
            "visual_storytelling": {
                "enabled": True,
                "characters": {
                    "actor_woman_01": {"base": "fixed Korean woman actor", "style": "webtoon cutout"},
                    "_default": {"base": "fallback actor"},
                },
                "sd_model": {"checkpoint": "mistoonAnime_v10Noobai.safetensors"},
            },
            "tts": {"character_mapping": {"narrator": "narrator_female"}},
            "sd": {"positive": "test"},
            "visual": {"safe_fallbacks": ["fallback"]},
            "motiontoon": {
                "enabled": True,
                "actor_pool": {
                    "actor_woman_01": {
                        "character_id": "actor_woman_01",
                        "visual_identity": "fixed woman actor",
                    },
                },
                "cast_slots": {
                    "suspect": {"actor_id": "actor_man_99", "aliases": ["suspect"]},
                },
            },
        }
    )

    assert result.is_valid is False
    assert any("actor_man_99" in error and "actor_pool" in error for error in result.errors)


def test_pack_validator_rejects_actor_without_visual_identity():
    validator = PackValidator()
    result = validator.validate_settings(
        {
            "visual_storytelling": {
                "enabled": True,
                "characters": {
                    "actor_woman_01": {"base": "fixed Korean woman actor", "style": "webtoon cutout"},
                    "_default": {"base": "fallback actor"},
                },
                "sd_model": {"checkpoint": "mistoonAnime_v10Noobai.safetensors"},
            },
            "tts": {"character_mapping": {"narrator": "narrator_female"}},
            "sd": {"positive": "test"},
            "visual": {"safe_fallbacks": ["fallback"]},
            "motiontoon": {
                "enabled": True,
                "actor_pool": {
                    "actor_woman_01": {"character_id": "actor_woman_01"},
                },
                "cast_slots": {
                    "protagonist": {"actor_id": "actor_woman_01"},
                },
            },
        }
    )

    assert result.is_valid is False
    assert any("visual_identity" in error for error in result.errors)


def test_pack_validator_warns_for_legacy_videotoon_cast_without_actor_pool():
    validator = PackValidator()
    result = validator.validate_settings(
        {
            "visual_storytelling": {"enabled": False},
            "tts": {"character_mapping": {"narrator": "narrator_female"}},
            "sd": {"positive": "test"},
            "visual": {"safe_fallbacks": ["fallback"]},
            "motiontoon": {
                "enabled": True,
                "video_toon_local_enabled": True,
                "video_toon_workflow_template": "legacy_character_reference_v1",
                "cast_slots": {
                    "protagonist": {"character_id": "young_woman", "aliases": ["lead"]},
                },
            },
        }
    )

    assert result.is_valid is True
    assert any("actor_pool missing" in warning for warning in result.warnings)


def test_public_videotoon_packs_use_actor_pool_contract():
    validator = PackValidator()
    repo_root = Path(__file__).resolve().parents[1]

    for pack_name in ("daily_life_toon", "mystery_toon"):
        settings_path = repo_root / "assets" / "packs" / pack_name / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        motiontoon = settings["motiontoon"]

        result = validator.validate_settings(settings)

        assert result.is_valid is True, f"{pack_name}: {result.errors}"
        assert "actor_pool" in motiontoon
        assert "role_casting_contract" in motiontoon
        assert not any("actor_pool missing" in warning for warning in result.warnings)
        for slot_name, slot_data in motiontoon["cast_slots"].items():
            assert slot_data.get("actor_id"), f"{pack_name}.{slot_name} missing actor_id"
            assert slot_data["actor_id"] in motiontoon["actor_pool"]


def test_public_videotoon_packs_cast_reusable_actor_model_template():
    validator = PackValidator()
    repo_root = Path(__file__).resolve().parents[1]
    actor_model_path = "assets/actor_models/actor_adult_woman_01/actor.json"

    for pack_name in ("daily_life_toon", "mystery_toon"):
        settings_path = repo_root / "assets" / "packs" / pack_name / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        motiontoon = settings["motiontoon"]
        actor_pool = motiontoon["actor_pool"]

        result = validator.validate_settings(settings)

        assert result.is_valid is True, f"{pack_name}: {result.errors}"
        assert actor_pool["actor_adult_woman_01"]["actor_model_path"] == actor_model_path
        assert any(
            slot_data.get("actor_id") == "actor_adult_woman_01"
            for slot_data in motiontoon["cast_slots"].values()
        ), f"{pack_name} does not cast actor_adult_woman_01"

        image_prompt = (repo_root / "assets" / "packs" / pack_name / "prompts" / "image_llm_prompt.txt").read_text(
            encoding="utf-8"
        )
        assert "actor_adult_woman_01" in image_prompt
