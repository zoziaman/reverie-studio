"""Public dry-run quality gate for Reverie Studio."""

from __future__ import annotations


REQUIRED_PACK_FIELDS = {"pack_id", "name", "story_beats", "expected_gates"}


def _score_pack_contract(pack: dict) -> tuple[float, str]:
    missing = sorted(REQUIRED_PACK_FIELDS.difference(pack))
    if missing:
        return 0.0, f"missing fields: {', '.join(missing)}"
    if not isinstance(pack.get("story_beats"), list) or not pack["story_beats"]:
        return 0.0, "story_beats must be a non-empty list"
    return 1.0, "pack contract is complete"


def _score_stage_observability(stages: list[dict]) -> tuple[float, str]:
    if not stages:
        return 0.0, "no stages were reported"
    if all(stage.get("name") and stage.get("status") for stage in stages):
        return 1.0, "all stages include name and status"
    return 0.4, "some stages are missing name or status"


def _score_duration_cost_tracking(stages: list[dict]) -> tuple[float, str]:
    if not stages:
        return 0.0, "no stages were reported"
    observed = [
        stage
        for stage in stages
        if "duration_seconds" in stage and "cost_usd" in stage
    ]
    ratio = len(observed) / len(stages)
    if ratio == 1.0:
        return 1.0, "all stages include duration and cost placeholders"
    if ratio >= 0.5:
        return 0.7, "most stages include duration and cost placeholders"
    return 0.4, "duration and cost tracking is incomplete"


def _score_backend_boundary(backend_profile: dict) -> tuple[float, str]:
    if not backend_profile.get("id"):
        return 0.0, "backend profile is missing an id"
    safety = backend_profile.get("safety", {})
    if safety.get("calls_external_services_by_default") is True:
        return 0.5, "backend may call external services by default"
    return 1.0, "backend default is local or dry-run safe"


def _score_upload_review(stages: list[dict], backend_profile: dict) -> tuple[float, str, list[str]]:
    upload_mode = backend_profile.get("upload", {}).get("default_mode")
    upload_blocked = any(
        stage.get("name") == "upload_gate" and stage.get("status") == "blocked_for_review"
        for stage in stages
    )
    if upload_mode == "manual_private_review" or upload_blocked:
        return 1.0, "upload is gated behind manual private review", ["manual_upload_review"]
    return 0.0, "upload gate is not explicit", ["manual_upload_review"]


def evaluate_quality_gate(
    pack: dict,
    stages: list[dict],
    backend_profile: dict,
    threshold: float = 0.75,
) -> dict:
    """Evaluate the public dry-run quality gate without reading media files."""

    pack_score, pack_note = _score_pack_contract(pack)
    stage_score, stage_note = _score_stage_observability(stages)
    duration_score, duration_note = _score_duration_cost_tracking(stages)
    backend_score, backend_note = _score_backend_boundary(backend_profile)
    upload_score, upload_note, reviews = _score_upload_review(stages, backend_profile)

    weighted = [
        ("pack_contract", 0.25, pack_score, pack_note),
        ("stage_observability", 0.20, stage_score, stage_note),
        ("duration_cost_tracking", 0.15, duration_score, duration_note),
        ("backend_boundary", 0.20, backend_score, backend_note),
        ("upload_review_gate", 0.20, upload_score, upload_note),
    ]
    score = round(sum(weight * value for _, weight, value, _ in weighted), 4)
    fatal_issues = [note for _, _, value, note in weighted if value == 0.0]
    status = "pass" if score >= threshold and not fatal_issues else "needs_review"
    return {
        "status": status,
        "score": score,
        "threshold": threshold,
        "requires_human_review": bool(reviews),
        "required_reviews": reviews,
        "components": [
            {"id": item_id, "weight": weight, "score": value, "note": note}
            for item_id, weight, value, note in weighted
        ],
        "fatal_issues": fatal_issues,
    }
