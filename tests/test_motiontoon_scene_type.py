from utils.motiontoon import build_scene_motion_directive, infer_scene_type, normalize_motiontoon_config


def test_confrontation_takes_precedence_over_prop_keywords():
    text = "\uacc4\uc88c \uc99d\uac70\uac00 \uc788\ub294\ub370, \ub2f9\uc2e0 \uac70\uc9d3\ub9d0 \uadf8\ub9cc\ud574."

    assert infer_scene_type(text, speaker="\uc21c\uc790") == "confrontation"


def test_normalize_motiontoon_config_preserves_actor_pool_contract():
    config = normalize_motiontoon_config(
        {
            "enabled": True,
            "actor_pool": {
                "actor_woman_01": {
                    "visual_identity": "recurring woman actor",
                    "voice_profile": "female_01",
                }
            },
            "role_casting_contract": {
                "enabled": True,
                "strict_actor_refs": True,
                "assignment_key": "role_casting",
            },
        }
    )

    assert config["actor_pool"]["actor_woman_01"]["voice_profile"] == "female_01"
    assert config["role_casting_contract"]["strict_actor_refs"] is True


def test_korean_narrator_aliases_do_not_get_subtitle_pulse():
    config = {"enabled": True, "subtitle_pulse_enabled": True}

    for speaker in ["나레이터", "나레이션", "내레이터", "내레이션", "해설"]:
        directive = build_scene_motion_directive(
            text="모든 일은 그날 시작되었습니다.",
            speaker=speaker,
            duration_frames=90,
            config=config,
        )

        assert "subtitle_pulse" not in directive["primitives"]


def test_character_speaker_keeps_subtitle_pulse():
    directive = build_scene_motion_directive(
        text="제가 직접 확인했어요.",
        speaker="순자",
        duration_frames=90,
        config={"enabled": True, "subtitle_pulse_enabled": True},
    )

    assert "subtitle_pulse" in directive["primitives"]
