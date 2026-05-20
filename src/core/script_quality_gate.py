import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    from config.pack_config import get_script_quality_config
except ImportError:  # pragma: no cover - local fallback
    get_script_quality_config = None


_NARRATOR_ROLES = {"나레이션", "내레이션", "narrator"}
_TOPIC_STOPWORDS = {
    "그리고", "하지만", "그러나", "때문에", "순간", "사실은", "외부의", "이야기",
    "영상", "챌린지", "소름", "끼치는", "들려오는", "걸려온", "드러나자",
}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _strip_topic_suffix(word: str) -> str:
    suffixes = ("으로", "에서", "에게", "처럼", "이다", "하는", "하고", "하며", "했다", "였다")
    for suffix in suffixes:
        if len(word) > len(suffix) + 1 and word.endswith(suffix):
            return word[: -len(suffix)]
    if len(word) > 2 and word[-1] in "은는이가을를도의만":
        return word[:-1]
    return word


def _extract_topic_keywords(topic: str, limit: int = 8) -> List[str]:
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", topic or "")
    out: List[str] = []
    for word in words:
        if word in _TOPIC_STOPWORDS:
            continue
        normalized = _strip_topic_suffix(word)
        if len(normalized) < 2:
            continue
        if normalized not in out:
            out.append(normalized)
        if len(out) >= limit:
            break
    return out


@dataclass
class ScriptQualityIssue:
    code: str
    severity: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScriptQualityReport:
    passed: bool
    score: int
    metrics: Dict[str, Any]
    issues: List[ScriptQualityIssue] = field(default_factory=list)

    def fatal_issues(self) -> List[ScriptQualityIssue]:
        return [issue for issue in self.issues if issue.severity == "fatal"]

    def warning_issues(self) -> List[ScriptQualityIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "metrics": self.metrics,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "message": issue.message,
                    "details": issue.details,
                }
                for issue in self.issues
            ],
        }

    def summary(self) -> str:
        if self.passed:
            return f"score={self.score} warnings={len(self.warning_issues())}"
        return ", ".join(f"{issue.code}: {issue.message}" for issue in self.fatal_issues())


class ScriptQualityError(ValueError):
    def __init__(self, report: ScriptQualityReport):
        self.report = report
        super().__init__(f"Script quality gate failed: {report.summary()}")


def evaluate_script_quality(
    topic: str,
    script_list: List[Dict[str, Any]],
    category: str = "",
    mode: str = "",
) -> ScriptQualityReport:
    issues: List[ScriptQualityIssue] = []
    normalized_texts = [_normalize_text(item.get("text", "")) for item in script_list if _normalize_text(item.get("text", ""))]
    total_turns = len(normalized_texts)
    role_values = [_normalize_text(item.get("role", "")) for item in script_list if _normalize_text(item.get("role", ""))]
    non_narrator_roles = sorted({role for role in role_values if role not in _NARRATOR_ROLES})
    narrator_count = sum(1 for role in role_values if role in _NARRATOR_ROLES)
    ellipsis_count = sum(1 for text in normalized_texts if text in {"...", ".."} or re.fullmatch(r"\.+", text))
    duplicate_counts = Counter(normalized_texts)
    unique_ratio = (len(duplicate_counts) / total_turns) if total_turns else 0.0
    max_duplicate_count = duplicate_counts.most_common(1)[0][1] if duplicate_counts else 0
    narration_ratio = (narrator_count / len(role_values)) if role_values else 0.0
    ellipsis_ratio = (ellipsis_count / total_turns) if total_turns else 0.0
    has_fallback_marker = any(item.get("_is_fallback") for item in script_list)

    topic_keywords = _extract_topic_keywords(topic)
    script_blob = " ".join(normalized_texts)
    matched_keywords = [kw for kw in topic_keywords if kw and kw in script_blob]
    topic_overlap_ratio = (len(matched_keywords) / len(topic_keywords)) if topic_keywords else 1.0

    quality_config = (
        get_script_quality_config(category=category, mode=mode)
        if get_script_quality_config is not None
        else None
    )
    min_non_narrator_roles = getattr(quality_config, "min_non_narrator_roles", 3)
    max_narration_ratio = getattr(quality_config, "max_narration_ratio", 0.5)
    min_turns_for_gate = getattr(quality_config, "min_turns_for_gate", 20)
    max_ellipsis_ratio = getattr(quality_config, "max_ellipsis_ratio", 0.12)
    warn_topic_overlap_ratio = getattr(quality_config, "warn_topic_overlap_ratio", 0.25)

    if total_turns == 0:
        issues.append(ScriptQualityIssue("empty_script", "fatal", "대본이 비어 있습니다."))
    if has_fallback_marker:
        issues.append(ScriptQualityIssue("fallback_marker", "fatal", "비상 템플릿 대본 마커가 남아 있습니다."))
    if total_turns >= min_turns_for_gate and unique_ratio < 0.8:
        issues.append(
            ScriptQualityIssue(
                "low_uniqueness",
                "fatal",
                "중복 문장이 과도합니다.",
                {"unique_ratio": round(unique_ratio, 3)},
            )
        )
    if total_turns >= min_turns_for_gate and max_duplicate_count > max(3, int(total_turns * 0.12)):
        issues.append(
            ScriptQualityIssue(
                "duplicate_spike",
                "fatal",
                "동일 문장이 비정상적으로 반복됩니다.",
                {"max_duplicate_count": max_duplicate_count},
            )
        )
    if len(non_narrator_roles) < min_non_narrator_roles:
        issues.append(
            ScriptQualityIssue(
                "role_variety",
                "fatal",
                "실제 등장인물 수가 부족합니다.",
                {"non_narrator_roles": non_narrator_roles},
            )
        )
    if total_turns >= min_turns_for_gate and narration_ratio > max_narration_ratio:
        issues.append(
            ScriptQualityIssue(
                "narration_ratio",
                "fatal",
                "나레이션 비중이 과도합니다.",
                {"narration_ratio": round(narration_ratio, 3)},
            )
        )
    if total_turns >= min_turns_for_gate and ellipsis_ratio > max_ellipsis_ratio:
        issues.append(
            ScriptQualityIssue(
                "ellipsis_ratio",
                "warning",
                "생략부호 대사가 지나치게 많습니다.",
                {"ellipsis_ratio": round(ellipsis_ratio, 3)},
            )
        )
    if topic_keywords and total_turns >= min_turns_for_gate and len(topic_keywords) >= 2 and topic_overlap_ratio == 0:
        issues.append(
            ScriptQualityIssue(
                "topic_detached",
                "fatal",
                "주제와 대본 본문이 사실상 연결되지 않습니다.",
                {"matched_keywords": matched_keywords, "topic_keywords": topic_keywords},
            )
        )
    elif topic_keywords and topic_overlap_ratio < warn_topic_overlap_ratio:
        issues.append(
            ScriptQualityIssue(
                "topic_alignment",
                "warning",
                "주제 키워드와 대본 본문 정합성이 낮습니다.",
                {"matched_keywords": matched_keywords, "topic_keywords": topic_keywords},
            )
        )

    score = 100
    for issue in issues:
        score -= 25 if issue.severity == "fatal" else 8
    score = max(score, 0)

    metrics = {
        "total_turns": total_turns,
        "unique_ratio": round(unique_ratio, 3),
        "max_duplicate_count": max_duplicate_count,
        "narration_ratio": round(narration_ratio, 3),
        "ellipsis_ratio": round(ellipsis_ratio, 3),
        "non_narrator_roles": non_narrator_roles,
        "topic_keywords": topic_keywords,
        "matched_keywords": matched_keywords,
        "topic_overlap_ratio": round(topic_overlap_ratio, 3),
    }
    passed = not any(issue.severity == "fatal" for issue in issues)
    return ScriptQualityReport(passed=passed, score=score, metrics=metrics, issues=issues)


def assert_script_quality(
    topic: str,
    script_list: List[Dict[str, Any]],
    category: str = "",
    mode: str = "",
) -> ScriptQualityReport:
    report = evaluate_script_quality(topic, script_list, category=category, mode=mode)
    if not report.passed:
        raise ScriptQualityError(report)
    return report
