from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser(description="Validate actor models and write local asset request manifests.")
    subparsers = parser.add_subparsers(dest="command", required=True)

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
