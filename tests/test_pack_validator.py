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
