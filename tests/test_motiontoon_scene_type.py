from utils.motiontoon import infer_scene_type, normalize_motiontoon_config


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
