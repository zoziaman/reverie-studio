from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

try:
    from modules_pro import background_library
    from utils import actor_model, videotoon_preflight
except ModuleNotFoundError:
    from ..modules_pro import background_library
    from . import actor_model, videotoon_preflight


PREPARE_SCHEMA = "reverie.pack.videotoon_episode_prepare.v1"


def _load_json_object(path: Path | str, label: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return data


def _safe_artifact_stem(episode: dict[str, Any]) -> str:
    raw = str(episode.get("episode_id") or "").strip() or "episode"
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in raw)


def write_videotoon_episode_prepare_bundle(
    roster_plan_path: Path | str,
    episode_path: Path | str,
    settings_path: Path | str,
    output_dir: Path | str,
    *,
    actor_root: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
    background_root: Optional[Path | str] = None,
    fail_on_not_ready: bool = False,
) -> dict[str, Any]:
    """Write the JSON preflight bundle needed before rendering a video-toon episode."""
    episode = _load_json_object(episode_path, "episode")
    roster_plan = _load_json_object(roster_plan_path, "actor roster plan")
    pack_id = str(roster_plan.get("pack_id") or "").strip()
    episode_id = str(episode.get("episode_id") or "")
    stem = _safe_artifact_stem(episode)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    actor_asset_plan_path = out_dir / f"{stem}.actor_asset_plan.json"
    actor_asset_coverage_path = out_dir / f"{stem}.actor_asset_coverage.json"
    background_requests_path = out_dir / f"{stem}.background_requests.json"
    background_coverage_path = out_dir / f"{stem}.background_coverage.json"
    preflight_path = out_dir / f"{stem}.preflight.json"
    prepare_report_path = out_dir / f"{stem}.prepare_report.json"

    actor_model.write_actor_episode_asset_plan(
        roster_plan_path,
        episode_path,
        actor_asset_plan_path,
        actor_root=actor_root,
        repo_root=repo_root,
    )
    actor_model.write_actor_episode_asset_coverage_report(
        actor_asset_plan_path,
        actor_asset_coverage_path,
        actor_root=actor_root,
        repo_root=repo_root,
    )
    background_library.write_background_episode_asset_request_manifest(
        settings_path,
        episode_path,
        background_requests_path,
        pack_id=pack_id or None,
        repo_root=str(repo_root) if repo_root is not None else None,
        background_root=str(background_root) if background_root is not None else None,
    )
    background_library.write_background_episode_asset_coverage_report(
        background_requests_path,
        episode_path,
        background_coverage_path,
        repo_root=str(repo_root) if repo_root is not None else None,
        background_root=str(background_root) if background_root is not None else None,
    )
    videotoon_preflight.write_videotoon_episode_preflight_report(
        actor_asset_coverage_path,
        background_coverage_path,
        preflight_path,
    )

    actor_coverage = _load_json_object(actor_asset_coverage_path, "actor coverage report")
    background_coverage = _load_json_object(background_coverage_path, "background coverage report")
    preflight = _load_json_object(preflight_path, "preflight report")
    report = {
        "schema": PREPARE_SCHEMA,
        "pack_id": pack_id,
        "episode_id": episode_id,
        "ready_for_render": bool(preflight.get("ready_for_render")),
        "missing_count": int(preflight.get("missing_count") or 0),
        "actor_missing_count": int(actor_coverage.get("missing_count") or 0),
        "background_missing_count": int(background_coverage.get("missing_count") or 0),
        "artifacts": {
            "actor_asset_plan": actor_asset_plan_path.name,
            "actor_asset_coverage": actor_asset_coverage_path.name,
            "background_requests": background_requests_path.name,
            "background_coverage": background_coverage_path.name,
            "preflight": preflight_path.name,
            "prepare_report": prepare_report_path.name,
        },
        "public_release_boundary": {
            "contains_generated_media": False,
            "contains_voice_samples": False,
            "contains_model_weights": False,
            "contains_private_paths": False,
        },
    }
    prepare_report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if fail_on_not_ready and not report["ready_for_render"]:
        return report
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Write a full video-toon episode prepare bundle.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    episode_parser = subparsers.add_parser(
        "episode",
        help="Write actor, background, and preflight JSON reports for one episode.",
    )
    episode_parser.add_argument("roster_plan_path", help="Input actor roster plan JSON path.")
    episode_parser.add_argument("episode_path", help="Input episode JSON path.")
    episode_parser.add_argument("settings_path", help="Input pack settings.json path.")
    episode_parser.add_argument("--actor-root", default=None, help="Directory that contains actor model folders.")
    episode_parser.add_argument("--repo-root", default=None, help="Repository root for relative path validation.")
    episode_parser.add_argument("--background-root", default=None, help="Directory that contains per-pack background folders.")
    episode_parser.add_argument("--output-dir", required=True, help="Directory where prepare artifacts should be written.")
    episode_parser.add_argument("--fail-on-not-ready", action="store_true", help="Exit 1 when the final preflight is not ready.")

    args = parser.parse_args(argv)
    if args.command == "episode":
        report = write_videotoon_episode_prepare_bundle(
            args.roster_plan_path,
            args.episode_path,
            args.settings_path,
            args.output_dir,
            actor_root=args.actor_root,
            repo_root=args.repo_root,
            background_root=args.background_root,
            fail_on_not_ready=args.fail_on_not_ready,
        )
        print(
            f"Wrote video-toon episode prepare bundle for {report['episode_id']}: "
            f"{Path(args.output_dir)} (missing {report['missing_count']})"
        )
        if args.fail_on_not_ready and not report["ready_for_render"]:
            return 1
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
