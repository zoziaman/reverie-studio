from types import SimpleNamespace

from utils.videotoon_contract import (
    role_casting_from_motiontoon_slots,
    scene_dicts_from_specs,
    validate_episode_actor_contract,
)


def test_role_casting_from_motiontoon_slots_prefers_actor_id():
    casting = role_casting_from_motiontoon_slots(
        {
            "victim": {"actor_id": "actor_woman_01", "character_id": "legacy_woman", "aliases": ["lead"]},
            "suspect": {"character_id": "legacy_suspect"},
            "empty": {},
        }
    )

    assert casting == {
        "victim": "actor_woman_01",
        "lead": "actor_woman_01",
        "suspect": "legacy_suspect",
    }


def test_validate_episode_actor_contract_accepts_cast_scenes():
    result = validate_episode_actor_contract(
        {
            "episode_id": "used_market_scam",
            "role_casting": {
                "victim": "actor_woman_01",
                "scammer": "actor_man_01",
            },
            "scenes": [
                {
                    "scene_id": "scene_0001",
                    "role_id": "victim",
                    "actor_id": "actor_woman_01",
                    "emotion": "fear",
                    "shot_type": "medium_close",
                },
                {
                    "scene_id": "scene_0002",
                    "role_id": "scammer",
                    "actor_id": "actor_man_01",
                    "emotion": "smirk",
                    "shot_type": "prop_reveal",
                },
            ],
        },
        {
            "actor_woman_01": {"visual_identity": "fixed woman actor"},
            "actor_man_01": {"visual_identity": "fixed man actor"},
        },
    )

    assert result.is_valid is True
    assert result.errors == []


def test_validate_episode_actor_contract_rejects_scene_actor_mismatch():
    result = validate_episode_actor_contract(
        {
            "episode_id": "used_market_scam",
            "role_casting": {"victim": "actor_woman_01"},
            "scenes": [
                {
                    "scene_id": "scene_0001",
                    "role_id": "victim",
                    "actor_id": "actor_man_01",
                    "emotion": "fear",
                    "shot_type": "medium_close",
                }
            ],
        },
        {
            "actor_woman_01": {"visual_identity": "fixed woman actor"},
            "actor_man_01": {"visual_identity": "fixed man actor"},
        },
    )

    assert result.is_valid is False
    assert any("does not match" in error for error in result.errors)


def test_validate_episode_actor_contract_rejects_unknown_role_and_actor():
    result = validate_episode_actor_contract(
        {
            "episode_id": "used_market_scam",
            "role_casting": {"victim": "actor_woman_01"},
            "scenes": [
                {
                    "scene_id": "scene_0001",
                    "role_id": "detective",
                    "actor_id": "actor_unknown_99",
                    "emotion": "neutral",
                    "shot_type": "wide",
                }
            ],
        },
        {"actor_woman_01": {"visual_identity": "fixed woman actor"}},
    )

    assert result.is_valid is False
    assert any("detective" in error and "role_casting" in error for error in result.errors)
    assert any("actor_unknown_99" in error and "actor_pool" in error for error in result.errors)


def test_validate_episode_actor_contract_allows_background_extra_without_actor():
    result = validate_episode_actor_contract(
        {
            "episode_id": "used_market_scam",
            "role_casting": {"victim": "actor_woman_01"},
            "scenes": [
                {
                    "scene_id": "scene_bg_0001",
                    "is_background_extra": True,
                    "shot_type": "street_wide",
                }
            ],
        },
        {"actor_woman_01": {"visual_identity": "fixed woman actor"}},
    )

    assert result.is_valid is True
    assert result.errors == []


def test_scene_dicts_from_specs_extracts_scene_contract_fields():
    scene_dicts = scene_dicts_from_specs(
        [
            SimpleNamespace(
                scene_id="scene_0001",
                role_id="victim",
                actor_id="actor_woman_01",
                emotion="fear",
                shot_type="medium_close",
                is_background_extra=False,
            )
        ]
    )

    assert scene_dicts == [
        {
            "scene_id": "scene_0001",
            "role_id": "victim",
            "actor_id": "actor_woman_01",
            "emotion": "fear",
            "shot_type": "medium_close",
            "is_background_extra": False,
        }
    ]
