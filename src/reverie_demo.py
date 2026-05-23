"""Public dry-run demo for the Reverie Studio snapshot.

This module is intentionally stdlib-only. It does not call local AI services,
does not read credentials, and does not create video/audio/image media. The
goal is to show the production workflow shape in a way that is safe for a fresh
public clone and easy for CI to verify.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from reverie_backends import get_backend_profile, list_backend_profiles
from reverie_doctor import build_environment_report, write_environment_report
from reverie_quality import evaluate_quality_gate


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK_PATH = REPO_ROOT / "examples" / "public_demo_pack.json"


def _repo_relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return "<path_outside_repo>"


@dataclass(frozen=True)
class DemoStage:
    name: str
    status: str
    duration_seconds: float
    cost_usd: float
    artifact: str
    note: str


def _load_pack(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    required = {"pack_id", "name", "story_beats", "expected_gates"}
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError(f"demo pack is missing required fields: {', '.join(missing)}")
    if not isinstance(payload["story_beats"], list) or not payload["story_beats"]:
        raise ValueError("demo pack must include at least one story beat")
    return payload


def _build_stages(pack: dict, backend_profile: dict, environment_report: dict) -> list[DemoStage]:
    beat_count = len(pack["story_beats"])
    image_provider = backend_profile["image"]["provider"]
    tts_provider = backend_profile["tts"]["provider"]
    env_status = environment_report["overall_status"]
    return [
        DemoStage(
            name="pack_load",
            status="pass",
            duration_seconds=0.01,
            cost_usd=0.0,
            artifact="pack.public_demo.json",
            note=f"Loaded public pack with {beat_count} story beats.",
        ),
        DemoStage(
            name="environment_doctor",
            status="pass" if env_status == "pass" else "needs_setup",
            duration_seconds=0.01,
            cost_usd=0.0,
            artifact="environment_report.json",
            note="Checked local prerequisites without reading credentials or contacting cloud services.",
        ),
        DemoStage(
            name="story_plan",
            status="pass",
            duration_seconds=0.03,
            cost_usd=0.0,
            artifact="storyboard.plan.json",
            note="Converted beats into a deterministic placeholder scene plan.",
        ),
        DemoStage(
            name="videotoon_actor_template",
            status="pass",
            duration_seconds=0.02,
            cost_usd=0.0,
            artifact="video_toon_actor_template.remotion_props.json",
            note="Wrote a fixed-actor, mouth/eye layer Remotion props dry-run without media files.",
        ),
        DemoStage(
            name="image_backend",
            status="dry_run",
            duration_seconds=0.0,
            cost_usd=0.0,
            artifact="placeholder_frames.manifest.json",
            note=f"Selected {image_provider} profile path; skipped model assets and media generation.",
        ),
        DemoStage(
            name="tts_backend",
            status="dry_run",
            duration_seconds=0.0,
            cost_usd=0.0,
            artifact="placeholder_voice.manifest.json",
            note=f"Selected {tts_provider} profile path; skipped voice data and generated audio.",
        ),
        DemoStage(
            name="caption_plan",
            status="pass",
            duration_seconds=0.02,
            cost_usd=0.0,
            artifact="captions.preview.json",
            note="Prepared caption timing placeholders for review.",
        ),
        DemoStage(
            name="render_plan",
            status="dry_run",
            duration_seconds=0.0,
            cost_usd=0.0,
            artifact="render.command.preview.json",
            note="Skipped Remotion render and media output.",
        ),
        DemoStage(
            name="metadata_gate",
            status="pass",
            duration_seconds=0.01,
            cost_usd=0.0,
            artifact="metadata.review.json",
            note="Prepared title, disclosure, and manual review placeholders.",
        ),
    ]


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _layer(
    actor_id: str,
    layer_type: str,
    key: str,
    target_relative_path: str,
    anchor_key: str,
    z_index: int,
) -> dict:
    return {
        "layer_id": f"{actor_id}__{layer_type}__{key}",
        "layer_type": layer_type,
        "key": key,
        "target_relative_path": target_relative_path,
        "anchor_key": anchor_key,
        "z_index": z_index,
        "public_safe": True,
    }


def _build_videotoon_actor_template_render_plan(pack: dict) -> dict:
    actor_id = "demo_fixed_actor_01"
    background_path = "backgrounds/demo_neighborhood_day.png"
    variant_layers = {
        "talking_standing": _layer(
            actor_id,
            "variant_base",
            "talking_standing",
            "actor_models/demo_fixed_actor_01/variants/talking_standing.png",
            "actor_root",
            1,
        )
    }
    mouth_layers = {
        "mouth_closed": _layer(
            actor_id,
            "mouth_layer",
            "mouth_closed",
            "actor_models/demo_fixed_actor_01/face_parts/mouth_closed.png",
            "mouth_center",
            3,
        ),
        "mouth_small_open": _layer(
            actor_id,
            "mouth_layer",
            "mouth_small_open",
            "actor_models/demo_fixed_actor_01/face_parts/mouth_small_open.png",
            "mouth_center",
            3,
        ),
    }
    eye_layers = {
        "eyes_open": _layer(
            actor_id,
            "eye_layer",
            "eyes_open",
            "actor_models/demo_fixed_actor_01/face_parts/eyes_open.png",
            "eye_center",
            2,
        ),
        "eyes_closed": _layer(
            actor_id,
            "eye_layer",
            "eyes_closed",
            "actor_models/demo_fixed_actor_01/face_parts/eyes_closed.png",
            "eye_center",
            2,
        ),
    }
    return {
        "schema": "reverie.pack.videotoon_render_plan.v1",
        "pack_id": pack["pack_id"],
        "episode_id": "public_demo_videotoon_actor_template",
        "ready_for_render": False,
        "scene_count": 1,
        "source_artifacts": {
            "actor_model": "demo_fixed_actor_01.public_template",
            "background": "demo_neighborhood_day.public_template",
        },
        "missing_assets": [
            "demo_fixed_actor_01:variant:talking_standing",
            "demo_fixed_actor_01:mouth_shape:mouth_closed",
            "demo_fixed_actor_01:mouth_shape:mouth_small_open",
            "demo_fixed_actor_01:eye_shape:eyes_open",
            "demo_fixed_actor_01:eye_shape:eyes_closed",
            "background:demo_neighborhood_day",
        ],
        "scenes": [
            {
                "scene_id": "demo_s001",
                "role_id": "protagonist",
                "actor_id": actor_id,
                "shot_type": "medium_close",
                "background": {
                    "target_relative_path": background_path,
                    "location_id": "demo_neighborhood",
                    "time": "day",
                    "exists": False,
                },
                "actor": {
                    "variant_key": "talking_standing",
                    "mouth_shape_key": "mouth_small_open",
                    "eye_shape_key": "eyes_open",
                    "canvas": {"width": 1024, "height": 1536},
                    "anchor_points": {
                        "actor_root": {"x": 0.5, "y": 0.92},
                        "eye_center": {"x": 0.5, "y": 0.25},
                        "mouth_center": {"x": 0.5, "y": 0.38},
                    },
                    "available_variant_layers": variant_layers,
                    "available_mouth_layers": mouth_layers,
                    "available_eye_layers": eye_layers,
                },
                "composition_layers": [
                    {
                        "layer_type": "background_plate",
                        "target_relative_path": background_path,
                        "location_id": "demo_neighborhood",
                        "time": "day",
                        "exists": False,
                        "z_index": 0,
                    },
                    variant_layers["talking_standing"],
                    eye_layers["eyes_open"],
                    mouth_layers["mouth_small_open"],
                ],
            }
        ],
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
    }


def _write_videotoon_actor_template_demo(output_dir: Path, pack: dict) -> dict:
    from utils.videotoon_render_plan import (
        build_remotion_props_from_videotoon_render_plan,
        build_videotoon_asset_work_order_from_render_plan,
    )

    render_plan = _build_videotoon_actor_template_render_plan(pack)
    work_order = build_videotoon_asset_work_order_from_render_plan(
        render_plan,
        schema="reverie.public_demo.videotoon_actor_asset_work_order.v1",
    )
    props = build_remotion_props_from_videotoon_render_plan(
        render_plan,
        fps=30,
        scene_duration_frames=90,
        width=1080,
        height=1920,
    )
    _write_json(output_dir / "video_toon_actor_template.render_plan.json", render_plan)
    _write_json(output_dir / "video_toon_actor_template.asset_work_order.json", work_order)
    _write_json(output_dir / "video_toon_actor_template.remotion_props.json", props)
    return props


def _build_storyboard_plan(pack: dict) -> dict:
    target_seconds = int(pack.get("target_runtime_seconds") or 10)
    beats = pack["story_beats"]
    duration_frames = max(30, int((target_seconds * 30) / max(1, len(beats))))
    scenes = []
    for index, beat in enumerate(beats):
        scenes.append(
            {
                "scene_id": f"public_demo_s{index + 1:03d}",
                "role": str(beat.get("role") or "narrator"),
                "text": str(beat.get("text") or ""),
                "startFrame": index * duration_frames,
                "durationFrames": duration_frames,
                "visual_placeholder": f"placeholder_frame_{index + 1:03d}",
                "voice_placeholder": f"placeholder_voice_{index + 1:03d}",
            }
        )
    return {
        "schema": "reverie.public_demo.storyboard_plan.v1",
        "pack_id": pack["pack_id"],
        "target_runtime_seconds": target_seconds,
        "fps": 30,
        "scene_count": len(scenes),
        "scenes": scenes,
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
    }


def _build_placeholder_frames_manifest(storyboard: dict, backend_profile: dict) -> dict:
    return {
        "schema": "reverie.public_demo.placeholder_frames.v1",
        "provider": backend_profile["image"]["provider"],
        "creates_media": False,
        "frame_count": storyboard["scene_count"],
        "frames": [
            {
                "scene_id": scene["scene_id"],
                "placeholder_id": scene["visual_placeholder"],
                "status": "not_generated",
                "target_path": "",
            }
            for scene in storyboard["scenes"]
        ],
    }


def _build_placeholder_voice_manifest(storyboard: dict, backend_profile: dict) -> dict:
    return {
        "schema": "reverie.public_demo.placeholder_voice.v1",
        "provider": backend_profile["tts"]["provider"],
        "creates_audio": False,
        "voice_count": storyboard["scene_count"],
        "voice_slots": [
            {
                "scene_id": scene["scene_id"],
                "role": scene["role"],
                "placeholder_id": scene["voice_placeholder"],
                "status": "not_generated",
                "target_path": "",
            }
            for scene in storyboard["scenes"]
        ],
    }


def _build_caption_preview(storyboard: dict) -> dict:
    captions = [
        {
            "scene_id": scene["scene_id"],
            "speaker": scene["role"],
            "text": scene["text"],
            "startFrame": scene["startFrame"],
            "durationFrames": scene["durationFrames"],
        }
        for scene in storyboard["scenes"]
    ]
    return {
        "schema": "reverie.public_demo.captions_preview.v1",
        "caption_count": len(captions),
        "captions": captions,
    }


def _build_render_command_preview() -> dict:
    return {
        "schema": "reverie.public_demo.render_command_preview.v1",
        "renderer": "remotion",
        "executes_command": False,
        "would_use_props": "video_toon_actor_template.remotion_props.json",
        "command_preview": [
            "npx",
            "remotion",
            "render",
            "RadioDrama",
            "--props=video_toon_actor_template.remotion_props.json",
        ],
        "creates_media": False,
    }


def _build_metadata_review(pack: dict) -> dict:
    return {
        "schema": "reverie.public_demo.metadata_review.v1",
        "title": f"{pack['name']} dry run",
        "description": "Public no-credential dry-run. No generated media or upload is produced.",
        "synthetic_media_disclosure_required": True,
        "requires_human_review": True,
        "upload_allowed": False,
        "checks": [
            {"id": "no_credentials", "status": "pass"},
            {"id": "no_generated_media", "status": "pass"},
            {"id": "manual_upload_review", "status": "blocked_for_review"},
        ],
    }


def _build_upload_gate() -> dict:
    return {
        "schema": "reverie.public_demo.upload_gate.v1",
        "starts_upload": False,
        "upload_allowed": False,
        "requires_human_review": True,
        "reason": "Credentials, platform account, and private/test upload mode must be configured by the user.",
    }


def _write_named_stage_artifacts(output_dir: Path, pack: dict, backend_profile: dict) -> None:
    storyboard = _build_storyboard_plan(pack)
    _write_json(output_dir / "pack.public_demo.json", pack)
    _write_json(output_dir / "storyboard.plan.json", storyboard)
    _write_json(
        output_dir / "placeholder_frames.manifest.json",
        _build_placeholder_frames_manifest(storyboard, backend_profile),
    )
    _write_json(
        output_dir / "placeholder_voice.manifest.json",
        _build_placeholder_voice_manifest(storyboard, backend_profile),
    )
    _write_json(output_dir / "captions.preview.json", _build_caption_preview(storyboard))
    _write_json(output_dir / "render.command.preview.json", _build_render_command_preview())
    _write_json(output_dir / "metadata.review.json", _build_metadata_review(pack))
    _write_json(output_dir / "youtube.private_upload.not_started.json", _build_upload_gate())


def _write_report(
    path: Path,
    pack: dict,
    stages: list[DemoStage],
    backend_profile: dict,
    quality_gate: dict,
    environment_report: dict,
) -> None:
    passed = sum(1 for stage in stages if stage.status == "pass")
    dry = sum(1 for stage in stages if stage.status == "dry_run")
    blocked = sum(1 for stage in stages if stage.status == "blocked_for_review")
    lines = [
        "# Reverie Studio Public Dry Run",
        "",
        f"Pack: `{pack['pack_id']}`",
        f"Backend profile: `{backend_profile['id']}`",
        "Output directory: `<public_demo_output>`",
        "",
        "This is a no-credential demo. It creates only JSON, JSONL, and Markdown",
        "reports. It does not create video, audio, image, subtitle, credential,",
        "token, log, or model files inside the repository.",
        "",
        "## Stage Summary",
        "",
        "| Stage | Status | Cost | Artifact |",
        "| --- | --- | ---: | --- |",
    ]
    for stage in stages:
        lines.append(
            f"| {stage.name} | {stage.status} | ${stage.cost_usd:.2f} | `{stage.artifact}` |"
        )
    lines.extend(
        [
            "",
            "## Environment Doctor",
            "",
            f"- Status: {environment_report['overall_status']}",
            "- Credentials read: false",
            "- External services called: false",
            "",
            "## Quality Gate",
            "",
            f"- Status: {quality_gate['status']}",
            f"- Score: {quality_gate['score']:.2f}",
            f"- Threshold: {quality_gate['threshold']:.2f}",
            "- Human upload review required: true",
            "",
            "## Result",
            "",
            f"- Passed stages: {passed}",
            f"- Dry-run stages: {dry}",
            f"- Review-blocked stages: {blocked}",
            "- Final status: NEEDS HUMAN REVIEW BEFORE ANY REAL UPLOAD",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run_demo(
    pack_path: Path = DEFAULT_PACK_PATH,
    output_dir: Path | None = None,
    backend_profile_id: str = "local_dry_run",
    quality_threshold: float = 0.75,
) -> dict:
    pack_path = pack_path.resolve()
    pack = _load_pack(pack_path)
    if output_dir is None:
        output_dir = Path(tempfile.gettempdir()) / "reverie-public-demo"
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    backend_profile = get_backend_profile(backend_profile_id)
    environment_report = build_environment_report(REPO_ROOT)
    stages = _build_stages(pack, backend_profile, environment_report)
    upload_stage = DemoStage(
        name="upload_gate",
        status="blocked_for_review",
        duration_seconds=0.0,
        cost_usd=0.0,
        artifact="youtube.private_upload.not_started.json",
        note="Upload remains blocked until a human configures credentials and approves private/test mode.",
    )
    quality_input = [asdict(stage) for stage in stages] + [asdict(upload_stage)]
    quality_gate = evaluate_quality_gate(pack, quality_input, backend_profile, quality_threshold)
    stages.extend(
        [
            DemoStage(
                name="quality_gate",
                status=quality_gate["status"],
                duration_seconds=0.01,
                cost_usd=0.0,
                artifact="quality_gate.json",
                note=f"Quality score {quality_gate['score']:.2f} with threshold {quality_gate['threshold']:.2f}.",
            ),
            upload_stage,
        ]
    )
    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        "run_id": "public-demo-dry-run",
        "created_at": now,
        "pack_path": _repo_relative_path(pack_path),
        "pack_id": pack["pack_id"],
        "mode": "dry_run",
        "backend_profile": backend_profile,
        "environment_report": environment_report,
        "quality_gate": quality_gate,
        "final_status": "needs_human_review",
        "stage_count": len(stages),
        "total_cost_usd": round(sum(stage.cost_usd for stage in stages), 4),
        "total_duration_seconds": round(sum(stage.duration_seconds for stage in stages), 4),
        "safety": {
            "uses_credentials": False,
            "calls_external_services": False,
            "creates_media": False,
            "starts_upload": False,
        },
        "stages": [asdict(stage) for stage in stages],
    }

    _write_json(output_dir / "backend_profile.json", backend_profile)
    write_environment_report(output_dir / "environment_report.json", environment_report)
    _write_named_stage_artifacts(output_dir, pack, backend_profile)
    _write_videotoon_actor_template_demo(output_dir, pack)
    _write_json(output_dir / "quality_gate.json", quality_gate)
    _write_json(output_dir / "run_manifest.json", manifest)
    _write_jsonl(output_dir / "stage_log.jsonl", (asdict(stage) for stage in stages))
    _write_report(
        output_dir / "pipeline_report.md",
        pack,
        stages,
        backend_profile,
        quality_gate,
        environment_report,
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the safe Reverie Studio public dry-run demo.")
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK_PATH, help="Path to a public demo pack JSON file.")
    parser.add_argument(
        "--backend-profile",
        default="local_dry_run",
        choices=[profile["id"] for profile in list_backend_profiles()],
        help="Backend profile to describe in the dry-run manifest.",
    )
    parser.add_argument(
        "--quality-threshold",
        type=float,
        default=0.75,
        help="Public dry-run quality gate threshold.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(os.environ.get("REVERIE_DEMO_OUT", tempfile.gettempdir())) / "reverie-public-demo",
        help="Output directory for dry-run reports. Defaults outside the repository.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full manifest JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = run_demo(args.pack, args.out, args.backend_profile, args.quality_threshold)
    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        print(f"Reverie public dry run wrote reports to: {args.out.resolve()}")
        print(f"Final status: {manifest['final_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
