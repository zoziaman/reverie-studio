from config.pack_config import _load_motiontoon_config, _load_visual_storytelling_config


def test_load_visual_storytelling_config_reads_character_library():
    config = _load_visual_storytelling_config(
        {
            "visual_storytelling": {
                "enabled": True,
                "sd_model": {"checkpoint": "mistoonAnime_v10Noobai.safetensors"},
                "characters": {
                    "young_woman": {"base": "korean woman", "style": "motiontoon"},
                    "_default": {"base": "fallback"},
                },
                "character_library": {
                    "enabled": True,
                    "auto_generate": True,
                    "preferred_slots": ["protagonist", "elder"],
                    "preferred_expressions": ["neutral", "talking"],
                    "preferred_poses": ["standing", "listening"],
                    "sheet_style": "cutout_sheet",
                    "prioritize_sheet_generation": True,
                },
            }
        }
    )

    assert config.enabled is True
    assert config.character_library.enabled is True
    assert config.character_library.preferred_slots == ["protagonist", "elder"]
    assert config.character_library.preferred_expressions == ["neutral", "talking"]
    assert config.character_library.preferred_poses == ["standing", "listening"]
    assert config.character_library.prioritize_sheet_generation is True


def test_load_motiontoon_config_preserves_actor_pool_contract():
    config = _load_motiontoon_config(
        {
            "motiontoon": {
                "enabled": True,
                "actor_pool": {
                    "actor_woman_01": {
                        "visual_identity": "fixed recurring woman actor",
                        "voice_profile": "female_01",
                    }
                },
                "role_casting_contract": {
                    "enabled": True,
                    "strict_actor_refs": True,
                    "assignment_key": "role_casting",
                },
                "cast_slots": {
                    "victim": {"actor_id": "actor_woman_01"},
                },
            }
        }
    )

    assert config.actor_pool["actor_woman_01"]["voice_profile"] == "female_01"
    assert config.role_casting_contract["strict_actor_refs"] is True
    assert config.cast_slots["victim"]["actor_id"] == "actor_woman_01"
