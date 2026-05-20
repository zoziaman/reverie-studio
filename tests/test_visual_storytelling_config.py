from config.pack_config import _load_visual_storytelling_config


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
