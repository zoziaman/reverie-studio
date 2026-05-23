from __future__ import annotations

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
    re.compile(r"C:\\Users\\", re.IGNORECASE),
    re.compile(r"C:/Users/", re.IGNORECASE),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH |PRIVATE )?PRIVATE KEY-----"),
)


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
