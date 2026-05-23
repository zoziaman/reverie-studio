# src/config/pack_validator.py

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.actor_model import validate_actor_model_package

logger = logging.getLogger(__name__)
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ValidationResult:
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def __str__(self) -> str:
        lines: List[str] = []
        if self.errors:
            lines.append(f"[ERRORS] ({len(self.errors)})")
            lines.extend(f"  - {error}" for error in self.errors)
        if self.warnings:
            lines.append(f"[WARNINGS] ({len(self.warnings)})")
            lines.extend(f"  - {warning}" for warning in self.warnings)
        if self.is_valid and not self.warnings:
            lines.append("[OK] Pack validation passed")
        return "\n".join(lines)


class PackValidator:
    VALID_CHANNEL_TYPES = [
        "horror",
        "senior",
        "education",
        "news",
        "entertainment",
        "custom",
        "daily",
        "mystery",
        "videotoon",
    ]
    VALID_COLOR_FILTERS = ["horror", "horror_green", "warm", "cool", "cold", "sepia", "noir", "vintage", "drama", "none"]
    VALID_TRANSITIONS = ["crossfade", "fade_black", "fade_white", "cut", "slide", "zoom"]

    def __init__(self, repo_root: Optional[str | Path] = None) -> None:
        if repo_root is not None:
            self.repo_root = Path(repo_root).resolve()
        elif (DEFAULT_REPO_ROOT / "assets").exists():
            self.repo_root = DEFAULT_REPO_ROOT
        else:
            self.repo_root = None

    def _is_valid_channel_type(self, channel_type: str) -> bool:
        if not channel_type:
            return True
        if channel_type in self.VALID_CHANNEL_TYPES:
            return True
        if "_" in channel_type:
            return channel_type.split("_", 1)[0] in self.VALID_CHANNEL_TYPES
        return False

    def _known_visual_character_ids(self, visual_storytelling: Dict[str, Any]) -> List[str]:
        characters = visual_storytelling.get("characters", {})
        if isinstance(characters, dict):
            return [str(character_id) for character_id in characters if not str(character_id).startswith("_")]
        if isinstance(characters, list):
            ids: List[str] = []
            for character in characters:
                if isinstance(character, dict) and character.get("id"):
                    ids.append(str(character.get("id")))
            return ids
        return []

    def validate_manifest(self, manifest: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult()

        required_aliases = [
            ("pack_id", "package_id"),
            ("pack_name", "package_name"),
            ("genre", "channel_type"),
        ]
        for left, right in required_aliases:
            if left not in manifest and right not in manifest:
                result.add_error(f"manifest: '{left}' or '{right}' is required")

        if "version" not in manifest:
            result.add_error("manifest: 'version' is required")

        version_min = manifest.get("reverie_version_min", manifest.get("min_reverie_version"))
        if version_min is None:
            result.add_warning("manifest: 'reverie_version_min' missing, default compatibility will be assumed")
        elif str(version_min) != "1":
            result.add_error(f"manifest: 'reverie_version_min' must be '1' (got '{version_min}')")

        channel_type = manifest.get("channel_type", manifest.get("genre", ""))
        if channel_type and not self._is_valid_channel_type(channel_type):
            result.add_warning(f"manifest: unsupported channel_type '{channel_type}'")

        package_id = manifest.get("pack_id", manifest.get("package_id", ""))
        if package_id and not re.match(r"^[a-zA-Z0-9_]+$", package_id):
            result.add_warning(f"manifest: pack_id should use only letters, numbers, and underscores ('{package_id}')")

        return result

    def _validate_actor_pool(
        self,
        actor_pool: Dict[str, Any],
        visual_storytelling: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        result = ValidationResult()
        visual_storytelling = visual_storytelling or {}
        known_character_ids = set(self._known_visual_character_ids(visual_storytelling))

        if not isinstance(actor_pool, dict):
            result.add_error("settings.motiontoon.actor_pool must be an object")
            return result

        for actor_id, actor_data in actor_pool.items():
            actor_path = f"settings.motiontoon.actor_pool.{actor_id}"
            if not isinstance(actor_id, str) or not actor_id.strip():
                result.add_error("settings.motiontoon.actor_pool keys must be non-empty actor ids")
                continue
            if not isinstance(actor_data, dict):
                result.add_error(f"{actor_path} must be an object")
                continue

            visual_identity = actor_data.get("visual_identity")
            if not isinstance(visual_identity, str) or not visual_identity.strip():
                result.add_error(f"{actor_path}.visual_identity is required")

            actor_model_path = actor_data.get("actor_model_path")
            actor_model_variants: set[str] = set()
            if actor_model_path is not None:
                if not isinstance(actor_model_path, str) or not actor_model_path.strip():
                    result.add_error(f"{actor_path}.actor_model_path must be a non-empty string")
                elif Path(actor_model_path).is_absolute():
                    result.add_error(f"{actor_path}.actor_model_path must be relative to the repository root")
                elif self.repo_root is None:
                    result.add_warning(f"{actor_path}.actor_model_path was not validated because repo_root is unavailable")
                else:
                    actor_model_result = validate_actor_model_package(actor_model_path, repo_root=self.repo_root)
                    for error in actor_model_result.errors:
                        result.add_error(f"{actor_path}.actor_model_path: {error}")
                    result.warnings.extend(
                        f"{actor_path}.actor_model_path: {warning}" for warning in actor_model_result.warnings
                    )
                    if actor_model_result.is_valid:
                        if actor_model_result.actor_id != actor_id:
                            result.add_error(
                                f"{actor_path}.actor_model_path actor_id '{actor_model_result.actor_id}' "
                                f"does not match actor_pool key '{actor_id}'"
                            )
                        actor_model_variants = set(actor_model_result.required_variants)

            character_id = actor_data.get("character_id")
            if character_id is not None:
                if not isinstance(character_id, str) or not character_id.strip():
                    result.add_error(f"{actor_path}.character_id must be a non-empty string")
                elif known_character_ids and character_id not in known_character_ids:
                    result.add_error(f"{actor_path}.character_id '{character_id}' is not defined in visual_storytelling.characters")

            voice_profile = actor_data.get("voice_profile")
            if voice_profile is not None and not isinstance(voice_profile, str):
                result.add_error(f"{actor_path}.voice_profile must be a string")

            aliases = actor_data.get("aliases")
            if aliases is not None:
                if not isinstance(aliases, list):
                    result.add_error(f"{actor_path}.aliases must be a list")
                elif any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
                    result.add_error(f"{actor_path}.aliases must contain non-empty strings")

            required_variants = actor_data.get("required_variants")
            if required_variants is not None:
                if not isinstance(required_variants, list):
                    result.add_error(f"{actor_path}.required_variants must be a list")
                elif any(not isinstance(variant, str) or not variant.strip() for variant in required_variants):
                    result.add_error(f"{actor_path}.required_variants must contain non-empty strings")
                elif actor_model_variants:
                    missing_model_variants = [
                        variant for variant in required_variants if variant not in actor_model_variants
                    ]
                    if missing_model_variants:
                        result.add_error(
                            f"{actor_path}.required_variants missing from actor_model: "
                            f"{', '.join(missing_model_variants)}"
                        )

            sprite_sheet = actor_data.get("sprite_sheet")
            if sprite_sheet is not None:
                if not isinstance(sprite_sheet, dict):
                    result.add_error(f"{actor_path}.sprite_sheet must be an object")
                elif required_variants:
                    missing_variants = [variant for variant in required_variants if variant not in sprite_sheet]
                    if missing_variants:
                        result.add_warning(
                            f"{actor_path}.sprite_sheet missing required variants: {', '.join(missing_variants)}"
                        )

        return result

    def _validate_role_casting_contract(self, contract: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult()

        if not isinstance(contract, dict):
            result.add_error("settings.motiontoon.role_casting_contract must be an object")
            return result

        for field_name in ("enabled", "strict_actor_refs", "allow_background_extras"):
            value = contract.get(field_name)
            if value is not None and not isinstance(value, bool):
                result.add_error(f"settings.motiontoon.role_casting_contract.{field_name} must be a bool")

        assignment_key = contract.get("assignment_key")
        if assignment_key is not None and not isinstance(assignment_key, str):
            result.add_error("settings.motiontoon.role_casting_contract.assignment_key must be a string")

        required_scene_fields = contract.get("required_scene_fields")
        if required_scene_fields is not None:
            if not isinstance(required_scene_fields, list):
                result.add_error("settings.motiontoon.role_casting_contract.required_scene_fields must be a list")
            elif any(not isinstance(field_name, str) or not field_name.strip() for field_name in required_scene_fields):
                result.add_error(
                    "settings.motiontoon.role_casting_contract.required_scene_fields must contain non-empty strings"
                )

        return result

    def _validate_motiontoon(
        self,
        motiontoon: Dict[str, Any],
        visual_storytelling: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        result = ValidationResult()

        if not isinstance(motiontoon, dict):
            result.add_error("settings.motiontoon must be an object")
            return result

        bool_fields = [
            "enabled",
            "blink_enabled",
            "mouth_flap_enabled",
            "layered_cutout_enabled",
            "prop_overlay_enabled",
            "dialogue_panel_enabled",
            "idle_drift_enabled",
            "impact_shake_enabled",
            "snap_zoom_enabled",
            "subtitle_pulse_enabled",
            "slow_push_enabled",
            "shorts_vertical_ready",
            "video_toon_local_enabled",
            "video_toon_layered_assets_required",
        ]
        for field_name in bool_fields:
            value = motiontoon.get(field_name)
            if value is not None and not isinstance(value, bool):
                result.add_error(f"settings.motiontoon.{field_name} must be a bool")

        if motiontoon.get("mode") is not None and not isinstance(motiontoon.get("mode"), str):
            result.add_error("settings.motiontoon.mode must be a string")

        profile = motiontoon.get("profile")
        if profile is not None:
            if not isinstance(profile, str):
                result.add_error("settings.motiontoon.profile must be a string")
            elif profile not in {"none", "basic", "gishini", "advanced", "screen_space", "classic"}:
                result.add_error("settings.motiontoon.profile must be one of: none, basic, gishini")

        overlay_theme = motiontoon.get("overlay_theme")
        if overlay_theme is not None:
            if not isinstance(overlay_theme, str):
                result.add_error("settings.motiontoon.overlay_theme must be a string")
            elif overlay_theme not in {"default", "scam_alert", "life_saguk", "daily_life", "mystery"}:
                result.add_error(
                    "settings.motiontoon.overlay_theme must be one of: default, scam_alert, life_saguk, daily_life, mystery"
                )

        if motiontoon.get("default_scene_type") is not None and not isinstance(motiontoon.get("default_scene_type"), str):
            result.add_error("settings.motiontoon.default_scene_type must be a string")

        video_toon_backend = motiontoon.get("video_toon_generation_backend")
        if video_toon_backend is not None:
            if not isinstance(video_toon_backend, str):
                result.add_error("settings.motiontoon.video_toon_generation_backend must be a string")
            elif video_toon_backend not in {"comfyui", "sd_webui"}:
                result.add_error("settings.motiontoon.video_toon_generation_backend must be one of: comfyui, sd_webui")

        video_toon_workflow = motiontoon.get("video_toon_workflow_template")
        if video_toon_workflow is not None and not isinstance(video_toon_workflow, str):
            result.add_error("settings.motiontoon.video_toon_workflow_template must be a string")
        elif motiontoon.get("video_toon_local_enabled") is True and not str(video_toon_workflow or "").strip():
            result.add_error("settings.motiontoon.video_toon_workflow_template is required when video_toon_local_enabled=true")

        layered_cutout_strength = motiontoon.get("layered_cutout_strength")
        if layered_cutout_strength is not None:
            if not isinstance(layered_cutout_strength, (int, float)):
                result.add_error("settings.motiontoon.layered_cutout_strength must be a number")
            elif not (0.1 <= float(layered_cutout_strength) <= 1.5):
                result.add_error("settings.motiontoon.layered_cutout_strength must be between 0.1 and 1.5")

        prop_keywords = motiontoon.get("prop_keywords")
        if prop_keywords is not None and not isinstance(prop_keywords, (list, dict)):
            result.add_error("settings.motiontoon.prop_keywords must be a list or object")

        scene_motion_rules = motiontoon.get("scene_motion_rules")
        if scene_motion_rules is not None and not isinstance(scene_motion_rules, dict):
            result.add_error("settings.motiontoon.scene_motion_rules must be an object")

        actor_pool = motiontoon.get("actor_pool")
        actor_pool_ids: set[str] = set()
        if actor_pool is not None:
            actor_result = self._validate_actor_pool(actor_pool, visual_storytelling=visual_storytelling)
            result.errors.extend(actor_result.errors)
            result.warnings.extend(actor_result.warnings)
            if actor_result.errors:
                result.is_valid = False
            if isinstance(actor_pool, dict):
                actor_pool_ids = {str(actor_id) for actor_id in actor_pool.keys()}
        elif motiontoon.get("video_toon_local_enabled") is True and motiontoon.get("cast_slots"):
            result.add_warning("settings.motiontoon.actor_pool missing; video-toon pack will use legacy character_id slots")

        role_contract = motiontoon.get("role_casting_contract")
        if role_contract is not None:
            contract_result = self._validate_role_casting_contract(role_contract)
            result.errors.extend(contract_result.errors)
            result.warnings.extend(contract_result.warnings)
            if contract_result.errors:
                result.is_valid = False

        cast_slots = motiontoon.get("cast_slots")
        if cast_slots is not None:
            if not isinstance(cast_slots, dict):
                result.add_error("settings.motiontoon.cast_slots must be an object")
            else:
                for slot_name, slot_data in cast_slots.items():
                    if not isinstance(slot_data, dict):
                        result.add_error(f"settings.motiontoon.cast_slots.{slot_name} must be an object")
                        continue
                    if "character_id" in slot_data and not isinstance(slot_data.get("character_id"), str):
                        result.add_error(f"settings.motiontoon.cast_slots.{slot_name}.character_id must be a string")
                    if "actor_id" in slot_data and not isinstance(slot_data.get("actor_id"), str):
                        result.add_error(f"settings.motiontoon.cast_slots.{slot_name}.actor_id must be a string")
                    if not slot_data.get("actor_id") and not slot_data.get("character_id"):
                        result.add_error(
                            f"settings.motiontoon.cast_slots.{slot_name} must define actor_id or legacy character_id"
                        )
                    if slot_data.get("actor_id") and actor_pool_ids and slot_data.get("actor_id") not in actor_pool_ids:
                        result.add_error(
                            f"settings.motiontoon.cast_slots.{slot_name}.actor_id '{slot_data.get('actor_id')}' is not defined in actor_pool"
                        )
                    aliases = slot_data.get("aliases")
                    if aliases is not None and not isinstance(aliases, list):
                        result.add_error(f"settings.motiontoon.cast_slots.{slot_name}.aliases must be a list")

        puppet_profiles = motiontoon.get("puppet_profiles")
        if puppet_profiles is not None:
            if not isinstance(puppet_profiles, dict):
                result.add_error("settings.motiontoon.puppet_profiles must be an object")
            else:
                for profile_name, profile_data in puppet_profiles.items():
                    if not isinstance(profile_data, dict):
                        result.add_error(f"settings.motiontoon.puppet_profiles.{profile_name} must be an object")

        return result

    def _validate_visual_storytelling(self, vs: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult()

        if "enabled" not in vs:
            result.add_warning("visual_storytelling: 'enabled' missing, default false will be assumed")

        characters = vs.get("characters")
        if characters is None:
            if vs.get("enabled", False):
                result.add_error("visual_storytelling: 'characters' is required when enabled=true")
        elif isinstance(characters, list):
            for index, char in enumerate(characters):
                if not isinstance(char, dict):
                    result.add_error(f"visual_storytelling: characters[{index}] must be an object")
                    continue
                if "id" not in char:
                    result.add_warning(f"visual_storytelling: characters[{index}].id missing")
                if "base_prompt" not in char and "base" not in char:
                    result.add_warning(f"visual_storytelling: characters[{index}].base_prompt missing")
        elif isinstance(characters, dict):
            if "_default" not in characters:
                result.add_warning("visual_storytelling: characters._default missing")
            for char_id, char_def in characters.items():
                if char_id.startswith("_"):
                    continue
                if not isinstance(char_def, dict):
                    result.add_error(f"visual_storytelling: characters.{char_id} must be an object")
                    continue
                if "base" not in char_def and "base_prompt" not in char_def:
                    result.add_warning(f"visual_storytelling: characters.{char_id}.base missing")
        else:
            result.add_error(f"visual_storytelling: 'characters' has invalid type '{type(characters).__name__}'")

        sd_model = vs.get("sd_model", {})
        if vs.get("enabled", False) and not sd_model.get("checkpoint"):
            result.add_warning("visual_storytelling: sd_model.checkpoint missing")

        image_generation = vs.get("image_generation", {})
        if image_generation:
            target = image_generation.get("target_images", 0)
            min_images = image_generation.get("min_images", 0)
            max_images = image_generation.get("max_images", 0)
            if min_images > max_images and max_images > 0:
                result.add_error(f"visual_storytelling: min_images({min_images}) > max_images({max_images})")
            if target > 0 and (target < min_images or target > max_images):
                result.add_warning(f"visual_storytelling: target_images({target}) is outside [{min_images}, {max_images}]")

        character_library = vs.get("character_library", {})
        if character_library:
            if not isinstance(character_library, dict):
                result.add_error("visual_storytelling: character_library must be an object")
            else:
                for key in ("preferred_slots", "preferred_expressions", "preferred_poses", "required_variant_keys"):
                    value = character_library.get(key, [])
                    if value and not isinstance(value, list):
                        result.add_error(f"visual_storytelling: character_library.{key} must be a list")
                required_by_slot = character_library.get("required_variant_keys_by_slot", {})
                if required_by_slot and not isinstance(required_by_slot, dict):
                    result.add_error("visual_storytelling: character_library.required_variant_keys_by_slot must be an object")
                elif isinstance(required_by_slot, dict):
                    for slot_name, slot_values in required_by_slot.items():
                        if slot_values and not isinstance(slot_values, list):
                            result.add_error(
                                f"visual_storytelling: character_library.required_variant_keys_by_slot.{slot_name} must be a list"
                            )

        effects = vs.get("visual_effects", {})
        if effects:
            color_filter = effects.get("color_filter", "")
            if isinstance(color_filter, dict):
                color_filter = color_filter.get("type", "")
            if color_filter and color_filter not in self.VALID_COLOR_FILTERS:
                result.add_warning(f"visual_storytelling: unsupported color_filter '{color_filter}'")

        transitions = effects.get("transitions", {}) if effects else {}
        if not transitions:
            transitions = vs.get("transitions", {})
        if transitions:
            default_transition = transitions.get("default", transitions.get("default_transition", ""))
            if default_transition and default_transition not in self.VALID_TRANSITIONS:
                result.add_warning(f"visual_storytelling: unsupported transition '{default_transition}'")

        return result

    def _validate_background_library(self, bg: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult()

        if not isinstance(bg, dict):
            result.add_error("background_library must be an object")
            return result

        if "profile" in bg and not isinstance(bg.get("profile"), str):
            result.add_error("background_library.profile must be a string")
        if "style_prompt" in bg and not isinstance(bg.get("style_prompt"), str):
            result.add_error("background_library.style_prompt must be a string")
        if "negative_prompt" in bg and not isinstance(bg.get("negative_prompt"), str):
            result.add_error("background_library.negative_prompt must be a string")
        if "images_per_location" in bg and not isinstance(bg.get("images_per_location"), int):
            result.add_error("background_library.images_per_location must be an integer")

        templates = bg.get("location_templates", {})
        if templates and not isinstance(templates, dict):
            result.add_error("background_library.location_templates must be an object")
        elif isinstance(templates, dict):
            for template_name, template_data in templates.items():
                if not isinstance(template_data, dict):
                    result.add_error(f"background_library.location_templates.{template_name} must be an object")
                    continue
                if not isinstance(template_data.get("base_prompt", ""), str) or not template_data.get("base_prompt", ""):
                    result.add_error(f"background_library.location_templates.{template_name}.base_prompt is required")
                keywords = template_data.get("keywords", [])
                if keywords and not isinstance(keywords, list):
                    result.add_error(f"background_library.location_templates.{template_name}.keywords must be a list")

        return result

    def validate_settings(self, settings: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult()

        visual_storytelling = settings.get("visual_storytelling", {})
        if visual_storytelling:
            vs_result = self._validate_visual_storytelling(visual_storytelling)
            result.errors.extend(vs_result.errors)
            result.warnings.extend(vs_result.warnings)
            if vs_result.errors:
                result.is_valid = False
        else:
            result.add_warning("settings: 'visual_storytelling' missing")

        tts = settings.get("tts", {})
        if not tts:
            result.add_warning("settings: 'tts' missing")
        elif not tts.get("character_mapping"):
            result.add_warning("settings: tts.character_mapping missing")

        sd = settings.get("sd", {})
        if not sd:
            result.add_warning("settings: 'sd' missing")

        visual = settings.get("visual", {})
        if not visual.get("safe_fallbacks"):
            result.add_warning("settings: visual.safe_fallbacks missing")

        motiontoon = settings.get("motiontoon", {})
        if motiontoon:
            mt_result = self._validate_motiontoon(motiontoon, visual_storytelling=visual_storytelling)
            result.errors.extend(mt_result.errors)
            result.warnings.extend(mt_result.warnings)
            if mt_result.errors:
                result.is_valid = False

        background_library = settings.get("background_library", {})
        if background_library:
            bg_result = self._validate_background_library(background_library)
            result.errors.extend(bg_result.errors)
            result.warnings.extend(bg_result.warnings)
            if bg_result.errors:
                result.is_valid = False

        script_quality = settings.get("script_quality", {})
        if script_quality:
            if not isinstance(script_quality, dict):
                result.add_error("settings.script_quality must be an object")
            else:
                if "min_non_narrator_roles" in script_quality and not isinstance(
                    script_quality.get("min_non_narrator_roles"), int
                ):
                    result.add_error("settings.script_quality.min_non_narrator_roles must be an int")
                for key in ("max_narration_ratio", "max_ellipsis_ratio", "warn_topic_overlap_ratio"):
                    if key in script_quality and not isinstance(script_quality.get(key), (int, float)):
                        result.add_error(f"settings.script_quality.{key} must be a number")
                if "min_turns_for_gate" in script_quality and not isinstance(
                    script_quality.get("min_turns_for_gate"), int
                ):
                    result.add_error("settings.script_quality.min_turns_for_gate must be an int")

        return result

    def validate_pack(
        self,
        manifest: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
        pack_data: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        result = ValidationResult()

        if pack_data and not manifest:
            manifest = pack_data
            settings = pack_data

        if manifest:
            manifest_result = self.validate_manifest(manifest)
            result.errors.extend(manifest_result.errors)
            result.warnings.extend(manifest_result.warnings)
            if manifest_result.errors:
                result.is_valid = False
        else:
            result.add_error("manifest data is missing")

        if settings:
            settings_result = self.validate_settings(settings)
            result.errors.extend(settings_result.errors)
            result.warnings.extend(settings_result.warnings)
            if settings_result.errors:
                result.is_valid = False
        else:
            result.add_warning("settings data is missing")

        return result

    def validate_and_log(self, pack_data: Dict[str, Any], pack_name: str = "unknown") -> Tuple[bool, ValidationResult]:
        result = self.validate_pack(pack_data=pack_data)

        if result.errors:
            logger.error(f"[PackValidator] '{pack_name}' failed validation:")
            for error in result.errors:
                logger.error(f"  [ERROR] {error}")

        if result.warnings:
            for warning in result.warnings:
                logger.warning(f"[PackValidator] '{pack_name}': {warning}")

        if result.is_valid:
            logger.info(f"[PackValidator] '{pack_name}' validation passed")

        return result.is_valid, result


pack_validator = PackValidator()


def validate_pack(pack_data: Dict[str, Any], pack_name: str = "unknown") -> Tuple[bool, ValidationResult]:
    return pack_validator.validate_and_log(pack_data, pack_name)
