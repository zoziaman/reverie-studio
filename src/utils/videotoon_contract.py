from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


DEFAULT_REQUIRED_SCENE_FIELDS = ["scene_id", "role_id", "actor_id", "emotion", "shot_type"]


@dataclass
class VideoToonContractResult:
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


def _coerce_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _get_value(source: Any, key: str, default: Any = "") -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _actor_ids(actor_pool: Mapping[str, Any]) -> set[str]:
    return {str(actor_id) for actor_id in actor_pool.keys() if str(actor_id).strip()}


def role_casting_from_motiontoon_slots(cast_slots: Mapping[str, Any]) -> Dict[str, str]:
    """Build an episode role casting table from pack-level motiontoon slots.

    New packs should use actor_id. Legacy packs may still expose character_id;
    this helper keeps them readable while the pipeline migrates.
    """
    casting: Dict[str, str] = {}
    for role_id, slot_data in _coerce_mapping(cast_slots).items():
        if not isinstance(slot_data, Mapping):
            continue
        actor_id = str(slot_data.get("actor_id") or slot_data.get("character_id") or "").strip()
        if actor_id:
            casting[str(role_id)] = actor_id
            for alias in list(slot_data.get("aliases") or []):
                alias_key = str(alias or "").strip()
                if alias_key:
                    casting.setdefault(alias_key, actor_id)
    return casting


def actor_for_role(role_id: str, role_casting: Mapping[str, Any]) -> str:
    return str(_coerce_mapping(role_casting).get(role_id, "") or "").strip()


def validate_episode_actor_contract(
    episode: Mapping[str, Any],
    actor_pool: Mapping[str, Any],
    *,
    assignment_key: str = "role_casting",
    strict_actor_refs: bool = True,
    allow_background_extras: bool = True,
    required_scene_fields: Optional[Sequence[str]] = None,
) -> VideoToonContractResult:
    """Validate episode role casting and scene-level actor references."""
    result = VideoToonContractResult()
    if not isinstance(episode, Mapping):
        result.add_error("episode must be an object")
        return result

    required_fields = list(required_scene_fields or DEFAULT_REQUIRED_SCENE_FIELDS)
    known_actor_ids = _actor_ids(actor_pool)
    role_casting = episode.get(assignment_key)
    if not isinstance(role_casting, Mapping) or not role_casting:
        result.add_error(f"episode.{assignment_key} must be a non-empty object")
        role_casting = {}

    normalized_casting: Dict[str, str] = {}
    for role_id, actor_id in dict(role_casting).items():
        role_key = str(role_id).strip()
        actor_key = str(actor_id or "").strip()
        if not role_key:
            result.add_error(f"episode.{assignment_key} contains an empty role id")
            continue
        if not actor_key:
            result.add_error(f"episode.{assignment_key}.{role_key} must reference an actor_id")
            continue
        normalized_casting[role_key] = actor_key
        if strict_actor_refs and known_actor_ids and actor_key not in known_actor_ids:
            result.add_error(f"episode.{assignment_key}.{role_key} actor_id '{actor_key}' is not defined in actor_pool")

    scenes = episode.get("scenes", [])
    if scenes is None:
        scenes = []
    if not isinstance(scenes, Iterable) or isinstance(scenes, (str, bytes, Mapping)):
        result.add_error("episode.scenes must be a list")
        return result

    for index, scene in enumerate(list(scenes)):
        scene_path = f"episode.scenes[{index}]"
        if not isinstance(scene, Mapping) and not hasattr(scene, "__dict__"):
            result.add_error(f"{scene_path} must be an object")
            continue

        is_background_extra = bool(_get_value(scene, "is_background_extra", False))
        if is_background_extra and allow_background_extras:
            if not str(_get_value(scene, "scene_id", "") or "").strip():
                result.add_error(f"{scene_path}.scene_id is required")
            continue

        for field_name in required_fields:
            if not str(_get_value(scene, field_name, "") or "").strip():
                result.add_error(f"{scene_path}.{field_name} is required")

        role_id = str(_get_value(scene, "role_id", "") or "").strip()
        actor_id = str(_get_value(scene, "actor_id", "") or "").strip()
        expected_actor = normalized_casting.get(role_id, "")

        if role_id and role_id not in normalized_casting:
            result.add_error(f"{scene_path}.role_id '{role_id}' is not declared in {assignment_key}")
        if actor_id and strict_actor_refs and known_actor_ids and actor_id not in known_actor_ids:
            result.add_error(f"{scene_path}.actor_id '{actor_id}' is not defined in actor_pool")
        if expected_actor and actor_id and actor_id != expected_actor:
            result.add_error(
                f"{scene_path}.actor_id '{actor_id}' does not match {assignment_key}.{role_id} '{expected_actor}'"
            )

    return result


def scene_dicts_from_specs(scenes: Iterable[Any]) -> list[Dict[str, Any]]:
    """Extract contract fields from scene spec objects for validation."""
    scene_dicts: list[Dict[str, Any]] = []
    for scene in scenes or []:
        scene_dicts.append(
            {
                "scene_id": _get_value(scene, "scene_id", ""),
                "role_id": _get_value(scene, "role_id", ""),
                "actor_id": _get_value(scene, "actor_id", ""),
                "emotion": _get_value(scene, "emotion", ""),
                "shot_type": _get_value(scene, "shot_type", ""),
                "is_background_extra": _get_value(scene, "is_background_extra", False),
            }
        )
    return scene_dicts
