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
            name="image_backend",
            status="dry_run",
            duration_seconds=0.0,
            cost_usd=0.0,
            artifact="placeholder_frames.none",
            note=f"Selected {image_provider} profile path; skipped model assets and media generation.",
        ),
        DemoStage(
            name="tts_backend",
            status="dry_run",
            duration_seconds=0.0,
            cost_usd=0.0,
            artifact="placeholder_voice.none",
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
            artifact="render.command.preview",
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


def _write_report(
    path: Path,
    pack: dict,
    stages: list[DemoStage],
    output_dir: Path,
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
        f"Output directory: `{output_dir}`",
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
        artifact="youtube.private_upload.not_started",
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
        "pack_path": str(pack_path),
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
    _write_json(output_dir / "quality_gate.json", quality_gate)
    _write_json(output_dir / "run_manifest.json", manifest)
    _write_jsonl(output_dir / "stage_log.jsonl", (asdict(stage) for stage in stages))
    _write_report(
        output_dir / "pipeline_report.md",
        pack,
        stages,
        output_dir,
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
