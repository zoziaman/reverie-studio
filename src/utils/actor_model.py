from __future__ import annotations

import argparse
import copy
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Optional

from PIL import Image, ImageDraw


REQUIRED_PROMPT_FILES = (
    "prompts/identity_prompt.txt",
    "prompts/variant_prompt.txt",
    "prompts/mouth_prompt.txt",
    "prompts/negative_prompt.txt",
    "references/README.md",
    "qa/actor_model_checklist.md",
)
FORBIDDEN_PUBLIC_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".wav",
    ".mp3",
    ".flac",
    ".mp4",
    ".mov",
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".onnx",
    ".pickle",
    ".pkl",
}
LOCAL_ACTOR_MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
READINESS_STATES = {"template", "draft", "ready_for_test", "approved", "retired"}
PRIVATE_TEXT_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(re.escape("C:" + "\\" + "Users" + "\\"), re.IGNORECASE),
    re.compile(re.escape("C:" + "/" + "Users" + "/"), re.IGNORECASE),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH |PRIVATE )?PRIVATE KEY-----"),
)
ACTOR_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
ASSET_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
DEFAULT_REQUIRED_VARIANTS = (
    "neutral_standing",
    "talking_standing",
    "blink_standing",
    "happy_standing",
    "sad_standing",
    "angry_standing",
    "worried_standing",
    "scared_standing",
    "neutral_seated",
    "talking_seated",
)
DEFAULT_MOUTH_SHAPES = (
    "mouth_closed",
    "mouth_small_open",
    "mouth_wide_open",
    "mouth_round",
)
DEFAULT_EYE_SHAPES = (
    "eyes_open",
    "eyes_closed",
    "eyes_worried",
    "eyes_angry",
)
DEFAULT_ROLE_RANGE = (
    "lead",
    "support",
    "witness",
    "neighbor",
)
DEFAULT_PRESET_CATALOG_PATH = Path("assets") / "actor_model_presets" / "catalog.json"
GOLD_TEMPLATE_GOAL_ID = "gold_reusable_video_toon_actor_v1"
DEFAULT_TEMPLATE_GOAL_ID = "reusable_video_toon_actor_v1"
DEFAULT_REUSE_SURFACES = (
    "pack_actor_pool",
    "episode_role_casting",
    "scene_variant_selection",
    "mouth_flap_layering",
    "eye_blink_layering",
    "thumbnail_composition",
    "omnibus_role_swap",
)
DEFAULT_REUSE_CONTEXTS = (
    "daily_life",
    "mystery",
    "family",
    "office",
    "school",
    "saguk",
    "thumbnail",
    "shorts",
)
PRESET_REQUIRED_FIELDS = (
    "display_name",
    "age_band",
    "gender_presentation",
    "genre_tags",
    "role_range",
    "visual_identity",
    "voice_profile",
)
DEFAULT_ROLE_CASTING_CONTRACT = {
    "enabled": True,
    "strict_actor_refs": True,
    "allow_background_extras": True,
    "assignment_key": "role_casting",
    "required_scene_fields": ["scene_id", "role_id", "actor_id", "emotion", "shot_type"],
}
DEFAULT_REUSE_CONTRACT = {
    "identity_is_fixed": True,
    "roles_may_change_by_episode": True,
    "background_may_change_by_episode": True,
    "wardrobe_policy": "base_silhouette_locked_pack_overrides_only",
    "allowed_pack_overrides": [
        "small accessory",
        "outerwear color",
        "occupation prop",
        "genre-safe wardrobe detail",
    ],
    "must_not_change": [
        "age band",
        "face shape",
        "hair silhouette",
        "body proportions",
        "primary clothing silhouette",
        "stable voice slot",
    ],
    "requires_asset_coverage_before_render": True,
}
DEFAULT_LAYERING_CONTRACT = {
    "image_format": "png_rgba",
    "canvas": {
        "width": 1024,
        "height": 1536,
    },
    "anchor_points": {
        "actor_root": {"x": 0.5, "y": 0.92},
        "head_center": {"x": 0.5, "y": 0.28},
        "eye_center": {"x": 0.5, "y": 0.25},
        "mouth_center": {"x": 0.5, "y": 0.38},
    },
    "layer_order": ["variant_base", "eye_layer", "mouth_layer"],
    "naming_policy": {
        "variant": "variants/{variant_key}.png",
        "mouth_shape": "face_parts/{mouth_shape_key}.png",
        "eye_shape": "face_parts/{eye_shape_key}.png",
    },
}


@dataclass
class ActorModelValidationResult:
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    actor_id: str = ""
    required_variants: list[str] = field(default_factory=list)
    mouth_shapes: list[str] = field(default_factory=list)
    eye_shapes: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and str(item).strip()]


def _is_safe_asset_key(value: str) -> bool:
    return bool(ASSET_KEY_PATTERN.fullmatch(value))


def _validate_asset_keys(field_name: str, values: list[str], result: ActorModelValidationResult) -> None:
    for value in values:
        if not _is_safe_asset_key(value):
            result.add_error(
                f"{field_name} contains unsafe asset key '{value}'; "
                "use letters, numbers, underscores, or hyphens only"
            )


def _safe_actor_asset_path(actor_dir: Path, relative_path: str) -> Path:
    path_text = str(relative_path or "").strip().replace("\\", "/")
    if not path_text:
        raise ValueError("actor asset target_relative_path is required")
    raw_path = Path(path_text)
    windows_path = PureWindowsPath(path_text)
    if raw_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError(f"actor asset path must be relative: {relative_path}")
    if any(part in {"", ".", ".."} for part in path_text.split("/")):
        raise ValueError(f"actor asset path must stay inside actor model package: {relative_path}")

    actor_root = actor_dir.resolve()
    target_path = (actor_root / raw_path).resolve()
    if target_path != actor_root and actor_root not in target_path.parents:
        raise ValueError(f"actor asset path must stay inside actor model package: {relative_path}")
    return target_path


def _coerce_string_list(value: Any, default: tuple[str, ...]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return _string_list(value)


def _normalize_aliases(value: Any) -> list[str]:
    return _coerce_string_list(value, ())


def _resolve_actor_path(actor_model_path: Path | str, repo_root: Optional[Path | str]) -> tuple[Path, Optional[str]]:
    raw_path = Path(actor_model_path)
    root = Path(repo_root).resolve() if repo_root is not None else None
    resolved = raw_path.resolve() if raw_path.is_absolute() else ((root or Path.cwd()) / raw_path).resolve()

    if root is not None and not (resolved == root or root in resolved.parents):
        return resolved, "actor_model_path must stay inside repo_root"
    return resolved, None


def _load_actor_json(actor_path: Path, result: ActorModelValidationResult) -> dict[str, Any]:
    try:
        data = json.loads(actor_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.add_error(f"{actor_path.name} must be valid JSON: {exc}")
        return {}
    if not isinstance(data, dict):
        result.add_error(f"{actor_path.name} must contain a JSON object")
        return {}
    return data


def _read_template(actor_dir: Path, relative_path: str) -> str:
    return (actor_dir / relative_path).read_text(encoding="utf-8").strip()


def _relative_to_root(path: Path, repo_root: Optional[Path | str]) -> str:
    if repo_root is None:
        return (Path(path.parent.name) / path.name).as_posix()
    root = Path(repo_root).resolve()
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return (Path(path.parent.name) / path.name).as_posix()


def _variant_parts(variant_key: str) -> tuple[str, str]:
    expression, _, pose = variant_key.partition("_")
    return expression or variant_key, pose or "standing"


def _resolve_actor_root(actor_root: Optional[Path | str], repo_root: Optional[Path | str]) -> Path:
    root = Path(repo_root).resolve() if repo_root is not None else None
    if actor_root is None:
        return ((root or Path.cwd()) / "assets" / "actor_models").resolve()

    raw_root = Path(actor_root)
    resolved = raw_root.resolve() if raw_root.is_absolute() else ((root or Path.cwd()) / raw_root).resolve()
    if root is not None and not (resolved == root or root in resolved.parents):
        raise ValueError("actor_root must stay inside repo_root")
    return resolved


def _resolve_preset_catalog_path(catalog_path: Optional[Path | str], repo_root: Optional[Path | str]) -> Path:
    root = Path(repo_root).resolve() if repo_root is not None else None
    raw_path = Path(catalog_path) if catalog_path is not None else DEFAULT_PRESET_CATALOG_PATH
    return raw_path.resolve() if raw_path.is_absolute() else ((root or Path.cwd()) / raw_path).resolve()


def _write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _default_display_name(actor_id: str) -> str:
    return " ".join(part.capitalize() for part in actor_id.split("_"))


def _default_template_goal(actor_id: str, *, is_primary_template: bool = False) -> dict[str, Any]:
    goal_id = GOLD_TEMPLATE_GOAL_ID if is_primary_template else DEFAULT_TEMPLATE_GOAL_ID
    return {
        "goal_id": goal_id,
        "is_primary_template": is_primary_template,
        "target_actor_id": actor_id,
        "target_use": "single fixed video-toon actor reusable across packs, episodes, roles, dialogue layers, and thumbnails",
        "reuse_surfaces": list(DEFAULT_REUSE_SURFACES),
    }


def _normalize_template_goal(actor_id: str, value: Any) -> dict[str, Any]:
    goal = _default_template_goal(actor_id)
    if isinstance(value, Mapping):
        for key in ("goal_id", "target_actor_id", "target_use"):
            if str(value.get(key) or "").strip():
                goal[key] = str(value[key]).strip()
        if isinstance(value.get("is_primary_template"), bool):
            goal["is_primary_template"] = bool(value["is_primary_template"])
        surfaces = _string_list(value.get("reuse_surfaces"))
        if surfaces:
            goal["reuse_surfaces"] = surfaces
    return goal


def _normalize_reuse_contract(value: Any) -> dict[str, Any]:
    contract = copy.deepcopy(DEFAULT_REUSE_CONTRACT)
    if isinstance(value, Mapping):
        for key in (
            "identity_is_fixed",
            "roles_may_change_by_episode",
            "background_may_change_by_episode",
            "requires_asset_coverage_before_render",
        ):
            if isinstance(value.get(key), bool):
                contract[key] = bool(value[key])
        if str(value.get("wardrobe_policy") or "").strip():
            contract["wardrobe_policy"] = str(value["wardrobe_policy"]).strip()
        for key in ("allowed_pack_overrides", "must_not_change"):
            items = _string_list(value.get(key))
            if items:
                contract[key] = items
    return contract


def _normalize_layering_contract(value: Any) -> dict[str, Any]:
    contract = copy.deepcopy(DEFAULT_LAYERING_CONTRACT)
    if not isinstance(value, Mapping):
        return contract

    if str(value.get("image_format") or "").strip():
        contract["image_format"] = str(value["image_format"]).strip()
    canvas = value.get("canvas")
    if isinstance(canvas, Mapping):
        for key in ("width", "height"):
            try:
                number = int(canvas.get(key) or 0)
            except (TypeError, ValueError):
                number = 0
            if number > 0:
                contract["canvas"][key] = number
    anchors = value.get("anchor_points")
    if isinstance(anchors, Mapping):
        for anchor_key, anchor_value in anchors.items():
            if not isinstance(anchor_value, Mapping):
                continue
            try:
                x = float(anchor_value.get("x"))
                y = float(anchor_value.get("y"))
            except (TypeError, ValueError):
                continue
            contract["anchor_points"][str(anchor_key)] = {"x": x, "y": y}
    layer_order = _string_list(value.get("layer_order"))
    if layer_order:
        contract["layer_order"] = layer_order
    naming_policy = value.get("naming_policy")
    if isinstance(naming_policy, Mapping):
        for key in ("variant", "mouth_shape", "eye_shape"):
            if str(naming_policy.get(key) or "").strip():
                contract["naming_policy"][key] = str(naming_policy[key]).strip()
    return contract


def _validate_layering_contract(data: Mapping[str, Any], result: ActorModelValidationResult) -> None:
    contract = data.get("layering_contract")
    if not isinstance(contract, Mapping):
        result.add_error("layering_contract must be an object")
        return

    if not str(contract.get("image_format") or "").strip():
        result.add_error("layering_contract.image_format must be a non-empty string")

    canvas = contract.get("canvas")
    if not isinstance(canvas, Mapping):
        result.add_error("layering_contract.canvas must be an object")
    else:
        for key in ("width", "height"):
            if not isinstance(canvas.get(key), int) or int(canvas.get(key)) <= 0:
                result.add_error(f"layering_contract.canvas.{key} must be a positive integer")

    anchors = contract.get("anchor_points")
    if not isinstance(anchors, Mapping):
        result.add_error("layering_contract.anchor_points must be an object")
    else:
        for required_anchor in ("actor_root", "mouth_center", "eye_center"):
            anchor = anchors.get(required_anchor)
            if not isinstance(anchor, Mapping):
                result.add_error(f"layering_contract.anchor_points.{required_anchor} must be an object")
                continue
            for axis in ("x", "y"):
                value = anchor.get(axis)
                if not isinstance(value, (int, float)):
                    result.add_error(f"layering_contract.anchor_points.{required_anchor}.{axis} must be numeric")

    layer_order = _string_list(contract.get("layer_order"))
    if not layer_order:
        result.add_error("layering_contract.layer_order must be a non-empty string list")
    else:
        for required_layer in ("variant_base", "eye_layer", "mouth_layer"):
            if required_layer not in layer_order:
                result.add_error(f"layering_contract.layer_order must include {required_layer}")

    naming_policy = contract.get("naming_policy")
    if not isinstance(naming_policy, Mapping):
        result.add_error("layering_contract.naming_policy must be an object")
        return
    for key, placeholder, sample in (
        ("variant", "variant_key", "neutral_standing"),
        ("mouth_shape", "mouth_shape_key", "mouth_closed"),
        ("eye_shape", "eye_shape_key", "eyes_open"),
    ):
        pattern = str(naming_policy.get(key) or "").strip()
        if not pattern:
            result.add_error(f"layering_contract.naming_policy.{key} must be a non-empty string")
            continue
        target = _target_from_naming_policy(pattern, **{placeholder: sample})
        try:
            _safe_actor_asset_path(Path("_actor_model_package"), target)
        except ValueError:
            result.add_error(f"layering_contract.naming_policy.{key} must resolve inside actor model package")


def _variant_groups(variants: list[str], mouth_shapes: list[str], eye_shapes: list[str]) -> dict[str, list[str]]:
    core_expressions = {"neutral", "talking", "blink"}
    core_variants: list[str] = []
    emotion_variants: list[str] = []
    poses: list[str] = []
    for variant in variants:
        expression, pose = _variant_parts(variant)
        if expression in core_expressions:
            core_variants.append(variant)
        else:
            emotion_variants.append(variant)
        if pose and pose not in poses:
            poses.append(pose)
    return {
        "core_variants": core_variants,
        "emotion_variants": emotion_variants,
        "poses": poses,
        "mouth_shapes": list(mouth_shapes),
        "eye_shapes": list(eye_shapes),
    }


def _identity_prompt_text(
    *,
    actor_id: str,
    age_band: str,
    gender_presentation: str,
    visual_identity: str,
) -> str:
    return f"""
Create or maintain {actor_id} as the same reusable {age_band} {gender_presentation}
video-toon actor in every variant.

Visual identity:
{visual_identity}

Keep stable:
- Age band.
- Same face shape and facial proportions.
- Same hair silhouette.
- Same ordinary body proportions.
- Same primary clothing silhouette unless a pack explicitly overrides wardrobe.

Use clean Korean webtoon video-toon cutout style, readable expression, cel
shading, and waist-up or half-body framing for layered compositing.
"""


def _variant_prompt_text(actor_id: str, required_variants: list[str]) -> str:
    variant_lines = "\n".join(f"- {variant}" for variant in required_variants)
    return f"""
Generate the requested expression and pose for {actor_id} while preserving the
actor identity.

Variant key format:
expression_pose

Required starter variants:
{variant_lines}

The pose may change, but the actor's face shape, age band, hair silhouette,
body proportions, and primary clothing silhouette must stay consistent.
"""


def _mouth_prompt_text(actor_id: str, mouth_shapes: list[str]) -> str:
    mouth_lines = "\n".join(f"- {shape}" for shape in mouth_shapes)
    return f"""
Create mouth shapes for early video-toon mouth-flap assembly.

Actor:
{actor_id}

Required mouth shapes:
{mouth_lines}

Keep the face, age band, head angle, hair silhouette, and line style consistent
across all mouth shapes. Mouth shapes should be usable as layered face parts.
"""


def _negative_prompt_text() -> str:
    return """
Avoid identity drift:
- different person
- younger or older age band
- changed face shape
- changed hair silhouette
- changed body proportions
- different clothing silhouette
- extra people
- cropped head
- full-body framing when half-body is required
- unreadable text
- UI overlays
- phone screen UI
- watermark
- logo
- realistic photo style
- 3D render style
- heavy blur
"""


def _references_readme_text(actor_id: str) -> str:
    return f"""
# References

Place private local reference images for `{actor_id}` here.

The public repository must not include real actor reference images, generated
channel output, model weights, voice samples, or private local paths.
"""


def _actor_checklist_text(actor_id: str) -> str:
    return f"""
# Actor Model Checklist

Actor: `{actor_id}`

Use this checklist before moving a local actor package beyond `template`.

- [ ] Identity lock is clear enough for another agent to reproduce.
- [ ] Required variants are generated or curated locally.
- [ ] Mouth shapes exist locally and align to the same face.
- [ ] Eye shapes exist locally and align to the same face.
- [ ] Voice profile is selected and stable.
- [ ] Actor can be referenced from `settings.motiontoon.actor_pool`.
- [ ] No public package files contain generated channel output.
- [ ] No public package files contain voice datasets, model weights, API keys,
      local paths, memory DBs, session logs, or OAuth credentials.
"""


def _asset_request(
    *,
    actor_id: str,
    request_type: str,
    key: str,
    target_relative_path: str,
    prompt: str,
    negative_prompt: str,
    expression: str = "",
    pose: str = "",
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "request_id": f"{actor_id}__{request_type}__{key}",
        "request_type": request_type,
        "actor_id": actor_id,
        "key": key,
        "target_relative_path": target_relative_path,
        "prompt": prompt.strip(),
        "negative_prompt": negative_prompt.strip(),
        "public_safe": True,
    }
    if expression:
        request["expression"] = expression
    if pose:
        request["pose"] = pose
    return request


def _load_actor_contract(actor_model_path: Path | str, repo_root: Optional[Path | str]) -> tuple[Path, dict[str, Any]]:
    actor_path, path_error = _resolve_actor_path(actor_model_path, repo_root)
    if path_error:
        raise ValueError(path_error)
    if not actor_path.exists():
        raise ValueError(f"actor_model_path does not exist: {actor_model_path}")
    data = json.loads(actor_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("actor.json must contain a JSON object")
    return actor_path, data


def _build_asset_requests_from_contract(
    actor_path: Path,
    validation: ActorModelValidationResult,
) -> list[dict[str, Any]]:
    actor_dir = actor_path.parent
    actor_id = validation.actor_id
    identity_prompt = _read_template(actor_dir, "prompts/identity_prompt.txt")
    variant_prompt = _read_template(actor_dir, "prompts/variant_prompt.txt")
    mouth_prompt = _read_template(actor_dir, "prompts/mouth_prompt.txt")
    negative_prompt = _read_template(actor_dir, "prompts/negative_prompt.txt")

    requests: list[dict[str, Any]] = []
    for variant_key in validation.required_variants:
        expression, pose = _variant_parts(variant_key)
        prompt = "\n\n".join(
            [
                identity_prompt,
                variant_prompt,
                f"Requested variant: {variant_key}",
                f"Expression: {expression}",
                f"Pose: {pose}",
                "Output: one transparent-capable half-body video-toon actor image, no background, no text.",
            ]
        )
        requests.append(
            _asset_request(
                actor_id=actor_id,
                request_type="variant",
                key=variant_key,
                target_relative_path=f"variants/{variant_key}.png",
                prompt=prompt,
                negative_prompt=negative_prompt,
                expression=expression,
                pose=pose,
            )
        )

    for mouth_shape in validation.mouth_shapes:
        prompt = "\n\n".join(
            [
                identity_prompt,
                mouth_prompt,
                f"Requested mouth shape: {mouth_shape}",
                "Output: transparent PNG mouth layer aligned to the actor face.",
            ]
        )
        requests.append(
            _asset_request(
                actor_id=actor_id,
                request_type="mouth_shape",
                key=mouth_shape,
                target_relative_path=f"face_parts/{mouth_shape}.png",
                prompt=prompt,
                negative_prompt=negative_prompt,
            )
        )

    for eye_shape in validation.eye_shapes:
        prompt = "\n\n".join(
            [
                identity_prompt,
                f"Create eye shape '{eye_shape}' for {actor_id}.",
                "Keep the same head angle, eye placement, line weight, and webtoon style.",
                "Output: transparent PNG eye layer aligned to the actor face.",
            ]
        )
        requests.append(
            _asset_request(
                actor_id=actor_id,
                request_type="eye_shape",
                key=eye_shape,
                target_relative_path=f"face_parts/{eye_shape}.png",
                prompt=prompt,
                negative_prompt=negative_prompt,
            )
        )

    return requests


def _validation_from_contract(actor_path: Path, actor_data: Mapping[str, Any]) -> ActorModelValidationResult:
    result = ActorModelValidationResult()
    actor_id = str(actor_data.get("actor_id") or "").strip()
    result.actor_id = actor_id
    if not actor_id:
        result.add_error("actor_id is required")
    elif actor_path.parent.name != actor_id:
        result.add_error(f"actor_id '{actor_id}' must match actor model folder '{actor_path.parent.name}'")
    result.required_variants = _string_list(actor_data.get("required_variants"))
    result.mouth_shapes = _string_list(actor_data.get("mouth_shapes"))
    result.eye_shapes = _string_list(actor_data.get("eye_shapes"))
    if not result.required_variants:
        result.add_error("required_variants must be a non-empty string list")
    if not result.mouth_shapes:
        result.add_error("mouth_shapes must be a non-empty string list")
    if not result.eye_shapes:
        result.add_error("eye_shapes must be a non-empty string list")
    _validate_asset_keys("required_variants", result.required_variants, result)
    _validate_asset_keys("mouth_shapes", result.mouth_shapes, result)
    _validate_asset_keys("eye_shapes", result.eye_shapes, result)
    return result


def _validate_public_boundary(data: Mapping[str, Any], result: ActorModelValidationResult) -> None:
    boundary = data.get("public_release_boundary")
    if not isinstance(boundary, Mapping):
        result.add_error("public_release_boundary must be an object")
        return

    for field_name in (
        "contains_real_actor_media",
        "contains_voice_samples",
        "contains_model_weights",
        "contains_private_paths",
    ):
        if boundary.get(field_name) is not False:
            result.add_error(f"public_release_boundary.{field_name} must be false")


def _validate_package_files(
    actor_dir: Path,
    result: ActorModelValidationResult,
    *,
    allow_local_media: bool = False,
) -> None:
    for relative_path in REQUIRED_PROMPT_FILES:
        if not (actor_dir / relative_path).exists():
            result.add_error(f"{relative_path} is required")

    forbidden_files = [
        str(path.relative_to(actor_dir))
        for path in actor_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in FORBIDDEN_PUBLIC_SUFFIXES
        and not (allow_local_media and path.suffix.lower() in LOCAL_ACTOR_MEDIA_SUFFIXES)
    ]
    if forbidden_files:
        result.add_error(f"public actor_model package contains forbidden media/model files: {', '.join(forbidden_files)}")

    for text_path in actor_dir.rglob("*"):
        if not text_path.is_file() or text_path.suffix.lower() not in {"", ".json", ".md", ".txt"}:
            continue
        try:
            text = text_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            result.add_error(f"{text_path.relative_to(actor_dir)} must be utf-8 text in public templates")
            continue
        for pattern in PRIVATE_TEXT_PATTERNS:
            if pattern.search(text):
                result.add_error(f"{text_path.relative_to(actor_dir)} contains private path, key, or credential-like text")
                break


def validate_actor_model_package(
    actor_model_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
    allow_local_media: bool = False,
) -> ActorModelValidationResult:
    """Validate a public-safe video-toon actor model package."""
    result = ActorModelValidationResult()
    actor_path, path_error = _resolve_actor_path(actor_model_path, repo_root)
    if path_error:
        result.add_error(path_error)
        return result
    if not actor_path.exists():
        result.add_error(f"actor_model_path does not exist: {actor_model_path}")
        return result
    if not actor_path.is_file():
        result.add_error(f"actor_model_path must point to actor.json: {actor_model_path}")
        return result

    actor_dir = actor_path.parent
    data = _load_actor_json(actor_path, result)
    if not data:
        return result

    actor_id = str(data.get("actor_id") or "").strip()
    result.actor_id = actor_id
    if not actor_id:
        result.add_error("actor_id is required")
    elif actor_dir.name != actor_id:
        result.add_error(f"actor_id '{actor_id}' must match actor model folder '{actor_dir.name}'")

    readiness_state = str(data.get("readiness_state") or "").strip()
    if readiness_state not in READINESS_STATES:
        result.add_error("readiness_state must be one of: template, draft, ready_for_test, approved, retired")

    identity_lock = data.get("identity_lock")
    if not isinstance(identity_lock, Mapping):
        result.add_error("identity_lock must be an object")
    elif not _string_list(identity_lock.get("must_not_change")):
        result.add_error("identity_lock.must_not_change must be a non-empty string list")

    template_goal = data.get("template_goal")
    if not isinstance(template_goal, Mapping):
        result.add_error("template_goal must be an object")
    else:
        if not str(template_goal.get("goal_id") or "").strip():
            result.add_error("template_goal.goal_id must be a non-empty string")
        if not _string_list(template_goal.get("reuse_surfaces")):
            result.add_error("template_goal.reuse_surfaces must be a non-empty string list")

    reuse_contract = data.get("reuse_contract")
    if not isinstance(reuse_contract, Mapping):
        result.add_error("reuse_contract must be an object")
    else:
        for field_name in (
            "identity_is_fixed",
            "roles_may_change_by_episode",
            "background_may_change_by_episode",
            "requires_asset_coverage_before_render",
        ):
            if not isinstance(reuse_contract.get(field_name), bool):
                result.add_error(f"reuse_contract.{field_name} must be a boolean")

    result.required_variants = _string_list(data.get("required_variants"))
    result.mouth_shapes = _string_list(data.get("mouth_shapes"))
    result.eye_shapes = _string_list(data.get("eye_shapes"))
    if not result.required_variants:
        result.add_error("required_variants must be a non-empty string list")
    if not result.mouth_shapes:
        result.add_error("mouth_shapes must be a non-empty string list")
    if not result.eye_shapes:
        result.add_error("eye_shapes must be a non-empty string list")
    _validate_asset_keys("required_variants", result.required_variants, result)
    _validate_asset_keys("mouth_shapes", result.mouth_shapes, result)
    _validate_asset_keys("eye_shapes", result.eye_shapes, result)

    _validate_layering_contract(data, result)
    _validate_public_boundary(data, result)
    _validate_package_files(actor_dir, result, allow_local_media=allow_local_media)
    return result


def scaffold_actor_model(
    actor_id: str,
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
    display_name: str = "",
    age_band: str = "adult",
    gender_presentation: str = "unspecified",
    role_range: Optional[list[str] | str] = None,
    visual_identity: str = "",
    voice_profile: str = "neutral_01",
    required_variants: Optional[list[str] | str] = None,
    mouth_shapes: Optional[list[str] | str] = None,
    eye_shapes: Optional[list[str] | str] = None,
    force: bool = False,
) -> Path:
    """Create a public-safe reusable video-toon actor model package."""
    actor_id = str(actor_id or "").strip()
    if not actor_id:
        raise ValueError("actor_id is required")
    if not ACTOR_ID_PATTERN.fullmatch(actor_id):
        raise ValueError("actor_id must use lowercase letters, numbers, and underscores")

    resolved_actor_root = _resolve_actor_root(actor_root, repo_root)
    actor_dir = resolved_actor_root / actor_id
    if actor_dir.exists() and not force:
        raise FileExistsError(f"actor model already exists: {actor_dir}")

    roles = _coerce_string_list(role_range, DEFAULT_ROLE_RANGE)
    variants = _coerce_string_list(required_variants, DEFAULT_REQUIRED_VARIANTS)
    mouths = _coerce_string_list(mouth_shapes, DEFAULT_MOUTH_SHAPES)
    eyes = _coerce_string_list(eye_shapes, DEFAULT_EYE_SHAPES)
    if not roles:
        raise ValueError("role_range must contain at least one role")
    if not variants:
        raise ValueError("required_variants must contain at least one variant")
    if not mouths:
        raise ValueError("mouth_shapes must contain at least one mouth shape")
    if not eyes:
        raise ValueError("eye_shapes must contain at least one eye shape")

    clean_display_name = str(display_name or "").strip() or _default_display_name(actor_id)
    clean_age_band = str(age_band or "").strip() or "adult"
    clean_gender = str(gender_presentation or "").strip() or "unspecified"
    clean_visual_identity = (
        str(visual_identity or "").strip()
        or f"{clean_age_band} {clean_gender} reusable video-toon actor with a clear, stable silhouette"
    )
    clean_voice_profile = str(voice_profile or "").strip() or "neutral_01"

    actor_dir.mkdir(parents=True, exist_ok=True)
    for directory_name in ("prompts", "references", "variants", "face_parts", "qa"):
        (actor_dir / directory_name).mkdir(parents=True, exist_ok=True)

    actor_data = {
        "actor_id": actor_id,
        "display_name": clean_display_name,
        "template_version": "actor_model_template_v1",
        "readiness_state": "template",
        "age_band": clean_age_band,
        "gender_presentation": clean_gender,
        "role_range": roles,
        "template_goal": _default_template_goal(actor_id),
        "reuse_contract": copy.deepcopy(DEFAULT_REUSE_CONTRACT),
        "identity_lock": {
            "face_shape": f"consistent {clean_age_band} {clean_gender} face shape",
            "hair": "fixed hair silhouette chosen during local asset generation",
            "body_type": "ordinary proportions, half-body video-toon friendly",
            "signature_clothing": "fixed primary clothing silhouette chosen during local asset generation",
            "must_not_change": [
                "age band",
                "face shape",
                "hair silhouette",
                "body proportions",
                "primary clothing silhouette",
            ],
        },
        "style_contract": {
            "visual_style": "clean Korean webtoon video-toon cutout",
            "line_quality": "clean line art",
            "rendering": "cel-shaded, readable expression",
            "framing": "waist-up or half-body, centered for layered compositing",
        },
        "required_variants": variants,
        "mouth_shapes": mouths,
        "eye_shapes": eyes,
        "layering_contract": copy.deepcopy(DEFAULT_LAYERING_CONTRACT),
        "voice_profile": {
            "recommended_slot": clean_voice_profile,
            "stable_voice_required": True,
        },
        "public_release_boundary": {
            "contains_real_actor_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
    }

    actor_path = actor_dir / "actor.json"
    actor_path.write_text(json.dumps(actor_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_text_file(
        actor_dir / "prompts" / "identity_prompt.txt",
        _identity_prompt_text(
            actor_id=actor_id,
            age_band=clean_age_band,
            gender_presentation=clean_gender,
            visual_identity=clean_visual_identity,
        ),
    )
    _write_text_file(actor_dir / "prompts" / "variant_prompt.txt", _variant_prompt_text(actor_id, variants))
    _write_text_file(actor_dir / "prompts" / "mouth_prompt.txt", _mouth_prompt_text(actor_id, mouths))
    _write_text_file(actor_dir / "prompts" / "negative_prompt.txt", _negative_prompt_text())
    _write_text_file(actor_dir / "references" / "README.md", _references_readme_text(actor_id))
    _write_text_file(actor_dir / "qa" / "actor_model_checklist.md", _actor_checklist_text(actor_id))
    (actor_dir / "references" / ".gitkeep").touch()
    (actor_dir / "variants" / ".gitkeep").touch()
    (actor_dir / "face_parts" / ".gitkeep").touch()

    validation = validate_actor_model_package(actor_path, repo_root=repo_root)
    if not validation.is_valid:
        raise ValueError("scaffolded actor model validation failed: " + "; ".join(validation.errors))
    return actor_path


def load_actor_model_preset_catalog(
    catalog_path: Optional[Path | str] = None,
    *,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Load and validate the public-safe actor preset catalog."""
    path = _resolve_preset_catalog_path(catalog_path, repo_root)
    if not path.exists():
        raise ValueError(f"actor model preset catalog does not exist: {path}")

    catalog = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict):
        raise ValueError("actor model preset catalog must contain a JSON object")
    if catalog.get("schema") != "reverie.actor_model.presets.v1":
        raise ValueError("actor model preset catalog schema must be reverie.actor_model.presets.v1")

    presets = catalog.get("presets")
    if not isinstance(presets, dict) or not presets:
        raise ValueError("actor model preset catalog must contain non-empty presets")

    serialized = json.dumps(catalog, ensure_ascii=False)
    for pattern in PRIVATE_TEXT_PATTERNS:
        if pattern.search(serialized):
            raise ValueError("actor model preset catalog contains private path, key, or credential-like text")

    for preset_id, preset in presets.items():
        if not isinstance(preset_id, str) or not preset_id.strip():
            raise ValueError("actor model preset ids must be non-empty strings")
        if not isinstance(preset, dict):
            raise ValueError(f"actor model preset {preset_id} must be an object")
        missing = [field_name for field_name in PRESET_REQUIRED_FIELDS if field_name not in preset]
        if missing:
            raise ValueError(f"actor model preset {preset_id} missing required fields: {', '.join(missing)}")
        for field_name in ("display_name", "age_band", "gender_presentation", "visual_identity", "voice_profile"):
            if not str(preset.get(field_name) or "").strip():
                raise ValueError(f"actor model preset {preset_id}.{field_name} must be a non-empty string")
        for field_name in ("genre_tags", "role_range"):
            if not _string_list(preset.get(field_name)):
                raise ValueError(f"actor model preset {preset_id}.{field_name} must be a non-empty string list")

    return catalog


def scaffold_actor_model_from_preset(
    preset_id: str,
    actor_id: str,
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
    catalog_path: Optional[Path | str] = None,
    force: bool = False,
) -> Path:
    """Create an actor model package from a reusable preset catalog entry."""
    preset_key = str(preset_id or "").strip()
    catalog = load_actor_model_preset_catalog(catalog_path, repo_root=repo_root)
    presets = catalog["presets"]
    if preset_key not in presets:
        raise ValueError(f"unknown actor model preset: {preset_key}")

    preset = presets[preset_key]
    return scaffold_actor_model(
        actor_id,
        actor_root=actor_root,
        repo_root=repo_root,
        display_name=str(preset["display_name"]),
        age_band=str(preset["age_band"]),
        gender_presentation=str(preset["gender_presentation"]),
        role_range=_string_list(preset["role_range"]),
        visual_identity=str(preset["visual_identity"]),
        voice_profile=str(preset["voice_profile"]),
        required_variants=preset.get("required_variants"),
        mouth_shapes=preset.get("mouth_shapes"),
        eye_shapes=preset.get("eye_shapes"),
        force=force,
    )


def build_actor_reuse_template_manifest(
    actor_model_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
    contexts: Optional[list[str] | str] = None,
) -> dict[str, Any]:
    """Build a portable manifest that treats one actor model as a reusable template target."""
    actor_path, actor_data = _load_actor_contract(actor_model_path, repo_root)
    validation = validate_actor_model_package(actor_path, repo_root=repo_root)
    if not validation.is_valid:
        raise ValueError("actor model package is invalid: " + "; ".join(validation.errors))

    role_range = _coerce_string_list(actor_data.get("role_range"), DEFAULT_ROLE_RANGE)
    usage_contexts = _coerce_string_list(contexts, DEFAULT_REUSE_CONTEXTS)
    if not usage_contexts:
        usage_contexts = list(DEFAULT_REUSE_CONTEXTS)

    template_goal = _normalize_template_goal(validation.actor_id, actor_data.get("template_goal"))
    reuse_contract = _normalize_reuse_contract(actor_data.get("reuse_contract"))
    reuse_surfaces = _string_list(template_goal.get("reuse_surfaces")) or list(DEFAULT_REUSE_SURFACES)
    actor_model_relative_path = _relative_to_root(actor_path, repo_root)

    reuse_slots: list[dict[str, Any]] = []
    for context_id in usage_contexts:
        for role_id in role_range:
            reuse_slots.append(
                {
                    "context_id": context_id,
                    "role_id": role_id,
                    "actor_id": validation.actor_id,
                    "actor_model_path": actor_model_relative_path,
                    "identity_is_fixed": bool(reuse_contract["identity_is_fixed"]),
                    "roles_may_change": bool(reuse_contract["roles_may_change_by_episode"]),
                    "background_may_change": bool(reuse_contract["background_may_change_by_episode"]),
                }
            )

    asset_requests = _build_asset_requests_from_contract(actor_path, validation)
    asset_targets = [
        {
            "request_type": request["request_type"],
            "key": request["key"],
            "target_relative_path": request["target_relative_path"],
            **({"expression": request["expression"]} if "expression" in request else {}),
            **({"pose": request["pose"]} if "pose" in request else {}),
        }
        for request in asset_requests
    ]

    return {
        "schema": "reverie.actor_model.reuse_template.v1",
        "actor_id": validation.actor_id,
        "actor_model_path": actor_model_relative_path,
        "template_goal": template_goal,
        "reuse_contract": reuse_contract,
        "reuse_surfaces": reuse_surfaces,
        "usage_contexts": usage_contexts,
        "role_range": role_range,
        "variant_groups": _variant_groups(validation.required_variants, validation.mouth_shapes, validation.eye_shapes),
        "reuse_slots": reuse_slots,
        "asset_targets": asset_targets,
        "asset_target_count": len(asset_targets),
        "ready_for_asset_generation": validation.is_valid,
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
    }


def write_actor_reuse_template_manifest(
    actor_model_path: Path | str,
    output_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
    contexts: Optional[list[str] | str] = None,
) -> Path:
    """Write a reusable actor-template manifest and return the output path."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_actor_reuse_template_manifest(actor_model_path, repo_root=repo_root, contexts=contexts)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _normalize_roster_assignment(assignment: Mapping[str, Any]) -> dict[str, Any]:
    role_id = str(assignment.get("role_id") or "").strip()
    preset_id = str(assignment.get("preset_id") or "").strip()
    actor_id = str(assignment.get("actor_id") or "").strip()
    if not role_id:
        raise ValueError("roster assignment role_id is required")
    if not preset_id:
        raise ValueError(f"roster assignment {role_id}.preset_id is required")
    if not actor_id:
        raise ValueError(f"roster assignment {role_id}.actor_id is required")
    if not ACTOR_ID_PATTERN.fullmatch(actor_id):
        raise ValueError(f"roster assignment {role_id}.actor_id must use lowercase letters, numbers, and underscores")
    return {
        "role_id": role_id,
        "preset_id": preset_id,
        "actor_id": actor_id,
        "aliases": _normalize_aliases(assignment.get("aliases")),
    }


def _parse_roster_assignment(raw_assignment: str) -> dict[str, Any]:
    raw = str(raw_assignment or "").strip()
    role_part, separator, preset_actor_part = raw.partition("=")
    if not separator:
        raise ValueError("roster assignment must use role=preset:actor_id")
    preset_part, separator, actor_alias_part = preset_actor_part.partition(":")
    if not separator:
        raise ValueError("roster assignment must use role=preset:actor_id")
    actor_part, _, alias_part = actor_alias_part.partition(":")
    return _normalize_roster_assignment(
        {
            "role_id": role_part,
            "preset_id": preset_part,
            "actor_id": actor_part,
            "aliases": alias_part,
        }
    )


def build_pack_actor_roster_plan(
    pack_id: str,
    assignments: list[Mapping[str, Any]],
    *,
    catalog_path: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
    actor_root_relative: str = "assets/actor_models",
) -> dict[str, Any]:
    """Build a public-safe pack actor roster patch from preset assignments."""
    pack_key = str(pack_id or "").strip()
    if not pack_key:
        raise ValueError("pack_id is required")
    if not assignments:
        raise ValueError("at least one roster assignment is required")

    catalog = load_actor_model_preset_catalog(catalog_path, repo_root=repo_root)
    presets = catalog["presets"]
    normalized_assignments = [_normalize_roster_assignment(assignment) for assignment in assignments]
    actor_root = str(actor_root_relative or "assets/actor_models").strip().replace("\\", "/").strip("/")

    actor_pool: dict[str, Any] = {}
    cast_slots: dict[str, Any] = {}
    role_casting: dict[str, str] = {}
    seen_roles: set[str] = set()
    seen_actors: set[str] = set()

    for assignment in normalized_assignments:
        role_id = assignment["role_id"]
        preset_id = assignment["preset_id"]
        actor_id = assignment["actor_id"]
        aliases = assignment["aliases"]
        if role_id in seen_roles:
            raise ValueError(f"duplicate roster role_id: {role_id}")
        if actor_id in seen_actors:
            raise ValueError(f"duplicate roster actor_id: {actor_id}")
        if preset_id not in presets:
            raise ValueError(f"unknown actor model preset: {preset_id}")

        preset = presets[preset_id]
        seen_roles.add(role_id)
        seen_actors.add(actor_id)
        actor_pool[actor_id] = {
            "character_id": actor_id,
            "actor_model_path": f"{actor_root}/{actor_id}/actor.json",
            "visual_identity": str(preset["visual_identity"]),
            "voice_profile": str(preset["voice_profile"]),
            "required_variants": _coerce_string_list(preset.get("required_variants"), DEFAULT_REQUIRED_VARIANTS),
            "preset_id": preset_id,
            "age_band": str(preset["age_band"]),
            "gender_presentation": str(preset["gender_presentation"]),
            "genre_tags": _string_list(preset["genre_tags"]),
        }
        cast_slots[role_id] = {
            "actor_id": actor_id,
            "character_id": actor_id,
            "aliases": aliases,
        }
        role_casting[role_id] = actor_id

    return {
        "schema": "reverie.pack.actor_roster_plan.v1",
        "pack_id": pack_key,
        "role_reuse_policy": {
            "stable_actor_identity": True,
            "episode_roles_may_change": True,
            "role_casting_is_episode_specific": True,
        },
        "motiontoon_patch": {
            "actor_pool": actor_pool,
            "role_casting_contract": dict(DEFAULT_ROLE_CASTING_CONTRACT),
            "cast_slots": cast_slots,
        },
        "episode_cast_seed": {
            "episode_id": f"{pack_key}_episode_seed",
            "role_casting": role_casting,
        },
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
    }


def write_pack_actor_roster_plan(
    pack_id: str,
    assignments: list[Mapping[str, Any]],
    output_path: Path | str,
    *,
    catalog_path: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
    actor_root_relative: str = "assets/actor_models",
) -> Path:
    """Write a public-safe pack actor roster plan and return the output path."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    plan = build_pack_actor_roster_plan(
        pack_id,
        assignments,
        catalog_path=catalog_path,
        repo_root=repo_root,
        actor_root_relative=actor_root_relative,
    )
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _load_json_object(path: Path | str, label: str) -> dict[str, Any]:
    json_path = Path(path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return data


def _validate_roster_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise ValueError("actor roster plan must be an object")
    if plan.get("schema") != "reverie.pack.actor_roster_plan.v1":
        raise ValueError("actor roster plan schema must be reverie.pack.actor_roster_plan.v1")
    boundary = plan.get("public_release_boundary")
    if not isinstance(boundary, Mapping):
        raise ValueError("actor roster plan public_release_boundary must be an object")
    for field_name in ("contains_generated_media", "contains_voice_samples", "contains_model_weights", "contains_private_paths"):
        if boundary.get(field_name) is not False:
            raise ValueError(f"actor roster plan public_release_boundary.{field_name} must be false")

    patch = plan.get("motiontoon_patch")
    if not isinstance(patch, Mapping):
        raise ValueError("actor roster plan motiontoon_patch must be an object")
    for field_name in ("actor_pool", "cast_slots", "role_casting_contract"):
        if not isinstance(patch.get(field_name), Mapping):
            raise ValueError(f"actor roster plan motiontoon_patch.{field_name} must be an object")
    return dict(patch)


def _merge_mapping_without_conflicts(
    target: dict[str, Any],
    patch: Mapping[str, Any],
    *,
    label: str,
    force: bool,
) -> None:
    for key, value in patch.items():
        key_text = str(key)
        if key_text in target and not force:
            raise ValueError(f"{label}.{key_text} already exists; pass force=True to overwrite")
        target[key_text] = copy.deepcopy(value)


def apply_pack_actor_roster_plan(
    settings: Mapping[str, Any],
    roster_plan: Mapping[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Apply a public-safe actor roster plan to a pack settings object."""
    if not isinstance(settings, Mapping):
        raise ValueError("settings must be an object")
    patch = _validate_roster_plan(roster_plan)
    applied = copy.deepcopy(dict(settings))
    motiontoon = applied.setdefault("motiontoon", {})
    if not isinstance(motiontoon, dict):
        raise ValueError("settings.motiontoon must be an object")

    actor_pool = motiontoon.setdefault("actor_pool", {})
    if not isinstance(actor_pool, dict):
        raise ValueError("settings.motiontoon.actor_pool must be an object")
    cast_slots = motiontoon.setdefault("cast_slots", {})
    if not isinstance(cast_slots, dict):
        raise ValueError("settings.motiontoon.cast_slots must be an object")

    _merge_mapping_without_conflicts(
        actor_pool,
        patch["actor_pool"],
        label="settings.motiontoon.actor_pool",
        force=force,
    )
    _merge_mapping_without_conflicts(
        cast_slots,
        patch["cast_slots"],
        label="settings.motiontoon.cast_slots",
        force=force,
    )

    role_contract = motiontoon.setdefault("role_casting_contract", {})
    if not isinstance(role_contract, dict):
        raise ValueError("settings.motiontoon.role_casting_contract must be an object")
    role_contract.update(copy.deepcopy(dict(patch["role_casting_contract"])))
    return applied


def write_applied_pack_actor_roster_plan(
    settings_path: Path | str,
    roster_plan_path: Path | str,
    output_path: Path | str,
    *,
    force: bool = False,
) -> Path:
    """Apply a roster plan to a settings JSON file and write the result."""
    settings = _load_json_object(settings_path, "settings")
    roster_plan = _load_json_object(roster_plan_path, "actor roster plan")
    applied = apply_pack_actor_roster_plan(settings, roster_plan, force=force)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(applied, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def scaffold_actor_models_from_roster_plan(
    roster_plan: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
    catalog_path: Optional[Path | str] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Scaffold every actor model referenced by a public-safe roster plan."""
    patch = _validate_roster_plan(roster_plan)
    pack_id = str(roster_plan.get("pack_id") or "").strip()
    actor_pool = patch["actor_pool"]
    if not actor_pool:
        raise ValueError("actor roster plan motiontoon_patch.actor_pool must not be empty")

    actors: dict[str, Any] = {}
    created_count = 0
    existing_count = 0
    for actor_id, actor_data in actor_pool.items():
        actor_key = str(actor_id or "").strip()
        if not actor_key:
            raise ValueError("actor roster plan actor_pool contains an empty actor id")
        if not isinstance(actor_data, Mapping):
            raise ValueError(f"actor roster plan actor_pool.{actor_key} must be an object")
        preset_id = str(actor_data.get("preset_id") or "").strip()
        if not preset_id:
            raise ValueError(f"actor roster plan actor_pool.{actor_key}.preset_id is required")

        target_root = _resolve_actor_root(actor_root, repo_root)
        actor_dir = target_root / actor_key
        already_exists = actor_dir.exists()
        actor_path = scaffold_actor_model_from_preset(
            preset_id,
            actor_key,
            actor_root=actor_root,
            repo_root=repo_root,
            catalog_path=catalog_path,
            force=force,
        )
        created = not already_exists or force
        if created:
            created_count += 1
        else:
            existing_count += 1
        validation = validate_actor_model_package(actor_path, repo_root=repo_root)
        actors[actor_key] = {
            "actor_id": actor_key,
            "preset_id": preset_id,
            "actor_model_path": _relative_to_root(actor_path, repo_root),
            "created": created,
            "is_valid": validation.is_valid,
            "errors": validation.errors,
            "warnings": validation.warnings,
        }

    return {
        "schema": "reverie.pack.actor_roster_scaffold.v1",
        "pack_id": pack_id,
        "actor_count": len(actors),
        "created_count": created_count,
        "existing_count": existing_count,
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
        "actors": actors,
    }


def write_actor_roster_scaffold_report(
    roster_plan_path: Path | str,
    output_path: Path | str,
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
    catalog_path: Optional[Path | str] = None,
    force: bool = False,
) -> Path:
    """Scaffold roster actors and write a public-safe scaffold report."""
    roster_plan = _load_json_object(roster_plan_path, "actor roster plan")
    report = scaffold_actor_models_from_roster_plan(
        roster_plan,
        actor_root=actor_root,
        repo_root=repo_root,
        catalog_path=catalog_path,
        force=force,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _target_from_naming_policy(pattern: str, **values: str) -> str:
    target = pattern
    for key, value in values.items():
        target = target.replace("{" + key + "}", value)
    return Path(target).as_posix()


def _layer_spec_entry(
    *,
    actor_id: str,
    layer_type: str,
    key: str,
    target_relative_path: str,
    anchor_key: str,
    z_index: int,
) -> dict[str, Any]:
    return {
        "layer_id": f"{actor_id}__{layer_type}__{key}",
        "layer_type": layer_type,
        "key": key,
        "target_relative_path": target_relative_path,
        "anchor_key": anchor_key,
        "z_index": z_index,
        "public_safe": True,
    }


def build_actor_layer_spec_manifest(
    actor_model_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Build a renderer-facing public-safe layer specification for one actor."""
    validation = validate_actor_model_package(actor_model_path, repo_root=repo_root, allow_local_media=True)
    if not validation.is_valid:
        raise ValueError("actor model validation failed: " + "; ".join(validation.errors))

    actor_path, path_error = _resolve_actor_path(actor_model_path, repo_root)
    if path_error:
        raise ValueError(path_error)
    actor_data = json.loads(actor_path.read_text(encoding="utf-8"))
    layering_contract = _normalize_layering_contract(actor_data.get("layering_contract"))
    naming_policy = layering_contract["naming_policy"]
    layer_order = list(layering_contract["layer_order"])
    z_index = {layer_type: index for index, layer_type in enumerate(layer_order)}

    variant_layers = [
        _layer_spec_entry(
            actor_id=validation.actor_id,
            layer_type="variant_base",
            key=variant_key,
            target_relative_path=_target_from_naming_policy(
                str(naming_policy["variant"]),
                variant_key=variant_key,
            ),
            anchor_key="actor_root",
            z_index=z_index.get("variant_base", 0),
        )
        for variant_key in validation.required_variants
    ]
    mouth_layers = [
        _layer_spec_entry(
            actor_id=validation.actor_id,
            layer_type="mouth_layer",
            key=mouth_shape,
            target_relative_path=_target_from_naming_policy(
                str(naming_policy["mouth_shape"]),
                mouth_shape_key=mouth_shape,
            ),
            anchor_key="mouth_center",
            z_index=z_index.get("mouth_layer", 2),
        )
        for mouth_shape in validation.mouth_shapes
    ]
    eye_layers = [
        _layer_spec_entry(
            actor_id=validation.actor_id,
            layer_type="eye_layer",
            key=eye_shape,
            target_relative_path=_target_from_naming_policy(
                str(naming_policy["eye_shape"]),
                eye_shape_key=eye_shape,
            ),
            anchor_key="eye_center",
            z_index=z_index.get("eye_layer", 1),
        )
        for eye_shape in validation.eye_shapes
    ]

    return {
        "schema": "reverie.actor_model.layer_spec.v1",
        "actor_id": validation.actor_id,
        "template_version": actor_data.get("template_version", ""),
        "readiness_state": actor_data.get("readiness_state", ""),
        "source_actor_model_path": _relative_to_root(actor_path, repo_root),
        "image_format": layering_contract["image_format"],
        "canvas": layering_contract["canvas"],
        "anchor_points": layering_contract["anchor_points"],
        "layer_order": layer_order,
        "variant_layers": variant_layers,
        "mouth_layers": mouth_layers,
        "eye_layers": eye_layers,
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
    }


def write_actor_layer_spec_manifest(
    actor_model_path: Path | str,
    output_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
) -> Path:
    """Write an actor layer specification manifest and return the output path."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_actor_layer_spec_manifest(actor_model_path, repo_root=repo_root)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def build_actor_asset_request_manifest(
    actor_model_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Build a public-safe request manifest for local actor asset generation."""
    validation = validate_actor_model_package(actor_model_path, repo_root=repo_root, allow_local_media=True)
    if not validation.is_valid:
        raise ValueError("actor model validation failed: " + "; ".join(validation.errors))

    actor_path, path_error = _resolve_actor_path(actor_model_path, repo_root)
    if path_error:
        raise ValueError(path_error)
    actor_data = json.loads(actor_path.read_text(encoding="utf-8"))
    requests = _build_asset_requests_from_contract(actor_path, validation)

    return {
        "schema": "reverie.actor_model.asset_requests.v1",
        "actor_id": validation.actor_id,
        "template_version": actor_data.get("template_version", ""),
        "readiness_state": actor_data.get("readiness_state", ""),
        "source_actor_model_path": _relative_to_root(actor_path, repo_root),
        "request_count": len(requests),
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
        "requests": requests,
    }


def write_actor_asset_request_manifest(
    actor_model_path: Path | str,
    output_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
) -> Path:
    """Write an actor asset request manifest and return the output path."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_actor_asset_request_manifest(actor_model_path, repo_root=repo_root)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _actor_canvas(actor_data: Mapping[str, Any]) -> tuple[int, int]:
    contract = _normalize_layering_contract(actor_data.get("layering_contract"))
    canvas = contract["canvas"]
    return int(canvas["width"]), int(canvas["height"])


def _anchor_pixel(actor_data: Mapping[str, Any], anchor_key: str, width: int, height: int) -> tuple[int, int]:
    contract = _normalize_layering_contract(actor_data.get("layering_contract"))
    anchor = contract["anchor_points"].get(anchor_key, {"x": 0.5, "y": 0.5})
    return int(float(anchor.get("x", 0.5)) * width), int(float(anchor.get("y", 0.5)) * height)


def _sample_asset_palette(actor_id: str) -> dict[str, tuple[int, int, int, int]]:
    seed = sum(ord(char) for char in actor_id)
    jacket = (72 + seed % 50, 92 + seed % 45, 122 + seed % 40, 255)
    accent = (176 + seed % 40, 94 + seed % 35, 112 + seed % 25, 255)
    return {
        "line": (34, 34, 34, 255),
        "skin": (245, 206, 176, 255),
        "hair": (42, 36, 34, 255),
        "jacket": jacket,
        "shirt": (244, 240, 230, 255),
        "accent": accent,
        "shadow": (0, 0, 0, 32),
    }


def _draw_sample_variant_asset(path: Path, actor_id: str, key: str, actor_data: Mapping[str, Any]) -> tuple[int, int]:
    width, height = _actor_canvas(actor_data)
    palette = _sample_asset_palette(actor_id)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    center_x = width // 2
    head_y = int(height * 0.22)
    head_w = int(width * 0.26)
    head_h = int(height * 0.17)
    torso_top = int(height * 0.43)
    torso_bottom = int(height * (0.94 if "seated" not in key else 0.82))
    shoulder_w = int(width * 0.56)
    waist_w = int(width * 0.39)
    expression = _variant_parts(key)[0]

    draw.ellipse(
        (center_x - head_w // 2 + 18, head_y - 8, center_x + head_w // 2 + 18, head_y + head_h + 10),
        fill=palette["shadow"],
    )
    draw.polygon(
        [
            (center_x - shoulder_w // 2, torso_top),
            (center_x + shoulder_w // 2, torso_top),
            (center_x + waist_w // 2, torso_bottom),
            (center_x - waist_w // 2, torso_bottom),
        ],
        fill=palette["jacket"],
        outline=palette["line"],
    )
    draw.polygon(
        [
            (center_x - int(width * 0.12), torso_top + 8),
            (center_x + int(width * 0.12), torso_top + 8),
            (center_x + int(width * 0.08), torso_bottom),
            (center_x - int(width * 0.08), torso_bottom),
        ],
        fill=palette["shirt"],
        outline=palette["line"],
    )
    neck_w = int(width * 0.08)
    draw.rounded_rectangle(
        (center_x - neck_w, int(height * 0.36), center_x + neck_w, int(height * 0.46)),
        radius=16,
        fill=palette["skin"],
        outline=palette["line"],
    )
    draw.ellipse(
        (center_x - head_w // 2, head_y, center_x + head_w // 2, head_y + head_h),
        fill=palette["skin"],
        outline=palette["line"],
        width=max(3, width // 220),
    )
    draw.pieslice(
        (center_x - head_w // 2 - 18, head_y - 42, center_x + head_w // 2 + 18, head_y + head_h // 2),
        start=185,
        end=355,
        fill=palette["hair"],
        outline=palette["line"],
    )
    draw.arc(
        (center_x - int(width * 0.09), head_y + int(head_h * 0.52), center_x + int(width * 0.09), head_y + int(head_h * 0.74)),
        start=20 if expression in {"happy", "talking"} else 180,
        end=160 if expression in {"happy", "talking"} else 340,
        fill=palette["line"],
        width=max(4, width // 160),
    )
    if expression in {"angry", "scared", "worried", "sad"}:
        draw.line(
            (center_x - int(width * 0.13), head_y + int(head_h * 0.38), center_x - int(width * 0.04), head_y + int(head_h * 0.34)),
            fill=palette["line"],
            width=max(3, width // 220),
        )
        draw.line(
            (center_x + int(width * 0.04), head_y + int(head_h * 0.34), center_x + int(width * 0.13), head_y + int(head_h * 0.38)),
            fill=palette["line"],
            width=max(3, width // 220),
        )
    image.save(path)
    return width, height


def _draw_sample_mouth_asset(path: Path, actor_id: str, key: str, actor_data: Mapping[str, Any]) -> tuple[int, int]:
    width, height = _actor_canvas(actor_data)
    palette = _sample_asset_palette(actor_id)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    center_x, center_y = _anchor_pixel(actor_data, "mouth_center", width, height)
    mouth_w = int(width * 0.12)
    mouth_h = int(height * 0.025)
    line_width = max(4, width // 150)

    if key == "mouth_closed":
        draw.line((center_x - mouth_w // 2, center_y, center_x + mouth_w // 2, center_y), fill=palette["line"], width=line_width)
    elif key == "mouth_round":
        draw.ellipse(
            (center_x - mouth_w // 3, center_y - mouth_h, center_x + mouth_w // 3, center_y + mouth_h),
            fill=(86, 42, 48, 255),
            outline=palette["line"],
            width=line_width,
        )
    else:
        scale = 1.0 if key == "mouth_small_open" else 1.55
        draw.rounded_rectangle(
            (
                center_x - int(mouth_w * scale / 2),
                center_y - int(mouth_h * scale / 2),
                center_x + int(mouth_w * scale / 2),
                center_y + int(mouth_h * scale),
            ),
            radius=10,
            fill=(96, 45, 52, 255),
            outline=palette["line"],
            width=line_width,
        )
    image.save(path)
    return width, height


def _draw_sample_eye_asset(path: Path, actor_id: str, key: str, actor_data: Mapping[str, Any]) -> tuple[int, int]:
    width, height = _actor_canvas(actor_data)
    palette = _sample_asset_palette(actor_id)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    center_x, center_y = _anchor_pixel(actor_data, "eye_center", width, height)
    eye_w = int(width * 0.075)
    eye_h = int(height * 0.018)
    gap = int(width * 0.09)
    line_width = max(4, width // 150)

    for side in (-1, 1):
        eye_x = center_x + side * gap
        if key == "eyes_closed":
            draw.arc(
                (eye_x - eye_w // 2, center_y - eye_h, eye_x + eye_w // 2, center_y + eye_h),
                start=10,
                end=170,
                fill=palette["line"],
                width=line_width,
            )
        else:
            y_offset = -eye_h if key == "eyes_angry" and side < 0 else eye_h if key == "eyes_angry" else 0
            draw.ellipse(
                (eye_x - eye_w // 2, center_y - eye_h + y_offset, eye_x + eye_w // 2, center_y + eye_h + y_offset),
                fill=(255, 255, 255, 255),
                outline=palette["line"],
                width=line_width,
            )
            draw.ellipse(
                (eye_x - eye_w // 7, center_y - eye_h // 2 + y_offset, eye_x + eye_w // 7, center_y + eye_h // 2 + y_offset),
                fill=palette["line"],
            )
    if key == "eyes_worried":
        draw.arc(
            (center_x - int(width * 0.17), center_y - int(height * 0.055), center_x - int(width * 0.03), center_y),
            start=200,
            end=340,
            fill=palette["line"],
            width=line_width,
        )
        draw.arc(
            (center_x + int(width * 0.03), center_y - int(height * 0.055), center_x + int(width * 0.17), center_y),
            start=200,
            end=340,
            fill=palette["line"],
            width=line_width,
        )
    image.save(path)
    return width, height


def _draw_sample_actor_asset(
    path: Path,
    actor_id: str,
    request: Mapping[str, Any],
    actor_data: Mapping[str, Any],
) -> tuple[int, int]:
    request_type = str(request.get("request_type") or "")
    key = str(request.get("key") or "")
    if request_type == "variant":
        return _draw_sample_variant_asset(path, actor_id, key, actor_data)
    if request_type == "mouth_shape":
        return _draw_sample_mouth_asset(path, actor_id, key, actor_data)
    if request_type == "eye_shape":
        return _draw_sample_eye_asset(path, actor_id, key, actor_data)
    width, height = _actor_canvas(actor_data)
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(path)
    return width, height


def scaffold_actor_model_sample_assets(
    actor_model_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Create local placeholder PNG assets for a reusable actor template."""
    actor_path, actor_data = _load_actor_contract(actor_model_path, repo_root)
    validation = validate_actor_model_package(actor_path, repo_root=repo_root, allow_local_media=True)
    if not validation.is_valid:
        raise ValueError("actor model validation failed: " + "; ".join(validation.errors))

    actor_dir = actor_path.parent
    requests = _build_asset_requests_from_contract(actor_path, validation)
    assets: list[dict[str, Any]] = []
    created_count = 0
    skipped_count = 0
    for request in requests:
        target_relative_path = str(request["target_relative_path"])
        target_path = _safe_actor_asset_path(actor_dir, target_relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        existed_before = target_path.is_file()
        if existed_before and not force:
            skipped_count += 1
            width, height = _actor_canvas(actor_data)
            created = False
        else:
            width, height = _draw_sample_actor_asset(target_path, validation.actor_id, request, actor_data)
            created_count += 1
            created = True

        assets.append(
            {
                "request_id": request["request_id"],
                "request_type": request["request_type"],
                "key": request["key"],
                "target_relative_path": target_relative_path,
                "created": created,
                "skipped_existing": existed_before and not force,
                "width": width,
                "height": height,
                "local_only": True,
                "public_safe_placeholder": True,
            }
        )

    coverage_after = build_actor_asset_coverage_report(actor_path, repo_root=repo_root)
    return {
        "schema": "reverie.actor_model.sample_assets.v1",
        "actor_id": validation.actor_id,
        "mode": "public_safe_placeholder_png",
        "creates_media": True,
        "source_actor_model_path": _relative_to_root(actor_path, repo_root),
        "target_actor_dir": _relative_to_root(actor_dir, repo_root),
        "asset_count": len(assets),
        "created_count": created_count,
        "skipped_count": skipped_count,
        "coverage_after": {
            "expected_count": coverage_after["expected_count"],
            "existing_count": coverage_after["existing_count"],
            "missing_count": coverage_after["missing_count"],
            "coverage_ratio": coverage_after["coverage_ratio"],
            "ready_for_local_test": coverage_after["ready_for_local_test"],
        },
        "public_release_boundary": {
            "contains_real_actor_media": False,
            "contains_placeholder_media": True,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
        "assets": assets,
    }


def write_actor_model_sample_assets_report(
    actor_model_path: Path | str,
    output_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
    force: bool = False,
) -> Path:
    """Create local placeholder PNG assets and write a JSON report."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = scaffold_actor_model_sample_assets(actor_model_path, repo_root=repo_root, force=force)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _actor_model_path_from_roster_actor(
    actor_id: str,
    actor_data: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str],
    repo_root: Optional[Path | str],
) -> Path | str:
    if actor_root is not None:
        return _resolve_actor_root(actor_root, repo_root) / actor_id / "actor.json"

    actor_model_path = str(actor_data.get("actor_model_path") or "").strip()
    if not actor_model_path:
        raise ValueError(f"actor roster plan actor_pool.{actor_id}.actor_model_path is required")
    return actor_model_path


def build_actor_roster_asset_request_manifest(
    roster_plan: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Build one public-safe asset request manifest for every actor in a roster plan."""
    patch = _validate_roster_plan(roster_plan)
    pack_id = str(roster_plan.get("pack_id") or "").strip()
    if not pack_id:
        raise ValueError("actor roster plan pack_id is required")

    actor_pool = patch["actor_pool"]
    if not actor_pool:
        raise ValueError("actor roster plan motiontoon_patch.actor_pool must not be empty")

    cast_slots = patch["cast_slots"]
    actors: dict[str, Any] = {}
    requests: list[dict[str, Any]] = []
    for actor_id, actor_data in actor_pool.items():
        actor_key = str(actor_id or "").strip()
        if not actor_key:
            raise ValueError("actor roster plan actor_pool contains an empty actor id")
        if not isinstance(actor_data, Mapping):
            raise ValueError(f"actor roster plan actor_pool.{actor_key} must be an object")

        actor_model_path = _actor_model_path_from_roster_actor(
            actor_key,
            actor_data,
            actor_root=actor_root,
            repo_root=repo_root,
        )
        actor_manifest = build_actor_asset_request_manifest(actor_model_path, repo_root=repo_root)
        if actor_manifest["actor_id"] != actor_key:
            raise ValueError(
                f"actor roster plan actor_pool.{actor_key} points to actor package "
                f"{actor_manifest['actor_id']}"
            )

        actor_requests = copy.deepcopy(actor_manifest["requests"])
        requests.extend(actor_requests)
        role_ids = [
            str(role_id)
            for role_id, slot in cast_slots.items()
            if isinstance(slot, Mapping) and str(slot.get("actor_id") or "").strip() == actor_key
        ]
        actors[actor_key] = {
            "actor_id": actor_key,
            "preset_id": str(actor_data.get("preset_id") or ""),
            "source_actor_model_path": actor_manifest["source_actor_model_path"],
            "template_version": actor_manifest["template_version"],
            "readiness_state": actor_manifest["readiness_state"],
            "role_ids": role_ids,
            "request_count": actor_manifest["request_count"],
        }

    return {
        "schema": "reverie.pack.actor_roster.asset_requests.v1",
        "pack_id": pack_id,
        "actor_count": len(actors),
        "request_count": len(requests),
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
        "actors": actors,
        "requests": requests,
    }


def write_actor_roster_asset_request_manifest(
    roster_plan_path: Path | str,
    output_path: Path | str,
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> Path:
    """Write one combined public-safe asset request manifest for a roster plan."""
    roster_plan = _load_json_object(roster_plan_path, "actor roster plan")
    manifest = build_actor_roster_asset_request_manifest(
        roster_plan,
        actor_root=actor_root,
        repo_root=repo_root,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def build_actor_roster_layer_spec_manifest(
    roster_plan: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Build one public-safe layer spec manifest for every actor in a roster plan."""
    patch = _validate_roster_plan(roster_plan)
    pack_id = str(roster_plan.get("pack_id") or "").strip()
    if not pack_id:
        raise ValueError("actor roster plan pack_id is required")

    actor_pool = patch["actor_pool"]
    if not actor_pool:
        raise ValueError("actor roster plan motiontoon_patch.actor_pool must not be empty")

    cast_slots = patch["cast_slots"]
    actors: dict[str, Any] = {}
    for actor_id, actor_data in actor_pool.items():
        actor_key = str(actor_id or "").strip()
        if not actor_key:
            raise ValueError("actor roster plan actor_pool contains an empty actor id")
        if not isinstance(actor_data, Mapping):
            raise ValueError(f"actor roster plan actor_pool.{actor_key} must be an object")

        actor_model_path = _actor_model_path_from_roster_actor(
            actor_key,
            actor_data,
            actor_root=actor_root,
            repo_root=repo_root,
        )
        layer_spec = build_actor_layer_spec_manifest(actor_model_path, repo_root=repo_root)
        if layer_spec["actor_id"] != actor_key:
            raise ValueError(
                f"actor roster plan actor_pool.{actor_key} points to actor package "
                f"{layer_spec['actor_id']}"
            )

        role_ids = [
            str(role_id)
            for role_id, slot in cast_slots.items()
            if isinstance(slot, Mapping) and str(slot.get("actor_id") or "").strip() == actor_key
        ]
        actor_spec = copy.deepcopy(layer_spec)
        actor_spec["preset_id"] = str(actor_data.get("preset_id") or "")
        actor_spec["role_ids"] = role_ids
        actors[actor_key] = actor_spec

    return {
        "schema": "reverie.pack.actor_roster.layer_specs.v1",
        "pack_id": pack_id,
        "actor_count": len(actors),
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
        "actors": actors,
    }


def write_actor_roster_layer_spec_manifest(
    roster_plan_path: Path | str,
    output_path: Path | str,
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> Path:
    """Write one combined public-safe layer spec manifest for a roster plan."""
    roster_plan = _load_json_object(roster_plan_path, "actor roster plan")
    manifest = build_actor_roster_layer_spec_manifest(
        roster_plan,
        actor_root=actor_root,
        repo_root=repo_root,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _scene_value(scene: Any, key: str, default: Any = "") -> Any:
    if isinstance(scene, Mapping):
        return scene.get(key, default)
    return getattr(scene, key, default)


def _normalize_scene_emotion(value: Any) -> str:
    emotion = str(value or "neutral").strip().lower().replace("-", "_") or "neutral"
    aliases = {
        "fear": "scared",
        "fearful": "scared",
        "afraid": "scared",
        "sadness": "sad",
        "concerned": "worried",
        "anxious": "worried",
        "talk": "talking",
        "speaking": "talking",
    }
    return aliases.get(emotion, emotion)


def _normalize_scene_pose(value: Any) -> str:
    pose = str(value or "standing").strip().lower().replace("-", "_") or "standing"
    aliases = {
        "sit": "seated",
        "sitting": "seated",
        "front": "standing",
        "forward": "standing",
        "idle": "standing",
    }
    return aliases.get(pose, pose)


def _scene_has_dialogue(scene: Any) -> bool:
    for key in ("line", "dialogue", "text", "speech"):
        if str(_scene_value(scene, key, "") or "").strip():
            return True
    return bool(_scene_value(scene, "is_speaking", False))


def _mouth_shape_for_scene(scene: Any) -> str:
    return "mouth_small_open" if _scene_has_dialogue(scene) else "mouth_closed"


def _eye_shape_for_emotion(emotion: str) -> str:
    if emotion == "angry":
        return "eyes_angry"
    if emotion in {"worried", "sad", "scared"}:
        return "eyes_worried"
    return "eyes_open"


def _asset_request_index(actor_manifest: Mapping[str, Any], request_type: str) -> dict[str, dict[str, Any]]:
    return {
        str(request.get("key") or ""): dict(request)
        for request in actor_manifest.get("requests", [])
        if isinstance(request, Mapping) and request.get("request_type") == request_type
    }


def _videotoon_contract_helpers() -> tuple[Any, Any]:
    try:
        from utils.videotoon_contract import DEFAULT_REQUIRED_SCENE_FIELDS, validate_episode_actor_contract
    except ModuleNotFoundError:
        from .videotoon_contract import DEFAULT_REQUIRED_SCENE_FIELDS, validate_episode_actor_contract
    return DEFAULT_REQUIRED_SCENE_FIELDS, validate_episode_actor_contract


def build_actor_episode_asset_plan(
    roster_plan: Mapping[str, Any],
    episode: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Map episode scenes to fixed actor variant assets before generation."""
    if not isinstance(episode, Mapping):
        raise ValueError("episode must contain a JSON object")
    patch = _validate_roster_plan(roster_plan)
    pack_id = str(roster_plan.get("pack_id") or "").strip()
    if not pack_id:
        raise ValueError("actor roster plan pack_id is required")

    actor_pool = patch["actor_pool"]
    role_contract = dict(patch["role_casting_contract"])
    assignment_key = str(role_contract.get("assignment_key") or "role_casting")
    normalized_episode = copy.deepcopy(dict(episode))
    if not isinstance(normalized_episode.get(assignment_key), Mapping):
        seed = roster_plan.get("episode_cast_seed")
        if isinstance(seed, Mapping) and isinstance(seed.get("role_casting"), Mapping):
            normalized_episode[assignment_key] = copy.deepcopy(dict(seed["role_casting"]))

    required_fields = role_contract.get("required_scene_fields")
    if not isinstance(required_fields, list):
        required_fields = None
    default_required_fields, validate_episode_actor_contract = _videotoon_contract_helpers()
    contract_result = validate_episode_actor_contract(
        normalized_episode,
        actor_pool,
        assignment_key=assignment_key,
        strict_actor_refs=bool(role_contract.get("strict_actor_refs", True)),
        allow_background_extras=bool(role_contract.get("allow_background_extras", True)),
        required_scene_fields=required_fields or default_required_fields,
    )

    actor_variant_requests: dict[str, dict[str, dict[str, Any]]] = {}
    actor_mouth_requests: dict[str, dict[str, dict[str, Any]]] = {}
    actor_eye_requests: dict[str, dict[str, dict[str, Any]]] = {}
    actors: dict[str, Any] = {}
    for actor_id, actor_data in actor_pool.items():
        actor_key = str(actor_id or "").strip()
        if not actor_key or not isinstance(actor_data, Mapping):
            continue
        actor_model_path = _actor_model_path_from_roster_actor(
            actor_key,
            actor_data,
            actor_root=actor_root,
            repo_root=repo_root,
        )
        actor_manifest = build_actor_asset_request_manifest(actor_model_path, repo_root=repo_root)
        actor_variant_requests[actor_key] = _asset_request_index(actor_manifest, "variant")
        actor_mouth_requests[actor_key] = _asset_request_index(actor_manifest, "mouth_shape")
        actor_eye_requests[actor_key] = _asset_request_index(actor_manifest, "eye_shape")
        actors[actor_key] = {
            "actor_id": actor_key,
            "preset_id": str(actor_data.get("preset_id") or ""),
            "source_actor_model_path": actor_manifest["source_actor_model_path"],
            "request_count": actor_manifest["request_count"],
        }

    scenes_input = normalized_episode.get("scenes") or []
    if not isinstance(scenes_input, list):
        scenes_input = []

    scenes: list[dict[str, Any]] = []
    errors = list(contract_result.errors)
    missing_variants: list[str] = []
    for index, scene in enumerate(scenes_input):
        scene_id = str(_scene_value(scene, "scene_id", f"scene_{index + 1:04d}") or "").strip()
        role_id = str(_scene_value(scene, "role_id", "") or "").strip()
        actor_id = str(_scene_value(scene, "actor_id", "") or "").strip()
        emotion = _normalize_scene_emotion(_scene_value(scene, "emotion", "neutral"))
        pose = _normalize_scene_pose(_scene_value(scene, "pose", "standing"))
        variant_key = str(_scene_value(scene, "variant_key", "") or "").strip() or f"{emotion}_{pose}"
        mouth_shape_key = _mouth_shape_for_scene(scene)
        eye_shape_key = _eye_shape_for_emotion(emotion)

        variant_key_is_safe = _is_safe_asset_key(variant_key)
        if not variant_key_is_safe:
            errors.append(f"scene {scene_id or index} variant_key '{variant_key}' is unsafe")
            variant_key = ""

        variant_request = actor_variant_requests.get(actor_id, {}).get(variant_key) if variant_key_is_safe else None
        mouth_request = actor_mouth_requests.get(actor_id, {}).get(mouth_shape_key, {})
        eye_request = actor_eye_requests.get(actor_id, {}).get(eye_shape_key, {})
        if variant_key_is_safe and not variant_request and actor_id:
            missing_key = f"{actor_id}:{variant_key}"
            missing_variants.append(missing_key)
            errors.append(f"scene {scene_id or index} actor {actor_id} missing variant {variant_key}")

        scenes.append(
            {
                "scene_id": scene_id,
                "role_id": role_id,
                "actor_id": actor_id,
                "emotion": emotion,
                "pose": pose,
                "shot_type": str(_scene_value(scene, "shot_type", "") or "").strip(),
                "variant_key": variant_key,
                "variant_available": bool(variant_request),
                "asset_request_id": str(variant_request.get("request_id", "")) if variant_request else "",
                "target_relative_path": str(variant_request.get("target_relative_path", "")) if variant_request else "",
                "mouth_shape_key": mouth_shape_key,
                "mouth_target_relative_path": str(mouth_request.get("target_relative_path", "")),
                "eye_shape_key": eye_shape_key,
                "eye_target_relative_path": str(eye_request.get("target_relative_path", "")),
            }
        )

    return {
        "schema": "reverie.pack.actor_episode_asset_plan.v1",
        "pack_id": pack_id,
        "episode_id": str(normalized_episode.get("episode_id") or ""),
        "is_valid": contract_result.is_valid and not missing_variants and not errors,
        "actor_count": len(actors),
        "scene_count": len(scenes),
        "missing_variant_count": len(missing_variants),
        "missing_variants": missing_variants,
        "errors": errors,
        "warnings": list(contract_result.warnings),
        "role_casting": copy.deepcopy(dict(normalized_episode.get(assignment_key) or {})),
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
        "actors": actors,
        "scenes": scenes,
    }


def write_actor_episode_asset_plan(
    roster_plan_path: Path | str,
    episode_path: Path | str,
    output_path: Path | str,
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> Path:
    """Write an episode scene-to-actor-asset plan."""
    roster_plan = _load_json_object(roster_plan_path, "actor roster plan")
    episode = _load_json_object(episode_path, "episode")
    manifest = build_actor_episode_asset_plan(
        roster_plan,
        episode,
        actor_root=actor_root,
        repo_root=repo_root,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _validate_episode_asset_plan(asset_plan: Mapping[str, Any]) -> None:
    if not isinstance(asset_plan, Mapping):
        raise ValueError("episode asset plan must be an object")
    if asset_plan.get("schema") != "reverie.pack.actor_episode_asset_plan.v1":
        raise ValueError("episode asset plan schema must be reverie.pack.actor_episode_asset_plan.v1")
    if not isinstance(asset_plan.get("actors", {}), Mapping):
        raise ValueError("episode asset plan actors must be an object")
    if not isinstance(asset_plan.get("scenes", []), list):
        raise ValueError("episode asset plan scenes must be a list")


def _actor_dir_from_episode_asset_plan(
    asset_plan: Mapping[str, Any],
    actor_id: str,
    *,
    actor_root: Optional[Path | str],
    repo_root: Optional[Path | str],
) -> Path:
    if not ACTOR_ID_PATTERN.fullmatch(actor_id):
        raise ValueError(f"episode asset plan actor_id is unsafe: {actor_id}")
    if actor_root is not None:
        return _resolve_actor_root(actor_root, repo_root) / actor_id
    actor_data = asset_plan.get("actors", {}).get(actor_id)
    if not isinstance(actor_data, Mapping):
        raise ValueError(f"episode asset plan actors.{actor_id} is required")
    source_path = str(actor_data.get("source_actor_model_path") or "").strip()
    if not source_path:
        raise ValueError(f"episode asset plan actors.{actor_id}.source_actor_model_path is required")
    actor_path, path_error = _resolve_actor_path(source_path, repo_root)
    if path_error:
        raise ValueError(path_error)
    return actor_path.parent


def _episode_scene_asset_specs(scene: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    return [
        ("variant", str(scene.get("variant_key") or ""), str(scene.get("target_relative_path") or "")),
        ("mouth_shape", str(scene.get("mouth_shape_key") or ""), str(scene.get("mouth_target_relative_path") or "")),
        ("eye_shape", str(scene.get("eye_shape_key") or ""), str(scene.get("eye_target_relative_path") or "")),
    ]


def build_actor_episode_asset_coverage_report(
    asset_plan: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Report local file coverage for every scene asset referenced by an episode plan."""
    _validate_episode_asset_plan(asset_plan)
    expected_assets: list[dict[str, Any]] = []
    missing_assets: list[str] = []
    errors = list(asset_plan.get("errors") or [])
    existing_count = 0

    for scene in asset_plan.get("scenes", []):
        if not isinstance(scene, Mapping):
            continue
        scene_id = str(scene.get("scene_id") or "")
        actor_id = str(scene.get("actor_id") or "").strip()
        if not actor_id:
            errors.append(f"scene {scene_id} actor_id is required for asset coverage")
            continue
        actor_dir = _actor_dir_from_episode_asset_plan(
            asset_plan,
            actor_id,
            actor_root=actor_root,
            repo_root=repo_root,
        )
        for asset_type, key, relative_path in _episode_scene_asset_specs(scene):
            asset_ref = f"{scene_id}:{actor_id}:{asset_type}:{key or '<missing-key>'}"
            if not key or not relative_path:
                missing_assets.append(asset_ref)
                expected_assets.append(
                    {
                        "scene_id": scene_id,
                        "actor_id": actor_id,
                        "asset_type": asset_type,
                        "key": key,
                        "target_relative_path": relative_path,
                        "exists": False,
                    }
                )
                continue

            try:
                target_path = _safe_actor_asset_path(actor_dir, relative_path)
            except ValueError:
                missing_assets.append(asset_ref)
                errors.append(f"scene {scene_id} {asset_type} path is unsafe")
                expected_assets.append(
                    {
                        "scene_id": scene_id,
                        "actor_id": actor_id,
                        "asset_type": asset_type,
                        "key": key,
                        "target_relative_path": relative_path,
                        "exists": False,
                    }
                )
                continue
            exists = target_path.is_file()
            if exists:
                existing_count += 1
            else:
                missing_assets.append(asset_ref)
            expected_assets.append(
                {
                    "scene_id": scene_id,
                    "actor_id": actor_id,
                    "asset_type": asset_type,
                    "key": key,
                    "target_relative_path": relative_path,
                    "exists": exists,
                }
            )

    expected_count = len(expected_assets)
    missing_count = expected_count - existing_count
    coverage_ratio = round(existing_count / expected_count, 4) if expected_count else 1.0
    ready_for_render = bool(asset_plan.get("is_valid")) and missing_count == 0 and not errors
    return {
        "schema": "reverie.pack.actor_episode.asset_coverage.v1",
        "pack_id": str(asset_plan.get("pack_id") or ""),
        "episode_id": str(asset_plan.get("episode_id") or ""),
        "source_asset_plan_valid": bool(asset_plan.get("is_valid")),
        "scene_count": int(asset_plan.get("scene_count") or len(asset_plan.get("scenes", []))),
        "expected_count": expected_count,
        "existing_count": existing_count,
        "missing_count": missing_count,
        "coverage_ratio": coverage_ratio,
        "ready_for_render": ready_for_render,
        "errors": errors,
        "missing_assets": missing_assets,
        "expected_assets": expected_assets,
    }


def write_actor_episode_asset_coverage_report(
    asset_plan_path: Path | str,
    output_path: Path | str,
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> Path:
    """Write episode scene asset coverage and return the output path."""
    asset_plan = _load_json_object(asset_plan_path, "episode asset plan")
    report = build_actor_episode_asset_coverage_report(
        asset_plan,
        actor_root=actor_root,
        repo_root=repo_root,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _build_episode_variant_request(
    actor_model_path: Path | str,
    *,
    actor_id: str,
    variant_key: str,
    expression: str,
    pose: str,
    scene_ids: list[str],
    shot_types: list[str],
    repo_root: Optional[Path | str],
) -> dict[str, Any]:
    if not _is_safe_asset_key(variant_key):
        raise ValueError(f"episode variant key is unsafe: {variant_key}")
    validation = validate_actor_model_package(actor_model_path, repo_root=repo_root, allow_local_media=True)
    if not validation.is_valid:
        raise ValueError("actor model validation failed: " + "; ".join(validation.errors))
    actor_path, path_error = _resolve_actor_path(actor_model_path, repo_root)
    if path_error:
        raise ValueError(path_error)

    actor_dir = actor_path.parent
    identity_prompt = _read_template(actor_dir, "prompts/identity_prompt.txt")
    variant_prompt = _read_template(actor_dir, "prompts/variant_prompt.txt")
    negative_prompt = _read_template(actor_dir, "prompts/negative_prompt.txt")
    prompt = "\n\n".join(
        [
            identity_prompt,
            variant_prompt,
            f"Episode supplement variant: {variant_key}",
            f"Expression: {expression}",
            f"Pose: {pose}",
            f"Scene ids: {', '.join(scene_ids)}",
            f"Shot types: {', '.join(shot_types)}",
            "Output: one transparent-capable half-body video-toon actor image, no background, no text.",
        ]
    )
    request = _asset_request(
        actor_id=actor_id,
        request_type="variant",
        key=variant_key,
        target_relative_path=f"variants/{variant_key}.png",
        prompt=prompt,
        negative_prompt=negative_prompt,
        expression=expression,
        pose=pose,
    )
    request["source"] = "episode_missing_variant"
    request["scene_ids"] = scene_ids
    request["shot_types"] = shot_types
    request["source_actor_model_path"] = _relative_to_root(actor_path, repo_root)
    return request


def build_actor_episode_variant_request_manifest(
    roster_plan: Mapping[str, Any],
    episode: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Build supplemental variant requests for episode scenes missing actor assets."""
    patch = _validate_roster_plan(roster_plan)
    actor_pool = patch["actor_pool"]
    episode_plan = build_actor_episode_asset_plan(
        roster_plan,
        episode,
        actor_root=actor_root,
        repo_root=repo_root,
    )

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for scene in episode_plan["scenes"]:
        if scene.get("variant_available"):
            continue
        actor_id = str(scene.get("actor_id") or "").strip()
        variant_key = str(scene.get("variant_key") or "").strip()
        if not actor_id or not variant_key:
            continue
        group_key = (actor_id, variant_key)
        grouped.setdefault(
            group_key,
            {
                "actor_id": actor_id,
                "variant_key": variant_key,
                "expression": str(scene.get("emotion") or "neutral"),
                "pose": str(scene.get("pose") or "standing"),
                "scene_ids": [],
                "shot_types": [],
            },
        )
        scene_id = str(scene.get("scene_id") or "").strip()
        shot_type = str(scene.get("shot_type") or "").strip()
        if scene_id and scene_id not in grouped[group_key]["scene_ids"]:
            grouped[group_key]["scene_ids"].append(scene_id)
        if shot_type and shot_type not in grouped[group_key]["shot_types"]:
            grouped[group_key]["shot_types"].append(shot_type)

    requests: list[dict[str, Any]] = []
    for (actor_id, _variant_key), group in grouped.items():
        actor_data = actor_pool.get(actor_id)
        if not isinstance(actor_data, Mapping):
            continue
        actor_model_path = _actor_model_path_from_roster_actor(
            actor_id,
            actor_data,
            actor_root=actor_root,
            repo_root=repo_root,
        )
        requests.append(
            _build_episode_variant_request(
                actor_model_path,
                actor_id=actor_id,
                variant_key=group["variant_key"],
                expression=group["expression"],
                pose=group["pose"],
                scene_ids=group["scene_ids"],
                shot_types=group["shot_types"],
                repo_root=repo_root,
            )
        )

    return {
        "schema": "reverie.pack.actor_episode.variant_requests.v1",
        "pack_id": episode_plan["pack_id"],
        "episode_id": episode_plan["episode_id"],
        "source_episode_asset_plan_schema": episode_plan["schema"],
        "source_missing_variant_count": episode_plan["missing_variant_count"],
        "request_count": len(requests),
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
        "requests": requests,
    }


def write_actor_episode_variant_request_manifest(
    roster_plan_path: Path | str,
    episode_path: Path | str,
    output_path: Path | str,
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> Path:
    """Write supplemental variant requests for missing episode actor assets."""
    roster_plan = _load_json_object(roster_plan_path, "actor roster plan")
    episode = _load_json_object(episode_path, "episode")
    manifest = build_actor_episode_variant_request_manifest(
        roster_plan,
        episode,
        actor_root=actor_root,
        repo_root=repo_root,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _validate_episode_variant_request_manifest(manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest, Mapping):
        raise ValueError("episode variant request manifest must be an object")
    if manifest.get("schema") != "reverie.pack.actor_episode.variant_requests.v1":
        raise ValueError("episode variant request manifest schema must be reverie.pack.actor_episode.variant_requests.v1")
    boundary = manifest.get("public_release_boundary")
    if not isinstance(boundary, Mapping):
        raise ValueError("episode variant request manifest public_release_boundary must be an object")
    for field_name in ("contains_generated_media", "contains_voice_samples", "contains_model_weights", "contains_private_paths"):
        if boundary.get(field_name) is not False:
            raise ValueError(f"episode variant request manifest public_release_boundary.{field_name} must be false")
    if not isinstance(manifest.get("requests", []), list):
        raise ValueError("episode variant request manifest requests must be a list")


def _actor_dir_from_variant_request(
    request: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str],
    repo_root: Optional[Path | str],
) -> Path:
    actor_id = str(request.get("actor_id") or "").strip()
    if not actor_id:
        raise ValueError("episode variant request actor_id is required")
    if not ACTOR_ID_PATTERN.fullmatch(actor_id):
        raise ValueError(f"episode variant request actor_id is unsafe: {actor_id}")
    if actor_root is not None:
        return _resolve_actor_root(actor_root, repo_root) / actor_id

    source_path = str(request.get("source_actor_model_path") or "").strip()
    if not source_path:
        raise ValueError(f"episode variant request {actor_id} source_actor_model_path is required without actor_root")
    actor_path, path_error = _resolve_actor_path(source_path, repo_root)
    if path_error:
        raise ValueError(path_error)
    return actor_path.parent


def build_actor_episode_variant_coverage_report(
    request_manifest: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Report whether supplemental episode variant request outputs exist locally."""
    _validate_episode_variant_request_manifest(request_manifest)
    expected_assets: list[dict[str, Any]] = []
    missing_variants: list[str] = []
    existing_count = 0

    for request in request_manifest.get("requests", []):
        if not isinstance(request, Mapping):
            continue
        if request.get("request_type") != "variant":
            continue
        actor_id = str(request.get("actor_id") or "").strip()
        variant_key = str(request.get("key") or "").strip()
        target_relative_path = str(request.get("target_relative_path") or "").strip()
        if not actor_id or not variant_key or not target_relative_path:
            raise ValueError("episode variant request requires actor_id, key, and target_relative_path")

        actor_dir = _actor_dir_from_variant_request(request, actor_root=actor_root, repo_root=repo_root)
        target_path = _safe_actor_asset_path(actor_dir, target_relative_path)
        exists = target_path.is_file()
        if exists:
            existing_count += 1
        else:
            missing_variants.append(f"{actor_id}:{variant_key}")
        expected_assets.append(
            {
                "request_id": str(request.get("request_id") or ""),
                "actor_id": actor_id,
                "key": variant_key,
                "target_relative_path": target_relative_path,
                "scene_ids": list(request.get("scene_ids") or []),
                "exists": exists,
            }
        )

    expected_count = len(expected_assets)
    missing_count = expected_count - existing_count
    coverage_ratio = round(existing_count / expected_count, 4) if expected_count else 1.0
    return {
        "schema": "reverie.pack.actor_episode.variant_coverage.v1",
        "pack_id": str(request_manifest.get("pack_id") or ""),
        "episode_id": str(request_manifest.get("episode_id") or ""),
        "expected_count": expected_count,
        "existing_count": existing_count,
        "missing_count": missing_count,
        "coverage_ratio": coverage_ratio,
        "ready_for_episode": missing_count == 0,
        "missing_variants": missing_variants,
        "expected_assets": expected_assets,
    }


def write_actor_episode_variant_coverage_report(
    request_manifest_path: Path | str,
    output_path: Path | str,
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> Path:
    """Write supplemental episode variant coverage and return the output path."""
    request_manifest = _load_json_object(request_manifest_path, "episode variant request manifest")
    report = build_actor_episode_variant_coverage_report(
        request_manifest,
        actor_root=actor_root,
        repo_root=repo_root,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _validate_episode_variant_coverage_report(report: Mapping[str, Any]) -> None:
    if not isinstance(report, Mapping):
        raise ValueError("episode variant coverage report must be an object")
    if report.get("schema") != "reverie.pack.actor_episode.variant_coverage.v1":
        raise ValueError("episode variant coverage report schema must be reverie.pack.actor_episode.variant_coverage.v1")
    if not isinstance(report.get("expected_assets", []), list):
        raise ValueError("episode variant coverage report expected_assets must be a list")


def _actor_path_for_promotion(
    actor_id: str,
    asset: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str],
    repo_root: Optional[Path | str],
) -> Path:
    if not ACTOR_ID_PATTERN.fullmatch(actor_id):
        raise ValueError(f"episode variant promotion actor_id is unsafe: {actor_id}")
    if actor_root is not None:
        return _resolve_actor_root(actor_root, repo_root) / actor_id / "actor.json"
    source_path = str(asset.get("source_actor_model_path") or "").strip()
    if not source_path:
        raise ValueError(f"episode variant promotion for {actor_id} requires actor_root or source_actor_model_path")
    actor_path, path_error = _resolve_actor_path(source_path, repo_root)
    if path_error:
        raise ValueError(path_error)
    return actor_path


def build_actor_episode_variant_promotion_plan(
    coverage_report: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Plan durable actor.json required_variants additions from ready episode coverage."""
    _validate_episode_variant_coverage_report(coverage_report)
    errors: list[str] = []
    if coverage_report.get("ready_for_episode") is not True or int(coverage_report.get("missing_count") or 0) > 0:
        errors.append("episode variant coverage is not ready for promotion; missing variants remain")
        return {
            "schema": "reverie.pack.actor_episode.variant_promotions.v1",
            "pack_id": str(coverage_report.get("pack_id") or ""),
            "episode_id": str(coverage_report.get("episode_id") or ""),
            "ready_for_promotion": False,
            "promotion_count": 0,
            "skipped_existing_count": 0,
            "errors": errors,
            "public_release_boundary": {
                "contains_generated_media": False,
                "contains_voice_samples": False,
                "contains_model_weights": False,
                "contains_private_paths": False,
            },
            "actors": {},
        }

    actor_groups: dict[str, list[Mapping[str, Any]]] = {}
    for asset in coverage_report.get("expected_assets", []):
        if not isinstance(asset, Mapping) or asset.get("exists") is not True:
            continue
        actor_id = str(asset.get("actor_id") or "").strip()
        variant_key = str(asset.get("key") or "").strip()
        if not actor_id or not variant_key:
            raise ValueError("episode variant coverage expected_assets require actor_id and key")
        actor_groups.setdefault(actor_id, []).append(asset)

    actors: dict[str, Any] = {}
    promotion_count = 0
    skipped_existing_count = 0
    for actor_id, assets in actor_groups.items():
        actor_path = _actor_path_for_promotion(actor_id, assets[0], actor_root=actor_root, repo_root=repo_root)
        actor_data = _load_actor_json(actor_path, ActorModelValidationResult())
        if not actor_data:
            raise ValueError(f"actor.json could not be loaded for {actor_id}: {actor_path}")
        required_before = _string_list(actor_data.get("required_variants"))
        required_after = list(required_before)
        promoted_variants: list[str] = []
        skipped_existing: list[str] = []

        for asset in assets:
            variant_key = str(asset.get("key") or "").strip()
            if variant_key in required_after:
                skipped_existing.append(variant_key)
                skipped_existing_count += 1
                continue
            required_after.append(variant_key)
            promoted_variants.append(variant_key)
            promotion_count += 1

        actors[actor_id] = {
            "actor_id": actor_id,
            "actor_model_path": _relative_to_root(actor_path, repo_root),
            "promoted_variants": promoted_variants,
            "skipped_existing_variants": skipped_existing,
            "required_variants_before": required_before,
            "required_variants_after": required_after,
        }

    return {
        "schema": "reverie.pack.actor_episode.variant_promotions.v1",
        "pack_id": str(coverage_report.get("pack_id") or ""),
        "episode_id": str(coverage_report.get("episode_id") or ""),
        "ready_for_promotion": not errors,
        "promotion_count": promotion_count,
        "skipped_existing_count": skipped_existing_count,
        "errors": errors,
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
        "actors": actors,
    }


def write_actor_episode_variant_promotion_plan(
    coverage_report_path: Path | str,
    output_path: Path | str,
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> Path:
    """Write a durable variant promotion plan without mutating actor.json."""
    coverage_report = _load_json_object(coverage_report_path, "episode variant coverage report")
    plan = build_actor_episode_variant_promotion_plan(
        coverage_report,
        actor_root=actor_root,
        repo_root=repo_root,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _validate_episode_variant_promotion_plan(plan: Mapping[str, Any]) -> None:
    if not isinstance(plan, Mapping):
        raise ValueError("episode variant promotion plan must be an object")
    if plan.get("schema") != "reverie.pack.actor_episode.variant_promotions.v1":
        raise ValueError("episode variant promotion plan schema must be reverie.pack.actor_episode.variant_promotions.v1")
    boundary = plan.get("public_release_boundary")
    if isinstance(boundary, Mapping):
        for field_name in ("contains_generated_media", "contains_voice_samples", "contains_model_weights", "contains_private_paths"):
            if boundary.get(field_name) is not False:
                raise ValueError(f"episode variant promotion plan public_release_boundary.{field_name} must be false")
    if not isinstance(plan.get("actors", {}), Mapping):
        raise ValueError("episode variant promotion plan actors must be an object")


def _actor_path_from_promotion_actor(
    actor_id: str,
    actor_plan: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str],
    repo_root: Optional[Path | str],
) -> Path:
    if not ACTOR_ID_PATTERN.fullmatch(actor_id):
        raise ValueError(f"episode variant promotion actor_id is unsafe: {actor_id}")
    if actor_root is not None:
        return _resolve_actor_root(actor_root, repo_root) / actor_id / "actor.json"
    actor_model_path = str(actor_plan.get("actor_model_path") or "").strip()
    if not actor_model_path:
        raise ValueError(f"episode variant promotion actor {actor_id} actor_model_path is required without actor_root")
    actor_path, path_error = _resolve_actor_path(actor_model_path, repo_root)
    if path_error:
        raise ValueError(path_error)
    return actor_path


def apply_actor_episode_variant_promotion_plan(
    promotion_plan: Mapping[str, Any],
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Apply a ready promotion plan to actor.json required_variants."""
    _validate_episode_variant_promotion_plan(promotion_plan)
    if promotion_plan.get("ready_for_promotion") is not True:
        raise ValueError("episode variant promotion plan is not ready")

    actors: dict[str, Any] = {}
    applied_count = 0
    skipped_existing_count = 0
    for actor_id, actor_plan in promotion_plan.get("actors", {}).items():
        actor_key = str(actor_id or "").strip()
        if not actor_key:
            raise ValueError("episode variant promotion plan contains an empty actor id")
        if not isinstance(actor_plan, Mapping):
            raise ValueError(f"episode variant promotion plan actors.{actor_key} must be an object")

        actor_path = _actor_path_from_promotion_actor(
            actor_key,
            actor_plan,
            actor_root=actor_root,
            repo_root=repo_root,
        )
        actor_data = _load_actor_json(actor_path, ActorModelValidationResult())
        if not actor_data:
            raise ValueError(f"actor.json could not be loaded for {actor_key}: {actor_path}")

        required_before = _string_list(actor_data.get("required_variants"))
        required_after = list(required_before)
        added_variants: list[str] = []
        skipped_existing: list[str] = []
        for variant_key in _string_list(actor_plan.get("promoted_variants")):
            if variant_key in required_after:
                skipped_existing.append(variant_key)
                skipped_existing_count += 1
                continue
            required_after.append(variant_key)
            added_variants.append(variant_key)
            applied_count += 1

        actor_data["required_variants"] = required_after
        actor_path.write_text(json.dumps(actor_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        actors[actor_key] = {
            "actor_id": actor_key,
            "actor_model_path": _relative_to_root(actor_path, repo_root),
            "added_variants": added_variants,
            "skipped_existing_variants": skipped_existing,
            "required_variants_before": required_before,
            "required_variants_after": required_after,
        }

    return {
        "schema": "reverie.pack.actor_episode.variant_promotion_apply.v1",
        "pack_id": str(promotion_plan.get("pack_id") or ""),
        "episode_id": str(promotion_plan.get("episode_id") or ""),
        "applied_count": applied_count,
        "skipped_existing_count": skipped_existing_count,
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
        "actors": actors,
    }


def write_applied_actor_episode_variant_promotion_plan(
    promotion_plan_path: Path | str,
    output_path: Path | str,
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> Path:
    """Apply a promotion plan and write an apply report."""
    promotion_plan = _load_json_object(promotion_plan_path, "episode variant promotion plan")
    report = apply_actor_episode_variant_promotion_plan(
        promotion_plan,
        actor_root=actor_root,
        repo_root=repo_root,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def build_actor_asset_coverage_report(
    actor_model_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Report whether locally generated actor assets exist for each request."""
    actor_path, actor_data = _load_actor_contract(actor_model_path, repo_root)
    validation = _validation_from_contract(actor_path, actor_data)
    if not validation.is_valid:
        raise ValueError("actor model contract validation failed: " + "; ".join(validation.errors))
    actor_dir = actor_path.parent
    requests = _build_asset_requests_from_contract(actor_path, validation)

    expected_assets: list[dict[str, Any]] = []
    missing_assets: list[str] = []
    existing_count = 0
    for request in requests:
        relative_path = str(request["target_relative_path"])
        target_path = _safe_actor_asset_path(actor_dir, relative_path)
        exists = target_path.is_file()
        if exists:
            existing_count += 1
        else:
            missing_assets.append(relative_path)
        expected_assets.append(
            {
                "request_id": request["request_id"],
                "request_type": request["request_type"],
                "key": request["key"],
                "target_relative_path": relative_path,
                "exists": exists,
            }
        )

    expected_count = len(expected_assets)
    missing_count = len(missing_assets)
    coverage_ratio = round(existing_count / expected_count, 4) if expected_count else 1.0
    return {
        "schema": "reverie.actor_model.asset_coverage.v1",
        "actor_id": validation.actor_id,
        "source_actor_model_path": _relative_to_root(actor_path, repo_root),
        "expected_count": expected_count,
        "existing_count": existing_count,
        "missing_count": missing_count,
        "coverage_ratio": coverage_ratio,
        "ready_for_local_test": missing_count == 0,
        "missing_assets": missing_assets,
        "expected_assets": expected_assets,
    }


def write_actor_asset_coverage_report(
    actor_model_path: Path | str,
    output_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
) -> Path:
    """Write a local actor asset coverage report and return the output path."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = build_actor_asset_coverage_report(actor_model_path, repo_root=repo_root)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _load_pack_settings(settings_path: Path | str, repo_root: Optional[Path | str]) -> tuple[Path, dict[str, Any]]:
    raw_path = Path(settings_path)
    root = Path(repo_root).resolve() if repo_root is not None else None
    path = raw_path.resolve() if raw_path.is_absolute() else ((root or Path.cwd()) / raw_path).resolve()
    if not path.exists():
        raise ValueError(f"pack settings path does not exist: {settings_path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("pack settings must contain a JSON object")
    return path, data


def _actor_model_entries_from_settings(settings: Mapping[str, Any]) -> dict[str, str]:
    motiontoon = settings.get("motiontoon")
    if not isinstance(motiontoon, Mapping):
        return {}
    actor_pool = motiontoon.get("actor_pool")
    if not isinstance(actor_pool, Mapping):
        return {}

    entries: dict[str, str] = {}
    for actor_id, actor_data in actor_pool.items():
        if not isinstance(actor_data, Mapping):
            continue
        actor_model_path = str(actor_data.get("actor_model_path") or "").strip()
        actor_key = str(actor_id or "").strip()
        if actor_key and actor_model_path:
            entries[actor_key] = actor_model_path
    return entries


def build_pack_actor_asset_coverage_report(
    settings_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Aggregate actor asset coverage for every actor_model_path in a pack settings file."""
    settings_file, settings = _load_pack_settings(settings_path, repo_root)
    actor_model_entries = _actor_model_entries_from_settings(settings)
    actors: dict[str, Any] = {}
    expected_count = 0
    existing_count = 0
    missing_count = 0

    for actor_id, actor_model_path in actor_model_entries.items():
        try:
            actor_report = build_actor_asset_coverage_report(actor_model_path, repo_root=repo_root)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            actors[actor_id] = {
                "actor_id": actor_id,
                "actor_model_path": actor_model_path,
                "is_valid": False,
                "errors": [str(exc)],
                "expected_count": 0,
                "existing_count": 0,
                "missing_count": 0,
                "ready_for_local_test": False,
            }
            missing_count += 1
            continue

        actor_report["is_valid"] = True
        actor_report["actor_model_path"] = actor_model_path
        actors[actor_id] = actor_report
        expected_count += int(actor_report["expected_count"])
        existing_count += int(actor_report["existing_count"])
        missing_count += int(actor_report["missing_count"])

    coverage_ratio = round(existing_count / expected_count, 4) if expected_count else 1.0
    return {
        "schema": "reverie.pack.actor_asset_coverage.v1",
        "pack_settings_path": _relative_to_root(settings_file, repo_root),
        "actor_model_count": len(actor_model_entries),
        "expected_count": expected_count,
        "existing_count": existing_count,
        "missing_count": missing_count,
        "coverage_ratio": coverage_ratio,
        "ready_for_local_test": bool(actor_model_entries) and missing_count == 0,
        "actors": actors,
    }


def write_pack_actor_asset_coverage_report(
    settings_path: Path | str,
    output_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
) -> Path:
    """Write a pack-level actor asset coverage report and return the output path."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = build_pack_actor_asset_coverage_report(settings_path, repo_root=repo_root)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold actor models, validate them, and write local asset request manifests."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scaffold_parser = subparsers.add_parser("scaffold", help="Create a public-safe actor model template package.")
    scaffold_parser.add_argument("actor_id", help="Actor model id, for example actor_middle_man_01")
    scaffold_parser.add_argument("--actor-root", default=None, help="Directory that contains actor model folders.")
    scaffold_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    scaffold_parser.add_argument("--display-name", default="", help="Human-readable actor name.")
    scaffold_parser.add_argument("--age-band", default="adult", help="Stable age band for the actor identity lock.")
    scaffold_parser.add_argument(
        "--gender-presentation",
        default="unspecified",
        help="Stable gender presentation for the actor identity lock.",
    )
    scaffold_parser.add_argument(
        "--role-range",
        default=",".join(DEFAULT_ROLE_RANGE),
        help="Comma-separated roles this actor can be cast into.",
    )
    scaffold_parser.add_argument(
        "--visual-identity",
        default="",
        help="Short reusable visual identity description for the actor.",
    )
    scaffold_parser.add_argument(
        "--voice-profile",
        default="neutral_01",
        help="Recommended stable voice slot for this actor.",
    )
    scaffold_parser.add_argument("--force", action="store_true", help="Overwrite an existing actor scaffold.")

    preset_parser = subparsers.add_parser(
        "scaffold-preset",
        help="Create a public-safe actor model package from a preset catalog entry.",
    )
    preset_parser.add_argument("preset_id", help="Preset key from assets/actor_model_presets/catalog.json")
    preset_parser.add_argument("actor_id", help="Actor model id to create from the preset")
    preset_parser.add_argument("--actor-root", default=None, help="Directory that contains actor model folders.")
    preset_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    preset_parser.add_argument("--catalog", default=None, help="Preset catalog JSON path.")
    preset_parser.add_argument("--force", action="store_true", help="Overwrite an existing actor scaffold.")

    sample_assets_parser = subparsers.add_parser(
        "scaffold-sample-assets",
        help="Create local placeholder PNG assets for one actor model.",
    )
    sample_assets_parser.add_argument("actor_model_path", help="Path to actor.json")
    sample_assets_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    sample_assets_parser.add_argument("--output", default=None, help="Output JSON report path. Prints JSON when omitted.")
    sample_assets_parser.add_argument("--force", action="store_true", help="Overwrite existing placeholder PNG assets.")

    roster_parser = subparsers.add_parser(
        "roster-plan",
        help="Build a pack motiontoon actor_pool/cast_slots plan from preset assignments.",
    )
    roster_parser.add_argument("pack_id", help="Pack id for the roster plan.")
    roster_parser.add_argument(
        "--assignment",
        action="append",
        required=True,
        help="Role assignment in role=preset:actor_id or role=preset:actor_id:alias1,alias2 format.",
    )
    roster_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    roster_parser.add_argument("--catalog", default=None, help="Preset catalog JSON path.")
    roster_parser.add_argument(
        "--actor-root-relative",
        default="assets/actor_models",
        help="Relative actor model root used inside actor_model_path values.",
    )
    roster_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")

    apply_roster_parser = subparsers.add_parser(
        "apply-roster-plan",
        help="Apply a roster plan JSON patch to a pack settings.json file.",
    )
    apply_roster_parser.add_argument("settings_path", help="Input pack settings.json path.")
    apply_roster_parser.add_argument("roster_plan_path", help="Input actor roster plan JSON path.")
    apply_roster_parser.add_argument("--output", default=None, help="Output settings JSON path. Prints JSON when omitted.")
    apply_roster_parser.add_argument("--force", action="store_true", help="Overwrite existing actor_pool or cast_slots entries.")

    scaffold_roster_parser = subparsers.add_parser(
        "scaffold-roster",
        help="Scaffold every actor model package referenced by a roster plan.",
    )
    scaffold_roster_parser.add_argument("roster_plan_path", help="Input actor roster plan JSON path.")
    scaffold_roster_parser.add_argument("--actor-root", default=None, help="Directory that contains actor model folders.")
    scaffold_roster_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    scaffold_roster_parser.add_argument("--catalog", default=None, help="Preset catalog JSON path.")
    scaffold_roster_parser.add_argument("--output", default=None, help="Output scaffold report path. Prints JSON when omitted.")
    scaffold_roster_parser.add_argument("--force", action="store_true", help="Overwrite existing actor scaffolds.")

    roster_request_parser = subparsers.add_parser(
        "roster-asset-requests",
        help="Build one JSON asset request manifest for every actor in a roster plan.",
    )
    roster_request_parser.add_argument("roster_plan_path", help="Input actor roster plan JSON path.")
    roster_request_parser.add_argument("--actor-root", default=None, help="Directory that contains actor model folders.")
    roster_request_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    roster_request_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")

    roster_layer_parser = subparsers.add_parser(
        "roster-layer-specs",
        help="Build one JSON layer spec manifest for every actor in a roster plan.",
    )
    roster_layer_parser.add_argument("roster_plan_path", help="Input actor roster plan JSON path.")
    roster_layer_parser.add_argument("--actor-root", default=None, help="Directory that contains actor model folders.")
    roster_layer_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    roster_layer_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")

    episode_asset_parser = subparsers.add_parser(
        "episode-asset-plan",
        help="Map episode scenes to fixed actor variant assets before generation.",
    )
    episode_asset_parser.add_argument("roster_plan_path", help="Input actor roster plan JSON path.")
    episode_asset_parser.add_argument("episode_path", help="Input episode JSON with role_casting and scenes.")
    episode_asset_parser.add_argument("--actor-root", default=None, help="Directory that contains actor model folders.")
    episode_asset_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    episode_asset_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")
    episode_asset_parser.add_argument("--fail-on-invalid", action="store_true", help="Exit 1 when the asset plan is invalid.")

    episode_asset_coverage_parser = subparsers.add_parser(
        "episode-asset-coverage",
        help="Report missing local variant, mouth, and eye assets for an episode asset plan.",
    )
    episode_asset_coverage_parser.add_argument("asset_plan_path", help="Input episode asset plan JSON path.")
    episode_asset_coverage_parser.add_argument("--actor-root", default=None, help="Directory that contains actor model folders.")
    episode_asset_coverage_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    episode_asset_coverage_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")
    episode_asset_coverage_parser.add_argument("--fail-on-missing", action="store_true", help="Exit 1 when any scene asset is missing.")

    episode_variant_parser = subparsers.add_parser(
        "episode-variant-requests",
        help="Build supplemental variant requests for episode scenes missing actor assets.",
    )
    episode_variant_parser.add_argument("roster_plan_path", help="Input actor roster plan JSON path.")
    episode_variant_parser.add_argument("episode_path", help="Input episode JSON with role_casting and scenes.")
    episode_variant_parser.add_argument("--actor-root", default=None, help="Directory that contains actor model folders.")
    episode_variant_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    episode_variant_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")

    episode_variant_coverage_parser = subparsers.add_parser(
        "episode-variant-coverage",
        help="Report missing local assets for supplemental episode variant requests.",
    )
    episode_variant_coverage_parser.add_argument("request_manifest_path", help="Input episode variant request manifest JSON path.")
    episode_variant_coverage_parser.add_argument("--actor-root", default=None, help="Directory that contains actor model folders.")
    episode_variant_coverage_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    episode_variant_coverage_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")
    episode_variant_coverage_parser.add_argument("--fail-on-missing", action="store_true", help="Exit 1 when any requested variant is missing.")

    episode_variant_promotions_parser = subparsers.add_parser(
        "episode-variant-promotions",
        help="Plan durable actor.json required_variants additions from ready episode coverage.",
    )
    episode_variant_promotions_parser.add_argument("coverage_report_path", help="Input episode variant coverage report JSON path.")
    episode_variant_promotions_parser.add_argument("--actor-root", default=None, help="Directory that contains actor model folders.")
    episode_variant_promotions_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    episode_variant_promotions_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")
    episode_variant_promotions_parser.add_argument("--fail-on-not-ready", action="store_true", help="Exit 1 when promotions are not ready.")

    apply_episode_variant_promotions_parser = subparsers.add_parser(
        "apply-episode-variant-promotions",
        help="Apply ready episode variant promotions to actor.json required_variants.",
    )
    apply_episode_variant_promotions_parser.add_argument("promotion_plan_path", help="Input episode variant promotion plan JSON path.")
    apply_episode_variant_promotions_parser.add_argument("--actor-root", default=None, help="Directory that contains actor model folders.")
    apply_episode_variant_promotions_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    apply_episode_variant_promotions_parser.add_argument("--output", default=None, help="Output apply report JSON path. Prints JSON when omitted.")

    request_parser = subparsers.add_parser("asset-requests", help="Build a JSON manifest of actor asset requests.")
    request_parser.add_argument("actor_model_path", help="Path to actor.json")
    request_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    request_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")

    layer_spec_parser = subparsers.add_parser(
        "layer-spec",
        help="Build a renderer-facing layer specification for one actor model.",
    )
    layer_spec_parser.add_argument("actor_model_path", help="Path to actor.json")
    layer_spec_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    layer_spec_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")

    reuse_parser = subparsers.add_parser(
        "reuse-template",
        help="Build a portable manifest for reusing one actor model across packs and episode roles.",
    )
    reuse_parser.add_argument("actor_model_path", help="Path to actor.json")
    reuse_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    reuse_parser.add_argument(
        "--context",
        action="append",
        default=None,
        help="Usage context to include, for example daily_life or mystery. Can be repeated.",
    )
    reuse_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")

    coverage_parser = subparsers.add_parser("coverage", help="Report missing local actor assets.")
    coverage_parser.add_argument("actor_model_path", help="Path to actor.json")
    coverage_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    coverage_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")
    coverage_parser.add_argument("--fail-on-missing", action="store_true", help="Exit 1 when any asset is missing.")

    pack_coverage_parser = subparsers.add_parser(
        "pack-coverage",
        help="Aggregate actor asset coverage for a pack settings.json file.",
    )
    pack_coverage_parser.add_argument("settings_path", help="Path to pack settings.json")
    pack_coverage_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    pack_coverage_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")
    pack_coverage_parser.add_argument("--fail-on-missing", action="store_true", help="Exit 1 when any asset is missing.")

    args = parser.parse_args(argv)
    if args.command == "scaffold":
        actor_path = scaffold_actor_model(
            args.actor_id,
            actor_root=args.actor_root,
            repo_root=args.repo_root,
            display_name=args.display_name,
            age_band=args.age_band,
            gender_presentation=args.gender_presentation,
            role_range=args.role_range,
            visual_identity=args.visual_identity,
            voice_profile=args.voice_profile,
            force=args.force,
        )
        print(f"Scaffolded actor model {args.actor_id}: {actor_path}")
        return 0
    if args.command == "scaffold-preset":
        actor_path = scaffold_actor_model_from_preset(
            args.preset_id,
            args.actor_id,
            actor_root=args.actor_root,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            force=args.force,
        )
        print(f"Scaffolded actor model {args.actor_id} from preset {args.preset_id}: {actor_path}")
        return 0
    if args.command == "scaffold-sample-assets":
        if args.output:
            output = write_actor_model_sample_assets_report(
                args.actor_model_path,
                args.output,
                repo_root=args.repo_root,
                force=args.force,
            )
            report = json.loads(Path(output).read_text(encoding="utf-8"))
            print(
                f"Wrote sample actor assets for {report['actor_id']}: {output} "
                f"(created {report['created_count']}/{report['asset_count']})"
            )
        else:
            report = scaffold_actor_model_sample_assets(
                args.actor_model_path,
                repo_root=args.repo_root,
                force=args.force,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print(
                f"sample actor assets for {report['actor_id']}: "
                f"created {report['created_count']}/{report['asset_count']}"
            )
        return 0
    if args.command == "roster-plan":
        assignments = [_parse_roster_assignment(raw_assignment) for raw_assignment in args.assignment]
        plan = build_pack_actor_roster_plan(
            args.pack_id,
            assignments,
            catalog_path=args.catalog,
            repo_root=args.repo_root,
            actor_root_relative=args.actor_root_relative,
        )
        if args.output:
            output = write_pack_actor_roster_plan(
                args.pack_id,
                assignments,
                args.output,
                catalog_path=args.catalog,
                repo_root=args.repo_root,
                actor_root_relative=args.actor_root_relative,
            )
            print(f"Wrote pack actor roster plan for {args.pack_id}: {output}")
        else:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if args.command == "apply-roster-plan":
        if args.output:
            output = write_applied_pack_actor_roster_plan(
                args.settings_path,
                args.roster_plan_path,
                args.output,
                force=args.force,
            )
            print(f"Wrote settings with actor roster plan applied: {output}")
        else:
            settings = _load_json_object(args.settings_path, "settings")
            roster_plan = _load_json_object(args.roster_plan_path, "actor roster plan")
            applied = apply_pack_actor_roster_plan(settings, roster_plan, force=args.force)
            print(json.dumps(applied, ensure_ascii=False, indent=2))
        return 0
    if args.command == "scaffold-roster":
        if args.output:
            output = write_actor_roster_scaffold_report(
                args.roster_plan_path,
                args.output,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
                catalog_path=args.catalog,
                force=args.force,
            )
            print(f"Wrote actor roster scaffold report: {output}")
        else:
            roster_plan = _load_json_object(args.roster_plan_path, "actor roster plan")
            report = scaffold_actor_models_from_roster_plan(
                roster_plan,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
                catalog_path=args.catalog,
                force=args.force,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.command == "roster-asset-requests":
        if args.output:
            output = write_actor_roster_asset_request_manifest(
                args.roster_plan_path,
                args.output,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            print(f"Wrote actor roster asset requests: {output}")
        else:
            roster_plan = _load_json_object(args.roster_plan_path, "actor roster plan")
            manifest = build_actor_roster_asset_request_manifest(
                roster_plan,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.command == "roster-layer-specs":
        if args.output:
            output = write_actor_roster_layer_spec_manifest(
                args.roster_plan_path,
                args.output,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            print(f"Wrote actor roster layer specs: {output}")
        else:
            roster_plan = _load_json_object(args.roster_plan_path, "actor roster plan")
            manifest = build_actor_roster_layer_spec_manifest(
                roster_plan,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.command == "episode-asset-plan":
        if args.output:
            output = write_actor_episode_asset_plan(
                args.roster_plan_path,
                args.episode_path,
                args.output,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            manifest = json.loads(Path(output).read_text(encoding="utf-8"))
            print(f"Wrote episode asset plan: {output}")
        else:
            roster_plan = _load_json_object(args.roster_plan_path, "actor roster plan")
            episode = _load_json_object(args.episode_path, "episode")
            manifest = build_actor_episode_asset_plan(
                roster_plan,
                episode,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        if args.fail_on_invalid and not manifest["is_valid"]:
            return 1
        return 0
    if args.command == "episode-asset-coverage":
        if args.output:
            output = write_actor_episode_asset_coverage_report(
                args.asset_plan_path,
                args.output,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            report = json.loads(Path(output).read_text(encoding="utf-8"))
            print(
                f"Wrote episode asset coverage: {output} "
                f"(missing {report['missing_count']}/{report['expected_count']})"
            )
        else:
            asset_plan = _load_json_object(args.asset_plan_path, "episode asset plan")
            report = build_actor_episode_asset_coverage_report(
                asset_plan,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print(f"episode scene assets missing {report['missing_count']}/{report['expected_count']}")
        if args.fail_on_missing and report["missing_count"]:
            return 1
        return 0
    if args.command == "episode-variant-requests":
        if args.output:
            output = write_actor_episode_variant_request_manifest(
                args.roster_plan_path,
                args.episode_path,
                args.output,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            print(f"Wrote episode variant requests: {output}")
        else:
            roster_plan = _load_json_object(args.roster_plan_path, "actor roster plan")
            episode = _load_json_object(args.episode_path, "episode")
            manifest = build_actor_episode_variant_request_manifest(
                roster_plan,
                episode,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.command == "episode-variant-coverage":
        if args.output:
            output = write_actor_episode_variant_coverage_report(
                args.request_manifest_path,
                args.output,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            report = json.loads(Path(output).read_text(encoding="utf-8"))
            print(
                f"Wrote episode variant coverage: {output} "
                f"(missing {report['missing_count']}/{report['expected_count']})"
            )
        else:
            request_manifest = _load_json_object(args.request_manifest_path, "episode variant request manifest")
            report = build_actor_episode_variant_coverage_report(
                request_manifest,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print(f"episode variants missing {report['missing_count']}/{report['expected_count']}")
        if args.fail_on_missing and report["missing_count"]:
            return 1
        return 0
    if args.command == "episode-variant-promotions":
        if args.output:
            output = write_actor_episode_variant_promotion_plan(
                args.coverage_report_path,
                args.output,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            promotion_plan = json.loads(Path(output).read_text(encoding="utf-8"))
            print(
                f"Wrote episode variant promotions: {output} "
                f"(promote {promotion_plan['promotion_count']})"
            )
        else:
            coverage_report = _load_json_object(args.coverage_report_path, "episode variant coverage report")
            promotion_plan = build_actor_episode_variant_promotion_plan(
                coverage_report,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            print(json.dumps(promotion_plan, ensure_ascii=False, indent=2))
            print(f"episode variant promotions: {promotion_plan['promotion_count']}")
        if args.fail_on_not_ready and not promotion_plan["ready_for_promotion"]:
            return 1
        return 0
    if args.command == "apply-episode-variant-promotions":
        if args.output:
            output = write_applied_actor_episode_variant_promotion_plan(
                args.promotion_plan_path,
                args.output,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            apply_report = json.loads(Path(output).read_text(encoding="utf-8"))
            print(
                f"Wrote applied episode variant promotions: {output} "
                f"(applied {apply_report['applied_count']})"
            )
        else:
            promotion_plan = _load_json_object(args.promotion_plan_path, "episode variant promotion plan")
            apply_report = apply_actor_episode_variant_promotion_plan(
                promotion_plan,
                actor_root=args.actor_root,
                repo_root=args.repo_root,
            )
            print(json.dumps(apply_report, ensure_ascii=False, indent=2))
            print(f"applied episode variant promotions: {apply_report['applied_count']}")
        return 0
    if args.command == "asset-requests":
        manifest = build_actor_asset_request_manifest(args.actor_model_path, repo_root=args.repo_root)
        if args.output:
            output = write_actor_asset_request_manifest(args.actor_model_path, args.output, repo_root=args.repo_root)
            print(f"Wrote actor asset requests for {manifest['actor_id']}: {output}")
        else:
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.command == "layer-spec":
        manifest = build_actor_layer_spec_manifest(args.actor_model_path, repo_root=args.repo_root)
        if args.output:
            output = write_actor_layer_spec_manifest(args.actor_model_path, args.output, repo_root=args.repo_root)
            print(f"Wrote actor layer spec for {manifest['actor_id']}: {output}")
        else:
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.command == "reuse-template":
        manifest = build_actor_reuse_template_manifest(
            args.actor_model_path,
            repo_root=args.repo_root,
            contexts=args.context,
        )
        if args.output:
            output = write_actor_reuse_template_manifest(
                args.actor_model_path,
                args.output,
                repo_root=args.repo_root,
                contexts=args.context,
            )
            print(f"Wrote actor reuse template for {manifest['actor_id']}: {output}")
        else:
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.command == "coverage":
        report = build_actor_asset_coverage_report(args.actor_model_path, repo_root=args.repo_root)
        if args.output:
            output = write_actor_asset_coverage_report(args.actor_model_path, args.output, repo_root=args.repo_root)
            print(
                f"Wrote actor asset coverage for {report['actor_id']}: {output} "
                f"(missing {report['missing_count']}/{report['expected_count']})"
            )
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print(f"actor {report['actor_id']} missing {report['missing_count']}/{report['expected_count']}")
        if args.fail_on_missing and report["missing_count"]:
            return 1
        return 0
    if args.command == "pack-coverage":
        report = build_pack_actor_asset_coverage_report(args.settings_path, repo_root=args.repo_root)
        if args.output:
            output = write_pack_actor_asset_coverage_report(args.settings_path, args.output, repo_root=args.repo_root)
            print(
                f"Wrote pack actor coverage for {report['pack_settings_path']}: {output} "
                f"(missing {report['missing_count']}/{report['expected_count']})"
            )
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print(
                f"pack {report['pack_settings_path']} missing "
                f"{report['missing_count']}/{report['expected_count']}"
            )
        if args.fail_on_missing and not report["ready_for_local_test"]:
            return 1
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
