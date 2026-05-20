# src/utils/youtube_policy_guard.py
"""YouTube upload metadata guardrails.

The goal is not to hide AI usage. The safer monetization posture is:
disclose synthetic media, avoid unverified "true story" claims, keep scam
content preventive, and reduce template-like shock metadata.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, Iterable, List


TRUE_STORY_REPLACEMENTS = (
    ("실화괴담", "공포드라마"),
    ("무서운실화", "무서운이야기"),
    ("실화공포", "공포드라마"),
    ("충격실화", "반전드라마"),
    ("감동실화", "감동드라마"),
    ("막장 실화", "가족 드라마"),
    ("막장실화", "가족드라마"),
    ("실화 기반", "사례 재구성"),
    ("실화를 바탕으로", "사례를 바탕으로 창작 재구성한"),
    ("실화입니다", "창작 드라마입니다"),
    ("진짜 있었던", "있을 법한"),
    ("실화", "사례 재구성"),
)

SHOCK_REPLACEMENTS = (
    ("충격적인", "반전이 있는"),
    ("충격적", "반전 있는"),
    ("결말충격", "결말반전"),
    ("충격", "반전"),
    ("소름 주의", "긴장 주의"),
    ("소름주의", "긴장주의"),
    ("대박", "주목"),
)

AI_DISCLOSURE = (
    "이 영상은 AI 음성/이미지/편집 도구를 활용한 창작 드라마이며, "
    "실제 인물·사건과 다를 수 있습니다."
)

SCAM_PREVENTION_DISCLOSURE = (
    "이 콘텐츠는 사기 예방 목적의 창작 재구성이며, "
    "사기 수법을 따라 하도록 돕기 위한 영상이 아닙니다."
)

PHONE_PATTERN = re.compile(r"(?<!\d)01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}(?!\d)")
ACCOUNT_PATTERN = re.compile(r"(?:계좌\s*)?\b\d{2,6}[-\s]\d{2,6}[-\s]\d{4,8}\b")
URL_PATTERN = re.compile(r"(?:https?://|www\.|[A-Za-z0-9.-]+\.(?:com|net|kr|org)\b)")
AUTH_CODE_PATTERN = re.compile(r"(?:인증번호|OTP|보안코드)\s*[:：]?\s*\d{4,8}", re.IGNORECASE)


@dataclass
class PolicyGuardResult:
    title: str
    description: str
    tags: List[str]
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def _collapse_spaces(value: str) -> str:
    return re.sub(r"\s{2,}", " ", (value or "").strip())


def _apply_replacements(value: str, replacements: Iterable[tuple[str, str]]) -> str:
    out = value or ""
    for src, dst in replacements:
        out = out.replace(src, dst)
    return _collapse_spaces(out)


def _sanitize_true_story_claims(value: str, verified_true_story: bool, warnings: List[str]) -> str:
    if verified_true_story:
        return _collapse_spaces(value)
    before = value or ""
    after = _apply_replacements(before, TRUE_STORY_REPLACEMENTS)
    if after != _collapse_spaces(before):
        warnings.append("검증되지 않은 실화 표현을 창작/사례 재구성 표현으로 보정했습니다.")
    return after


def _soften_shock_language(value: str, warnings: List[str]) -> str:
    before = value or ""
    after = _apply_replacements(before, SHOCK_REPLACEMENTS)
    if after != _collapse_spaces(before):
        warnings.append("과도한 충격/소름 표현을 완화했습니다.")
    return after


def _sanitize_tags(tags: Iterable[Any], verified_true_story: bool, warnings: List[str]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for raw in tags or []:
        tag = str(raw or "").strip().lstrip("#")
        if not tag:
            continue
        tag = _sanitize_true_story_claims(tag, verified_true_story, warnings)
        tag = _soften_shock_language(tag, warnings)
        tag = re.sub(r"[^\w가-힣A-Za-z0-9_-]", "", tag)
        if not tag or tag in seen:
            continue
        seen.add(tag)
        cleaned.append(tag)
    return cleaned[:15]


def _ensure_description_disclosures(description: str, channel_mode: str) -> str:
    parts = [_collapse_spaces(description) or "창작 드라마 콘텐츠입니다."]

    if "AI 음성/이미지/편집 도구" not in description:
        parts.append(AI_DISCLOSURE)

    if (channel_mode or "").strip().lower() in {"scam_alert", "senior_scam_alert", "scam"}:
        if "사기 예방 목적의 창작 재구성" not in description:
            parts.append(SCAM_PREVENTION_DISCLOSURE)

    return "\n\n".join(part for part in parts if part)


def _collect_policy_errors(title: str, description: str, tags: List[str], channel_mode: str) -> List[str]:
    combined = "\n".join([title or "", description or "", " ".join(tags or [])])
    errors: List[str] = []

    if PHONE_PATTERN.search(combined):
        errors.append("개인정보처럼 보이는 전화번호가 포함되어 있습니다.")
    if ACCOUNT_PATTERN.search(combined):
        errors.append("실제 계좌번호처럼 보이는 숫자 패턴이 포함되어 있습니다.")
    if AUTH_CODE_PATTERN.search(combined):
        errors.append("인증번호/OTP처럼 보이는 민감 정보가 포함되어 있습니다.")
    if URL_PATTERN.search(combined):
        errors.append("외부 URL이 포함되어 있어 사기/오해 리스크가 있습니다.")

    scam_mode = (channel_mode or "").strip().lower() in {"scam_alert", "senior_scam_alert", "scam"}
    if scam_mode and re.search(r"(따라\s*하는\s*법|수법\s*공개|원문\s*그대로|복붙|바로\s*입금)", combined):
        errors.append("사기 수법을 실행 가능하게 보이게 하는 표현이 포함되어 있습니다.")

    return errors


def prepare_upload_metadata(
    *,
    title: str,
    description: str = "",
    tags: Iterable[Any] = (),
    channel_mode: str = "",
    privacy: str = "private",
    verified_true_story: bool = False,
) -> PolicyGuardResult:
    """Return policy-safe metadata and a report.

    Private uploads are still checked because a private video can later be made
    public without regenerating metadata.
    """
    warnings: List[str] = []

    safe_title = _sanitize_true_story_claims(title or "창작 드라마", verified_true_story, warnings)
    safe_title = _soften_shock_language(safe_title, warnings)

    safe_description = _sanitize_true_story_claims(description or "", verified_true_story, warnings)
    safe_description = _soften_shock_language(safe_description, warnings)
    safe_description = _ensure_description_disclosures(safe_description, channel_mode)

    safe_tags = _sanitize_tags(tags or [], verified_true_story, warnings)
    errors = _collect_policy_errors(safe_title, safe_description, safe_tags, channel_mode)

    if (privacy or "private").lower() in {"public", "unlisted"} and not safe_description:
        errors.append("공개/일부공개 업로드에는 설명문이 필요합니다.")

    return PolicyGuardResult(
        title=safe_title[:100],
        description=safe_description[:5000],
        tags=safe_tags,
        warnings=list(dict.fromkeys(warnings)),
        errors=errors,
    )
