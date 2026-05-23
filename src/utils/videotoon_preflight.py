from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional


ACTOR_COVERAGE_SCHEMA = "reverie.pack.actor_episode.asset_coverage.v1"
BACKGROUND_COVERAGE_SCHEMA = "reverie.background_library.asset_coverage.v1"
BACKGROUND_EPISODE_COVERAGE_SCHEMA = "reverie.background_library.episode_asset_coverage.v1"
PREFLIGHT_SCHEMA = "reverie.pack.videotoon_episode_preflight.v1"


def _load_json_object(path: Path | str, label: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return data


def _validate_report_schema(report: Mapping[str, Any], expected_schema: str, label: str) -> None:
    if not isinstance(report, Mapping):
        raise ValueError(f"{label} must be an object")
    if report.get("schema") != expected_schema:
        raise ValueError(f"{label} schema must be {expected_schema}")


def _validate_background_report_schema(report: Mapping[str, Any]) -> None:
    if not isinstance(report, Mapping):
        raise ValueError("background coverage report must be an object")
    if report.get("schema") not in {BACKGROUND_COVERAGE_SCHEMA, BACKGROUND_EPISODE_COVERAGE_SCHEMA}:
        raise ValueError(
            "background coverage report schema must be "
            f"{BACKGROUND_COVERAGE_SCHEMA} or {BACKGROUND_EPISODE_COVERAGE_SCHEMA}"
        )


def _summary(report: Mapping[str, Any], *, schema: str) -> dict[str, Any]:
    return {
        "schema": schema,
        "ready_for_render": bool(report.get("ready_for_render")),
        "expected_count": int(report.get("expected_count") or 0),
        "existing_count": int(report.get("existing_count") or 0),
        "missing_count": int(report.get("missing_count") or 0),
        "coverage_ratio": float(report.get("coverage_ratio") or 0.0),
    }


def _domain_missing_assets(domain: str, report: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "domain": domain,
            "asset": str(asset),
        }
        for asset in list(report.get("missing_assets") or [])
    ]


def build_videotoon_episode_preflight_report(
    actor_coverage_report: Mapping[str, Any],
    background_coverage_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Combine actor and background asset coverage into one episode render gate."""
    _validate_report_schema(actor_coverage_report, ACTOR_COVERAGE_SCHEMA, "actor coverage report")
    _validate_background_report_schema(background_coverage_report)

    actor_pack_id = str(actor_coverage_report.get("pack_id") or "").strip()
    background_pack_id = str(background_coverage_report.get("pack_id") or "").strip()
    errors = list(actor_coverage_report.get("errors") or []) + list(background_coverage_report.get("errors") or [])
    if actor_pack_id and background_pack_id and actor_pack_id != background_pack_id:
        errors.append(f"pack_id mismatch: actor={actor_pack_id}, background={background_pack_id}")

    actor_summary = _summary(actor_coverage_report, schema=ACTOR_COVERAGE_SCHEMA)
    background_summary = _summary(background_coverage_report, schema=str(background_coverage_report.get("schema") or ""))
    expected_count = actor_summary["expected_count"] + background_summary["expected_count"]
    existing_count = actor_summary["existing_count"] + background_summary["existing_count"]
    missing_count = actor_summary["missing_count"] + background_summary["missing_count"]
    coverage_ratio = round(existing_count / expected_count, 4) if expected_count else 0.0
    missing_assets = (
        _domain_missing_assets("actor", actor_coverage_report)
        + _domain_missing_assets("background", background_coverage_report)
    )
    ready_for_render = (
        actor_summary["ready_for_render"]
        and background_summary["ready_for_render"]
        and missing_count == 0
        and not errors
    )

    return {
        "schema": PREFLIGHT_SCHEMA,
        "pack_id": actor_pack_id or background_pack_id,
        "episode_id": str(actor_coverage_report.get("episode_id") or ""),
        "ready_for_render": ready_for_render,
        "expected_count": expected_count,
        "existing_count": existing_count,
        "missing_count": missing_count,
        "coverage_ratio": coverage_ratio,
        "errors": errors,
        "missing_assets": missing_assets,
        "actor_assets": actor_summary,
        "background_assets": background_summary,
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
    }


def write_videotoon_episode_preflight_report(
    actor_coverage_path: Path | str,
    background_coverage_path: Path | str,
    output_path: Path | str,
) -> Path:
    """Write a combined video-toon episode preflight report."""
    actor_coverage = _load_json_object(actor_coverage_path, "actor coverage report")
    background_coverage = _load_json_object(background_coverage_path, "background coverage report")
    report = build_videotoon_episode_preflight_report(actor_coverage, background_coverage)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Combine actor and background coverage into a video-toon render gate.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    episode_parser = subparsers.add_parser(
        "episode",
        help="Build a video-toon episode preflight report.",
    )
    episode_parser.add_argument("--actor-coverage", required=True, help="Actor episode asset coverage JSON path.")
    episode_parser.add_argument("--background-coverage", required=True, help="Background asset coverage JSON path.")
    episode_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")
    episode_parser.add_argument("--fail-on-not-ready", action="store_true", help="Exit 1 when preflight is not ready.")

    args = parser.parse_args(argv)
    if args.command == "episode":
        actor_coverage = _load_json_object(args.actor_coverage, "actor coverage report")
        background_coverage = _load_json_object(args.background_coverage, "background coverage report")
        report = build_videotoon_episode_preflight_report(actor_coverage, background_coverage)
        if args.output:
            output = write_videotoon_episode_preflight_report(
                args.actor_coverage,
                args.background_coverage,
                args.output,
            )
            print(
                f"Wrote video-toon episode preflight for {report['pack_id']}: {output} "
                f"(missing {report['missing_count']}/{report['expected_count']})"
            )
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print(f"video-toon episode preflight missing {report['missing_count']}/{report['expected_count']}")
        if args.fail_on_not_ready and not report["ready_for_render"]:
            return 1
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
