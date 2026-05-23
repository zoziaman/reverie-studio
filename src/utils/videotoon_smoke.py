from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw

try:
    from modules_pro import background_library
    from utils import actor_model, videotoon_episode_prepare, videotoon_render_plan
except ModuleNotFoundError:
    from ..modules_pro import background_library
    from . import actor_model, videotoon_episode_prepare, videotoon_render_plan


SMOKE_SCHEMA = "reverie.local.videotoon_smoke_bundle.v1"
BACKGROUND_SAMPLE_SCHEMA = "reverie.local.background_sample_assets.v1"
DEFAULT_PACK_ID = "daily_life_toon"
DEFAULT_EPISODE_ID = "daily_life_toon_ep001"
DEFAULT_ACTOR_ID = "actor_adult_woman_01"


def _write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _copy_actor_template(source_repo_root: Path, output_dir: Path, actor_id: str) -> Path:
    source_actor_dir = source_repo_root / "assets" / "actor_models" / actor_id
    if not source_actor_dir.exists():
        raise ValueError(f"source actor template does not exist: {source_actor_dir}")

    target_actor_dir = output_dir / "actor_models" / actor_id
    if not target_actor_dir.exists():
        shutil.copytree(source_actor_dir, target_actor_dir)
    else:
        for source_file in source_actor_dir.rglob("*"):
            if not source_file.is_file():
                continue
            target_file = target_actor_dir / source_file.relative_to(source_actor_dir)
            if target_file.exists():
                continue
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
    return target_actor_dir / "actor.json"


def _build_roster_plan(actor_data: dict[str, Any], *, pack_id: str, actor_id: str) -> dict[str, Any]:
    voice_profile = actor_data.get("voice_profile") if isinstance(actor_data.get("voice_profile"), dict) else {}
    return {
        "schema": "reverie.pack.actor_roster_plan.v1",
        "pack_id": pack_id,
        "role_reuse_policy": {
            "stable_actor_identity": True,
            "episode_roles_may_change": True,
            "role_casting_is_episode_specific": True,
        },
        "motiontoon_patch": {
            "actor_pool": {
                actor_id: {
                    "character_id": actor_id,
                    "actor_model_path": f"actor_models/{actor_id}/actor.json",
                    "visual_identity": str(actor_data.get("identity_lock", {}).get("face_shape") or actor_id),
                    "voice_profile": str(voice_profile.get("recommended_slot") or "female_01"),
                    "required_variants": list(actor_data.get("required_variants") or []),
                    "preset_id": "gold_actor_template",
                    "age_band": str(actor_data.get("age_band") or ""),
                    "gender_presentation": str(actor_data.get("gender_presentation") or ""),
                    "genre_tags": ["daily_life", "omnibus", "video_toon"],
                }
            },
            "role_casting_contract": copy.deepcopy(actor_model.DEFAULT_ROLE_CASTING_CONTRACT),
            "cast_slots": {
                "protagonist": {
                    "actor_id": actor_id,
                    "character_id": actor_id,
                    "aliases": ["lead", "fixed_actor", actor_id],
                }
            },
        },
        "episode_cast_seed": {
            "episode_id": f"{pack_id}_episode_seed",
            "role_casting": {"protagonist": actor_id},
        },
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
    }


def _build_episode(*, episode_id: str, roster_plan: dict[str, Any], actor_id: str) -> dict[str, Any]:
    return {
        "episode_id": episode_id,
        "role_casting": roster_plan["episode_cast_seed"]["role_casting"],
        "scenes": [
            {
                "scene_id": "s001",
                "role_id": "protagonist",
                "actor_id": actor_id,
                "emotion": "happy",
                "pose": "standing",
                "shot_type": "medium",
                "line": "This smoke run proves the fixed actor can speak with layered mouth and eye parts.",
                "background_id": "street",
                "time": "day",
            }
        ],
    }


def _build_settings() -> dict[str, Any]:
    return {
        "background_library": {
            "profile": DEFAULT_PACK_ID,
            "style_prompt": "clean reusable Korean webtoon background, no people, no signs, no text",
            "negative_prompt": "people, character, face, readable text, logo, UI card, photorealistic",
            "location_templates": {
                "street": {
                    "id": "street",
                    "name_ko": "street",
                    "name_en": "street",
                    "base_prompt": "quiet Korean neighborhood street, no people, open center space",
                    "keywords": ["street", "neighborhood street"],
                }
            },
        }
    }


def _draw_background_placeholder(path: Path, *, width: int, height: int) -> None:
    image = Image.new("RGBA", (width, height), (222, 232, 236, 255))
    draw = ImageDraw.Draw(image)
    sky_bottom = int(height * 0.48)
    road_top = int(height * 0.66)
    draw.rectangle((0, 0, width, sky_bottom), fill=(202, 224, 238, 255))
    draw.rectangle((0, sky_bottom, width, road_top), fill=(206, 214, 205, 255))
    draw.rectangle((0, road_top, width, height), fill=(88, 94, 98, 255))
    draw.polygon(
        [(0, height), (int(width * 0.43), road_top), (int(width * 0.57), road_top), (width, height)],
        fill=(112, 118, 122, 255),
    )
    for index, x in enumerate(range(70, width, 190)):
        building_top = int(height * (0.22 + (index % 3) * 0.06))
        building_width = 120 + (index % 2) * 45
        draw.rectangle(
            (x, building_top, x + building_width, road_top),
            fill=(176, 180, 176, 255),
            outline=(92, 98, 98, 255),
            width=3,
        )
        for window_y in range(building_top + 28, road_top - 26, 44):
            for window_x in range(x + 18, x + building_width - 28, 38):
                draw.rectangle((window_x, window_y, window_x + 18, window_y + 18), fill=(244, 226, 152, 255))
    draw.line((0, road_top, width, road_top), fill=(56, 62, 66, 255), width=5)
    draw.line((0, int(height * 0.82), width, int(height * 0.82)), fill=(238, 225, 152, 255), width=6)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_background_sample_assets(
    settings_path: Path,
    episode_path: Path,
    output_dir: Path,
    *,
    pack_id: str,
    background_root: Path,
) -> dict[str, Any]:
    request_manifest = background_library.build_background_episode_asset_request_manifest(
        settings_path,
        episode_path,
        pack_id=pack_id,
        repo_root=str(output_dir),
        background_root=str(background_root),
        images_per_location=1,
    )
    assets: list[dict[str, Any]] = []
    created_count = 0
    skipped_count = 0
    for request in request_manifest.get("requests", []):
        if not isinstance(request, dict):
            continue
        relative_path = str(request.get("target_relative_path") or "")
        target = background_root / pack_id / relative_path
        width = int(request.get("width") or 1024)
        height = int(request.get("height") or 576)
        created = not target.exists()
        if created:
            _draw_background_placeholder(target, width=width, height=height)
            created_count += 1
        else:
            skipped_count += 1
        assets.append(
            {
                "request_id": str(request.get("request_id") or ""),
                "target_relative_path": relative_path,
                "width": width,
                "height": height,
                "created": created,
                "local_only": True,
                "public_safe_placeholder": True,
            }
        )

    return {
        "schema": BACKGROUND_SAMPLE_SCHEMA,
        "pack_id": pack_id,
        "creates_media": True,
        "asset_count": len(assets),
        "created_count": created_count,
        "skipped_count": skipped_count,
        "public_release_boundary": {
            "contains_real_background_media": False,
            "contains_placeholder_media": True,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
        "assets": assets,
    }


def write_local_videotoon_smoke_bundle(
    output_dir: Path | str,
    *,
    source_repo_root: Optional[Path | str] = None,
    pack_id: str = DEFAULT_PACK_ID,
    episode_id: str = DEFAULT_EPISODE_ID,
    actor_id: str = DEFAULT_ACTOR_ID,
    fps: int = 30,
    duration_seconds: int = 10,
    width: int = 1080,
    height: int = 1920,
) -> dict[str, Any]:
    """Write a local-only video-toon smoke bundle with placeholder media."""
    smoke_root = Path(output_dir).resolve()
    source_root = Path(source_repo_root).resolve() if source_repo_root is not None else Path.cwd().resolve()
    smoke_root.mkdir(parents=True, exist_ok=True)

    input_dir = smoke_root / "inputs"
    prepare_dir = smoke_root / "prepare"
    actor_root = smoke_root / "actor_models"
    background_root = smoke_root / "backgrounds"
    input_dir.mkdir(parents=True, exist_ok=True)
    prepare_dir.mkdir(parents=True, exist_ok=True)

    actor_path = _copy_actor_template(source_root, smoke_root, actor_id)
    actor_data = _load_json(actor_path)
    roster_plan = _build_roster_plan(actor_data, pack_id=pack_id, actor_id=actor_id)
    episode = _build_episode(episode_id=episode_id, roster_plan=roster_plan, actor_id=actor_id)
    settings = _build_settings()

    roster_path = _write_json(input_dir / f"{pack_id}.actor_roster_plan.json", roster_plan)
    episode_path = _write_json(input_dir / f"{episode_id}.json", episode)
    settings_path = _write_json(input_dir / "settings.json", settings)

    actor_sample_report_path = prepare_dir / f"{actor_id}.sample_assets.json"
    actor_model.write_actor_model_sample_assets_report(
        actor_path,
        actor_sample_report_path,
        repo_root=smoke_root,
        force=True,
    )
    actor_sample_report = _load_json(actor_sample_report_path)

    background_sample_report = _write_background_sample_assets(
        settings_path,
        episode_path,
        smoke_root,
        pack_id=pack_id,
        background_root=background_root,
    )
    background_sample_report_path = _write_json(
        prepare_dir / f"{episode_id}.background_sample_assets.json",
        background_sample_report,
    )

    prepare_report = videotoon_episode_prepare.write_videotoon_episode_prepare_bundle(
        roster_path,
        episode_path,
        settings_path,
        prepare_dir,
        actor_root=actor_root,
        repo_root=smoke_root,
        background_root=background_root,
    )
    prepare_report_path = prepare_dir / f"{episode_id}.prepare_report.json"
    render_plan_path = prepare_dir / f"{episode_id}.render_plan.json"
    remotion_props_path = prepare_dir / f"{episode_id}.remotion_props.json"
    asset_work_order_path = prepare_dir / f"{episode_id}.asset_work_order.json"
    scene_duration_frames = int(fps) * int(duration_seconds)

    videotoon_render_plan.write_videotoon_render_plan_from_prepare_report(
        prepare_report_path,
        render_plan_path,
    )
    videotoon_render_plan.write_remotion_props_from_videotoon_render_plan(
        render_plan_path,
        remotion_props_path,
        fps=int(fps),
        scene_duration_frames=scene_duration_frames,
        width=int(width),
        height=int(height),
    )
    videotoon_render_plan.write_videotoon_asset_work_order_from_render_plan(
        render_plan_path,
        asset_work_order_path,
    )
    render_plan = _load_json(render_plan_path)

    manifest = {
        "schema": SMOKE_SCHEMA,
        "pack_id": pack_id,
        "episode_id": episode_id,
        "actor_id": actor_id,
        "ready_for_render": bool(prepare_report.get("ready_for_render")) and bool(render_plan.get("ready_for_render")),
        "creates_media": True,
        "calls_external_services": False,
        "starts_upload": False,
        "fps": int(fps),
        "duration_seconds": int(duration_seconds),
        "total_frames": scene_duration_frames,
        "actor_sample_assets": {
            "schema": actor_sample_report["schema"],
            "asset_count": actor_sample_report["asset_count"],
            "created_count": actor_sample_report["created_count"],
            "coverage_after": actor_sample_report["coverage_after"],
        },
        "background_sample_assets": {
            "schema": background_sample_report["schema"],
            "asset_count": background_sample_report["asset_count"],
            "created_count": background_sample_report["created_count"],
        },
        "artifacts": {
            "roster_plan": _relative_to_root(roster_path, smoke_root),
            "episode": _relative_to_root(episode_path, smoke_root),
            "settings": _relative_to_root(settings_path, smoke_root),
            "actor_sample_assets": _relative_to_root(actor_sample_report_path, smoke_root),
            "background_sample_assets": _relative_to_root(background_sample_report_path, smoke_root),
            "prepare_report": _relative_to_root(prepare_report_path, smoke_root),
            "render_plan": _relative_to_root(render_plan_path, smoke_root),
            "asset_work_order": _relative_to_root(asset_work_order_path, smoke_root),
            "remotion_props": _relative_to_root(remotion_props_path, smoke_root),
        },
        "public_release_boundary": {
            "contains_real_actor_media": False,
            "contains_real_background_media": False,
            "contains_placeholder_media": True,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
    }
    _write_json(smoke_root / "smoke_manifest.json", manifest)
    return manifest


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Create local video-toon smoke bundles.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    local_parser = subparsers.add_parser(
        "local",
        help="Write a local-only video-toon smoke bundle with placeholder actor and background PNGs.",
    )
    local_parser.add_argument("--output-dir", required=True, help="Directory where the smoke bundle should be written.")
    local_parser.add_argument("--source-repo-root", default=None, help="Source checkout that contains public actor templates.")
    local_parser.add_argument("--fps", type=int, default=30, help="Frames per second for Remotion props.")
    local_parser.add_argument("--duration-seconds", type=int, default=10, help="Single-scene smoke duration in seconds.")
    local_parser.add_argument("--width", type=int, default=1080, help="Remotion composition width.")
    local_parser.add_argument("--height", type=int, default=1920, help="Remotion composition height.")

    args = parser.parse_args(argv)
    if args.command == "local":
        manifest = write_local_videotoon_smoke_bundle(
            args.output_dir,
            source_repo_root=args.source_repo_root,
            fps=args.fps,
            duration_seconds=args.duration_seconds,
            width=args.width,
            height=args.height,
        )
        print(
            f"Wrote video-toon smoke bundle for {manifest['episode_id']}: "
            f"{Path(args.output_dir) / 'smoke_manifest.json'}"
        )
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
