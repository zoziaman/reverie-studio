from __future__ import annotations

import argparse
import copy
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


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


def _validate_package_files(actor_dir: Path, result: ActorModelValidationResult) -> None:
    for relative_path in REQUIRED_PROMPT_FILES:
        if not (actor_dir / relative_path).exists():
            result.add_error(f"{relative_path} is required")

    forbidden_files = [
        str(path.relative_to(actor_dir))
        for path in actor_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_PUBLIC_SUFFIXES
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

    result.required_variants = _string_list(data.get("required_variants"))
    result.mouth_shapes = _string_list(data.get("mouth_shapes"))
    result.eye_shapes = _string_list(data.get("eye_shapes"))
    if not result.required_variants:
        result.add_error("required_variants must be a non-empty string list")
    if not result.mouth_shapes:
        result.add_error("mouth_shapes must be a non-empty string list")
    if not result.eye_shapes:
        result.add_error("eye_shapes must be a non-empty string list")

    _validate_public_boundary(data, result)
    _validate_package_files(actor_dir, result)
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


def build_actor_asset_request_manifest(
    actor_model_path: Path | str,
    *,
    repo_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Build a public-safe request manifest for local actor asset generation."""
    validation = validate_actor_model_package(actor_model_path, repo_root=repo_root)
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
        target_path = actor_dir / relative_path
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

    request_parser = subparsers.add_parser("asset-requests", help="Build a JSON manifest of actor asset requests.")
    request_parser.add_argument("actor_model_path", help="Path to actor.json")
    request_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation")
    request_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")

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
    if args.command == "asset-requests":
        manifest = build_actor_asset_request_manifest(args.actor_model_path, repo_root=args.repo_root)
        if args.output:
            output = write_actor_asset_request_manifest(args.actor_model_path, args.output, repo_root=args.repo_root)
            print(f"Wrote actor asset requests for {manifest['actor_id']}: {output}")
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
