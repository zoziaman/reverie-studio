from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional


RENDER_PLAN_SCHEMA = "reverie.pack.videotoon_render_plan.v1"
REMOTION_PROPS_SCHEMA = "reverie.remotion.radio_drama_props.v1"
PREPARE_SCHEMA = "reverie.pack.videotoon_episode_prepare.v1"
ACTOR_PLAN_SCHEMA = "reverie.pack.actor_episode_asset_plan.v1"
ACTOR_LAYER_SPECS_SCHEMA = "reverie.pack.actor_roster.layer_specs.v1"
BACKGROUND_COVERAGE_SCHEMA = "reverie.background_library.episode_asset_coverage.v1"
PREFLIGHT_SCHEMA = "reverie.pack.videotoon_episode_preflight.v1"


def _load_json_object(path: Path | str, label: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return data


def _require_schema(report: Mapping[str, Any], schema: str, label: str) -> None:
    if report.get("schema") != schema:
        raise ValueError(f"{label} schema must be {schema}")


def _artifact_path(prepare_path: Path, prepare_report: Mapping[str, Any], key: str) -> Path:
    artifacts = prepare_report.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ValueError("prepare report artifacts must be an object")
    filename = str(artifacts.get(key) or "").strip()
    if not filename:
        raise ValueError(f"prepare report artifacts.{key} is required")
    return prepare_path.parent / filename


def _index_by_key(items: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {
        str(item.get("key") or ""): dict(item)
        for item in items
        if isinstance(item, Mapping) and str(item.get("key") or "").strip()
    }


def _scene_backgrounds_by_id(background_coverage: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    backgrounds = background_coverage.get("scene_backgrounds")
    if not isinstance(backgrounds, list):
        return {}
    return {
        str(item.get("scene_id") or ""): dict(item)
        for item in backgrounds
        if isinstance(item, Mapping) and str(item.get("scene_id") or "").strip()
    }


def _background_layer(background: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "layer_type": "background_plate",
        "target_relative_path": str(background.get("target_relative_path") or ""),
        "location_id": str(background.get("location_id") or ""),
        "time": str(background.get("time") or ""),
        "exists": bool(background.get("exists")),
        "z_index": 0,
    }


def _actor_layer(
    layer: Mapping[str, Any],
    *,
    fallback_type: str,
    fallback_key: str,
    fallback_target: str,
) -> dict[str, Any]:
    return {
        "layer_type": str(layer.get("layer_type") or fallback_type),
        "key": str(layer.get("key") or fallback_key),
        "target_relative_path": str(layer.get("target_relative_path") or fallback_target),
        "anchor_key": str(layer.get("anchor_key") or ""),
        "z_index": int(layer.get("z_index") or 0),
        "public_safe": bool(layer.get("public_safe", True)),
    }


def _build_scene_composition(
    scene: Mapping[str, Any],
    *,
    actor_specs: Mapping[str, Any],
    background_by_scene_id: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    scene_id = str(scene.get("scene_id") or "")
    actor_id = str(scene.get("actor_id") or "")
    actor_spec = actor_specs.get(actor_id) if isinstance(actor_specs.get(actor_id), Mapping) else {}
    variant_layers = _index_by_key(actor_spec.get("variant_layers") if isinstance(actor_spec, Mapping) else [])
    eye_layers = _index_by_key(actor_spec.get("eye_layers") if isinstance(actor_spec, Mapping) else [])
    mouth_layers = _index_by_key(actor_spec.get("mouth_layers") if isinstance(actor_spec, Mapping) else [])

    variant_key = str(scene.get("variant_key") or "")
    eye_shape_key = str(scene.get("eye_shape_key") or "")
    mouth_shape_key = str(scene.get("mouth_shape_key") or "")
    background = background_by_scene_id.get(scene_id, {})

    composition_layers = [
        _background_layer(background),
        _actor_layer(
            variant_layers.get(variant_key, {}),
            fallback_type="variant_base",
            fallback_key=variant_key,
            fallback_target=str(scene.get("target_relative_path") or ""),
        ),
        _actor_layer(
            eye_layers.get(eye_shape_key, {}),
            fallback_type="eye_layer",
            fallback_key=eye_shape_key,
            fallback_target=str(scene.get("eye_target_relative_path") or ""),
        ),
        _actor_layer(
            mouth_layers.get(mouth_shape_key, {}),
            fallback_type="mouth_layer",
            fallback_key=mouth_shape_key,
            fallback_target=str(scene.get("mouth_target_relative_path") or ""),
        ),
    ]

    return {
        "scene_id": scene_id,
        "role_id": str(scene.get("role_id") or ""),
        "actor_id": actor_id,
        "shot_type": str(scene.get("shot_type") or ""),
        "background": {
            "target_relative_path": str(background.get("target_relative_path") or ""),
            "location_id": str(background.get("location_id") or ""),
            "time": str(background.get("time") or ""),
            "exists": bool(background.get("exists")),
        },
        "actor": {
            "variant_key": variant_key,
            "mouth_shape_key": mouth_shape_key,
            "eye_shape_key": eye_shape_key,
            "canvas": actor_spec.get("canvas", {}) if isinstance(actor_spec, Mapping) else {},
            "anchor_points": actor_spec.get("anchor_points", {}) if isinstance(actor_spec, Mapping) else {},
        },
        "composition_layers": composition_layers,
    }


def build_videotoon_render_plan_from_prepare_report(
    prepare_report_path: Path | str,
) -> dict[str, Any]:
    """Build a public-safe scene composition plan from a prepare report bundle."""
    prepare_path = Path(prepare_report_path)
    prepare_report = _load_json_object(prepare_path, "prepare report")
    _require_schema(prepare_report, PREPARE_SCHEMA, "prepare report")

    actor_plan_path = _artifact_path(prepare_path, prepare_report, "actor_asset_plan")
    actor_layer_specs_path = _artifact_path(prepare_path, prepare_report, "actor_layer_specs")
    background_coverage_path = _artifact_path(prepare_path, prepare_report, "background_coverage")
    preflight_path = _artifact_path(prepare_path, prepare_report, "preflight")

    actor_plan = _load_json_object(actor_plan_path, "actor asset plan")
    actor_layer_specs = _load_json_object(actor_layer_specs_path, "actor layer specs")
    background_coverage = _load_json_object(background_coverage_path, "background coverage")
    preflight = _load_json_object(preflight_path, "preflight")
    _require_schema(actor_plan, ACTOR_PLAN_SCHEMA, "actor asset plan")
    _require_schema(actor_layer_specs, ACTOR_LAYER_SPECS_SCHEMA, "actor layer specs")
    _require_schema(background_coverage, BACKGROUND_COVERAGE_SCHEMA, "background coverage")
    _require_schema(preflight, PREFLIGHT_SCHEMA, "preflight")

    scenes_input = actor_plan.get("scenes") if isinstance(actor_plan.get("scenes"), list) else []
    actor_specs = actor_layer_specs.get("actors") if isinstance(actor_layer_specs.get("actors"), Mapping) else {}
    background_by_scene_id = _scene_backgrounds_by_id(background_coverage)
    scenes = [
        _build_scene_composition(
            scene,
            actor_specs=actor_specs,
            background_by_scene_id=background_by_scene_id,
        )
        for scene in scenes_input
        if isinstance(scene, Mapping)
    ]

    return {
        "schema": RENDER_PLAN_SCHEMA,
        "pack_id": str(prepare_report.get("pack_id") or actor_plan.get("pack_id") or ""),
        "episode_id": str(prepare_report.get("episode_id") or actor_plan.get("episode_id") or ""),
        "ready_for_render": bool(preflight.get("ready_for_render")),
        "scene_count": len(scenes),
        "source_artifacts": dict(prepare_report.get("artifacts") or {}),
        "missing_assets": list(preflight.get("missing_assets") or []),
        "scenes": scenes,
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
    }


def write_videotoon_render_plan_from_prepare_report(
    prepare_report_path: Path | str,
    output_path: Path | str,
) -> Path:
    """Write a render plan manifest from a prepare report bundle."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    plan = build_videotoon_render_plan_from_prepare_report(prepare_report_path)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _layer_by_type(scene: Mapping[str, Any], layer_type: str) -> dict[str, Any]:
    layers = scene.get("composition_layers")
    if not isinstance(layers, list):
        return {}
    for layer in layers:
        if isinstance(layer, Mapping) and layer.get("layer_type") == layer_type:
            return dict(layer)
    return {}


def _remotion_image_from_scene(
    scene: Mapping[str, Any],
    *,
    scene_index: int,
    scene_duration_frames: int,
) -> dict[str, Any]:
    background_layer = _layer_by_type(scene, "background_plate")
    variant_layer = _layer_by_type(scene, "variant_base")
    eye_layer = _layer_by_type(scene, "eye_layer")
    mouth_layer = _layer_by_type(scene, "mouth_layer")
    background_path = str(background_layer.get("target_relative_path") or "")
    foreground_path = str(variant_layer.get("target_relative_path") or "")
    eye_path = str(eye_layer.get("target_relative_path") or "")
    mouth_path = str(mouth_layer.get("target_relative_path") or "")
    mouth_key = str(mouth_layer.get("key") or "")

    image = {
        "path": background_path or foreground_path,
        "backgroundPath": background_path,
        "foregroundPath": foreground_path,
        "startFrame": scene_index * scene_duration_frames,
        "durationFrames": scene_duration_frames,
        "motion": {
            "scene_type": "video_toon_layered_scene",
            "use_layered_cutout": True,
            "character_layer_mode": "layered_actor_pool_v1",
            "actor_id": str(scene.get("actor_id") or ""),
            "role_id": str(scene.get("role_id") or ""),
            "variant_key": str((scene.get("actor") or {}).get("variant_key") or ""),
            "background_id": str((scene.get("background") or {}).get("location_id") or ""),
        },
    }
    if eye_path:
        image["eyesOpenPath"] = eye_path
    if mouth_path and mouth_key == "mouth_closed":
        image["mouthClosedPath"] = mouth_path
    elif mouth_path:
        image["mouthOpenPath"] = mouth_path
    return image


def build_remotion_props_from_videotoon_render_plan(
    render_plan: Mapping[str, Any],
    *,
    fps: int = 30,
    scene_duration_frames: int = 90,
    width: int = 1920,
    height: int = 1080,
) -> dict[str, Any]:
    """Convert a video-toon render plan into Remotion RadioDrama props."""
    _require_schema(render_plan, RENDER_PLAN_SCHEMA, "render plan")
    if scene_duration_frames <= 0:
        raise ValueError("scene_duration_frames must be positive")
    if fps <= 0:
        raise ValueError("fps must be positive")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")

    scenes = render_plan.get("scenes") if isinstance(render_plan.get("scenes"), list) else []
    images = [
        _remotion_image_from_scene(scene, scene_index=index, scene_duration_frames=scene_duration_frames)
        for index, scene in enumerate(scenes)
        if isinstance(scene, Mapping)
    ]

    return {
        "schema": REMOTION_PROPS_SCHEMA,
        "images": images,
        "audioSegments": [],
        "subtitles": [],
        "motiontoon": {
            "enabled": True,
            "mode": "layered_actor_pool_v1",
            "sourceRenderPlanSchema": RENDER_PLAN_SCHEMA,
            "renderPlan": dict(render_plan),
        },
        "totalFrames": len(images) * scene_duration_frames,
        "fps": fps,
        "width": width,
        "height": height,
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
    }


def write_remotion_props_from_videotoon_render_plan(
    render_plan_path: Path | str,
    output_path: Path | str,
    *,
    fps: int = 30,
    scene_duration_frames: int = 90,
    width: int = 1920,
    height: int = 1080,
) -> Path:
    """Write Remotion RadioDrama props from a video-toon render plan."""
    render_plan = _load_json_object(render_plan_path, "render plan")
    props = build_remotion_props_from_videotoon_render_plan(
        render_plan,
        fps=fps,
        scene_duration_frames=scene_duration_frames,
        width=width,
        height=height,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(props, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build a public-safe video-toon scene render plan.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser(
        "from-prepare",
        help="Build a scene composition plan from a prepare report JSON.",
    )
    prepare_parser.add_argument("prepare_report_path", help="Input prepare_report.json path.")
    prepare_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")

    remotion_parser = subparsers.add_parser(
        "to-remotion-props",
        help="Convert a video-toon render plan into Remotion RadioDrama props.",
    )
    remotion_parser.add_argument("render_plan_path", help="Input render_plan.json path.")
    remotion_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")
    remotion_parser.add_argument("--fps", type=int, default=30, help="Frames per second.")
    remotion_parser.add_argument("--scene-duration-frames", type=int, default=90, help="Default duration per scene.")
    remotion_parser.add_argument("--width", type=int, default=1920, help="Composition width.")
    remotion_parser.add_argument("--height", type=int, default=1080, help="Composition height.")

    args = parser.parse_args(argv)
    if args.command == "from-prepare":
        plan = build_videotoon_render_plan_from_prepare_report(args.prepare_report_path)
        if args.output:
            output = write_videotoon_render_plan_from_prepare_report(args.prepare_report_path, args.output)
            print(f"Wrote video-toon render plan for {plan['episode_id']}: {output}")
        else:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if args.command == "to-remotion-props":
        render_plan = _load_json_object(args.render_plan_path, "render plan")
        props = build_remotion_props_from_videotoon_render_plan(
            render_plan,
            fps=args.fps,
            scene_duration_frames=args.scene_duration_frames,
            width=args.width,
            height=args.height,
        )
        if args.output:
            output = write_remotion_props_from_videotoon_render_plan(
                args.render_plan_path,
                args.output,
                fps=args.fps,
                scene_duration_frames=args.scene_duration_frames,
                width=args.width,
                height=args.height,
            )
            print(f"Wrote Remotion props for {props['motiontoon']['renderPlan']['episode_id']}: {output}")
        else:
            print(json.dumps(props, ensure_ascii=False, indent=2))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
