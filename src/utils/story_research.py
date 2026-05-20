# src/utils/story_research.py
"""Source-backed story freshness helpers.

This module turns market/news/trend signals into abstract drama ingredients.
It deliberately does not copy news articles into scripts. The output is a
small prompt section that tells the writer what motif to use, what concrete
evidence object to show, and what not to include for policy/safety reasons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_SOURCE_URLS = (
    "https://www.korea.kr/news/policyNewsView.do?newsId=148959669",
    "https://www.korea.kr/news/policyNewsView.do?newsId=148956942",
    "https://m.korea.kr/briefing/pressReleaseView.do?newsId=156752329",
    "https://www.korea.kr/news/policyNewsView.do?newsId=148956167",
    "https://blog.youtube/culture-and-trends/end-of-year-summary-2025/",
)

SCAM_MODE_ALIASES = {
    "scam",
    "scam_alert",
    "senior_scam_alert",
    "fraud",
    "voice_phishing",
}

DAILY_TOON_MODE_ALIASES = {
    "daily",
    "daily_life",
    "daily_life_toon",
    "slice_of_life",
    "videotoon",
}

MYSTERY_TOON_MODE_ALIASES = {
    "mystery",
    "mystery_toon",
    "detective",
    "suspense",
}

CLICHE_PATTERNS = (
    "문자 하나",
    "통장이 비",
    "전 재산",
    "가족 사칭",
    "수상한 전화",
    "며느리",
    "시어머니",
    "충격 실화",
    "믿었던 사람이",
    "알 수 없는 이야기",
)

SPECIFICITY_TOKENS = (
    "오픈뱅킹",
    "안심차단",
    "딥보이스",
    "실시간 탐지",
    "가족 알림",
    "택배",
    "배송 지연",
    "개인정보 유출",
    "악성앱",
    "정부지원금",
    "계좌 등록",
    "지급정지",
    "통신사",
    "경찰서",
    "은행 앱",
)

ACTIONABLE_FORBIDDEN = (
    "실제 전화번호",
    "실제 계좌번호",
    "실제 URL",
    "QR코드",
    "인증번호",
    "사기 절차",
    "기관명 단정",
)


@dataclass(frozen=True)
class TrendCard:
    id: str
    title: str
    source_title: str
    source_url: str
    observed_at: str
    modes: List[str] = field(default_factory=list)
    motifs: List[str] = field(default_factory=list)
    human_conflict: str = ""
    evidence_object: str = ""
    story_angles: List[str] = field(default_factory=list)
    do_not_include: List[str] = field(default_factory=list)
    policy_notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrendCard":
        return cls(
            id=str(data.get("id") or _stable_id(data.get("title", ""))),
            title=str(data.get("title") or ""),
            source_title=str(data.get("source_title") or data.get("sourceTitle") or ""),
            source_url=str(data.get("source_url") or data.get("sourceUrl") or ""),
            observed_at=str(data.get("observed_at") or data.get("observedAt") or _today()),
            modes=[str(v) for v in data.get("modes", []) if v],
            motifs=[str(v) for v in data.get("motifs", []) if v],
            human_conflict=str(data.get("human_conflict") or data.get("humanConflict") or ""),
            evidence_object=str(data.get("evidence_object") or data.get("evidenceObject") or ""),
            story_angles=[str(v) for v in data.get("story_angles", data.get("storyAngles", [])) if v],
            do_not_include=[str(v) for v in data.get("do_not_include", data.get("doNotInclude", [])) if v],
            policy_notes=[str(v) for v in data.get("policy_notes", data.get("policyNotes", [])) if v],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "source_title": self.source_title,
            "source_url": self.source_url,
            "observed_at": self.observed_at,
            "modes": list(self.modes),
            "motifs": list(self.motifs),
            "human_conflict": self.human_conflict,
            "evidence_object": self.evidence_object,
            "story_angles": list(self.story_angles),
            "do_not_include": list(self.do_not_include),
            "policy_notes": list(self.policy_notes),
        }


@dataclass(frozen=True)
class StoryResearchBundle:
    cards: List[TrendCard]
    context: str
    quality_score: int
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "cards": [card.to_dict() for card in self.cards],
            "context": self.context,
            "quality_score": self.quality_score,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class StoryFreshnessReport:
    score: int
    issues: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.score >= 70

    def as_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "issues": list(self.issues),
            "strengths": list(self.strengths),
        }


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _stable_id(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "-", value or "trend").strip("-").lower()
    return slug[:64] or "trend"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_cache_dir() -> Path:
    return _project_root() / "data" / "research" / "trend_cards"


def _default_cards() -> List[TrendCard]:
    return [
        TrendCard(
            id="videotoon-daily-small-betrayal",
            title="작은 생활 선택이 관계를 바꾸는 일상툰",
            source_title="Reverie internal story pattern",
            source_url="local://reverie/story-patterns/daily-life-toon",
            observed_at="2026-05-01",
            modes=["daily_life_toon", "daily", "videotoon", "general"],
            motifs=["관리비", "반려동물", "단체채팅", "아파트 엘리베이터", "편의점 영수증"],
            human_conflict="누구나 겪는 작은 생활 갈등이 한 사람의 자존심과 오래된 오해를 건드린다.",
            evidence_object="찢어진 영수증, 읽지 않은 단체채팅, 현관 앞 택배 상자, 관리비 고지서",
            story_angles=[
                "큰 사건 없이도 첫 장면의 사소한 물건이 마지막 선택의 증거가 되게 한다.",
                "악역을 만들기보다 서로 다른 생활 리듬이 부딪히는 장면으로 몰입을 만든다.",
            ],
            do_not_include=["막장식 유산 분쟁", "갑작스러운 불치병", "설명만 하는 나레이션"],
            policy_notes=["자동 대량생산처럼 보이지 않게 매 화마다 구체적인 장소, 물건, 선택을 바꾼다."],
        ),
        TrendCard(
            id="videotoon-mystery-neighborhood-clue",
            title="동네 공간 안의 작은 단서로 풀리는 미스터리툰",
            source_title="Reverie internal story pattern",
            source_url="local://reverie/story-patterns/mystery-toon",
            observed_at="2026-05-01",
            modes=["mystery_toon", "mystery", "videotoon", "general"],
            motifs=["낡은 계단", "공용 우편함", "빗물 자국", "옥상 물탱크", "닫힌 가게 셔터"],
            human_conflict="겉으로는 평범한 이웃 관계 안에서 누가 무엇을 숨겼는지 조용히 의심이 커진다.",
            evidence_object="우편함에 남은 메모, 젖은 신발 자국, CCTV 사각지대, 오래된 열쇠",
            story_angles=[
                "첫 컷의 배경 소품을 마지막 반전의 공정한 단서로 회수한다.",
                "공포 괴물이나 점프스케어 없이 사람의 말과 행동의 모순으로 긴장을 만든다.",
            ],
            do_not_include=["고어", "귀신 실체화", "무작위 납치", "설명 불가능한 초자연 해결"],
            policy_notes=["미스터리는 단서 중심으로 설계하고, 썸네일과 제목은 과장된 실화 주장 없이 만든다."],
        ),
        TrendCard(
            id="kr-voice-phishing-ai-detection",
            title="딥보이스와 가족·정부지원금 사칭 통화 탐지",
            source_title="보이스피싱 탐지·알림 서비스 이용하세요",
            source_url="https://www.korea.kr/news/policyNewsView.do?newsId=148959669",
            observed_at="2026-02-19",
            modes=["senior", "scam_alert", "senior_scam_alert"],
            motifs=["딥보이스", "가족 사칭", "정부지원금 사칭", "실시간 탐지"],
            human_conflict="가족이 '목소리가 맞다'는 확신과 탐지 알림 사이에서 서로를 의심한다.",
            evidence_object="통화 중 뜬 딥보이스 의심 알림과 가족 단체방의 부재중 전화 기록",
            story_angles=[
                "진짜 가족 목소리처럼 들린 전화 뒤에 탐지 알림이 늦게 뜬다.",
                "정부지원금 안내라고 믿은 문장이 가족의 오래된 불안을 건드린다.",
            ],
            do_not_include=list(ACTIONABLE_FORBIDDEN),
            policy_notes=["사기 수법 절차를 설명하지 말고 탐지·의심·확인 행동 중심으로 재구성한다."],
        ),
        TrendCard(
            id="kr-open-banking-safe-block",
            title="오픈뱅킹 안심차단과 연결 계좌 사각지대",
            source_title="오픈뱅킹 안심차단 서비스로 예방하세요",
            source_url="https://www.korea.kr/news/policyNewsView.do?newsId=148956942",
            observed_at="2026-01-05",
            modes=["senior", "scam_alert", "senior_scam_alert", "family"],
            motifs=["오픈뱅킹", "안심차단", "계좌 등록", "가족 알림"],
            human_conflict="자녀는 미리 차단하자고 했지만 부모는 번거롭다며 미뤘고, 알림이 울린 뒤 서로를 탓한다.",
            evidence_object="은행 앱의 오픈뱅킹 등록 알림, 마지막 조회 시간, 가려진 계좌 끝자리",
            story_angles=[
                "아침 식탁에서 뒤늦게 발견한 오픈뱅킹 등록 알림으로 시작한다.",
                "가족이 피해자를 탓하다가 사실은 모두가 확인을 미룬 책임이 드러난다.",
            ],
            do_not_include=list(ACTIONABLE_FORBIDDEN),
            policy_notes=["계좌·금액은 가짜/마스킹 처리하고 예방 서비스 설명은 짧게 둔다."],
        ),
        TrendCard(
            id="kr-coupang-smishing-delivery-delay",
            title="배송 지연·개인정보 유출 불안을 악용한 스미싱",
            source_title="쿠팡 개인정보 유출 스미싱 문자, 절대 누르지 마세요",
            source_url="https://www.korea.kr/news/policyNewsView.do?newsId=148956167",
            observed_at="2025-12-10",
            modes=["senior", "scam_alert", "senior_scam_alert", "everyday"],
            motifs=["택배", "배송 지연", "개인정보 유출", "스미싱"],
            human_conflict="선물 배송을 기다리던 가족이 불안 때문에 확인 버튼을 누를 뻔하고, 서로의 디지털 습관을 비난한다.",
            evidence_object="배송 지연 문자, 흐릿한 택배 상자, 차단된 링크 미리보기",
            story_angles=[
                "손주 선물이 늦어진다는 문자가 평범한 거실을 긴장시키는 장면.",
                "개인정보 유출 뉴스와 배송 문자가 겹치며 판단력이 흔들린다.",
            ],
            do_not_include=list(ACTIONABLE_FORBIDDEN),
            policy_notes=["특정 기업 비난처럼 보이지 않도록 '대형 쇼핑몰 사칭'으로 허구화한다."],
        ),
        TrendCard(
            id="kr-cross-agency-fraud-response",
            title="금융·통신·수사기관 정보 공유와 빠른 지급정지",
            source_title="보이스피싱 범죄 대응 시행령 입법예고",
            source_url="https://m.korea.kr/briefing/pressReleaseView.do?newsId=156752329",
            observed_at="2026-04-01",
            modes=["senior", "scam_alert", "senior_scam_alert"],
            motifs=["지급정지", "통신사", "경찰서", "정보 공유"],
            human_conflict="피해자는 이미 늦었다고 포기하지만 가족은 은행·통신사·경찰 사이를 뛰며 마지막 가능성을 붙잡는다.",
            evidence_object="경찰서 접수증, 은행 앱 지급정지 안내, 통신사 스팸 신고 화면",
            story_angles=[
                "경찰서 조사 책상 위에 세 기관의 알림이 동시에 쌓인다.",
                "가족이 서로 탓하던 장면이 신고와 차단을 함께 하는 장면으로 뒤집힌다.",
            ],
            do_not_include=list(ACTIONABLE_FORBIDDEN),
            policy_notes=["제도 설명 영상이 아니라 인물의 선택과 감정 변화로 보여준다."],
        ),
        TrendCard(
            id="youtube-specific-community-formats",
            title="반복 포맷보다 구체적 상황·커뮤니티 반응이 강한 영상 흐름",
            source_title="YouTube Culture & Trends 2025",
            source_url="https://blog.youtube/culture-and-trends/end-of-year-summary-2025/",
            observed_at="2025-12-01",
            modes=["horror", "makjang", "touching", "senior", "shorts", "general"],
            motifs=["구체적 생활 디테일", "댓글을 부르는 딜레마", "짧은 재해석 가능 장면"],
            human_conflict="누가 봐도 정답이 있는 사건보다 댓글에서 편이 갈릴 선택을 전면에 둔다.",
            evidence_object="시청자가 멈춰 보게 되는 영수증, 메모, 채팅 캡처, 가족사진 같은 일상 물건",
            story_angles=[
                "사건 자체보다 '그때 왜 아무도 말리지 않았나'라는 선택의 책임으로 끌고 간다.",
                "롱폼 본편 안에 쇼츠로 잘라낼 수 있는 15초 딜레마 장면을 심는다.",
            ],
            do_not_include=["뉴스 원문 복사", "유행어 남발", "댓글 조작 유도"],
            policy_notes=["대량생산처럼 보이지 않게 매 회차마다 다른 구체적 물건과 선택을 배치한다."],
        ),
    ]


def _normalize_mode(category: str, mode: str) -> List[str]:
    values = []
    for raw in (category, mode):
        text = (raw or "").strip().lower()
        if text:
            values.append(text)
    if any(v in SCAM_MODE_ALIASES or "scam" in v for v in values):
        values.extend(["scam_alert", "senior_scam_alert"])
    if any(v in DAILY_TOON_MODE_ALIASES for v in values):
        values.extend(["daily_life_toon", "daily", "videotoon", "general"])
    if any(v in MYSTERY_TOON_MODE_ALIASES for v in values):
        values.extend(["mystery_toon", "mystery", "videotoon", "general"])
    return list(dict.fromkeys(values or ["general"]))


def _load_cached_cards(cache_dir: Optional[os.PathLike[str] | str] = None) -> List[TrendCard]:
    root = Path(cache_dir) if cache_dir else _default_cache_dir()
    if not root.exists():
        return []

    cards: List[TrendCard] = []
    for path in sorted(root.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            items = raw.get("cards", raw) if isinstance(raw, dict) else raw
            if not isinstance(items, list):
                continue
            cards.extend(TrendCard.from_dict(item) for item in items if isinstance(item, dict))
        except Exception:
            continue
    return cards


def save_trend_cards(cards: Sequence[TrendCard], path: os.PathLike[str] | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cards": [card.to_dict() for card in cards],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _matches_mode(card: TrendCard, modes: Sequence[str]) -> bool:
    card_modes = {m.lower() for m in card.modes}
    if not card_modes:
        return True
    mode_set = set(modes)
    return bool(card_modes & mode_set) or "general" in card_modes


def _rank_cards(cards: Sequence[TrendCard], modes: Sequence[str], topic_seed: str = "") -> List[TrendCard]:
    seed = topic_seed or ""

    def score(card: TrendCard) -> int:
        value = 0
        if _matches_mode(card, modes):
            value += 40
        for motif in card.motifs:
            if motif and motif in seed:
                value += 20
        for mode in modes:
            if mode and mode in card.modes:
                value += 5
        if card.source_url:
            value += 5
        return value

    dedup: Dict[str, TrendCard] = {}
    for card in cards:
        dedup.setdefault(card.id, card)
    return sorted(dedup.values(), key=score, reverse=True)


def _fetch_title(url: str, timeout: float = 4.0) -> str:
    request = Request(url, headers={"User-Agent": "ReverieStoryResearch/1.0"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read(180_000)
    text = data.decode("utf-8", errors="ignore")
    match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.I | re.S)
    if not match:
        return ""
    return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()


def fetch_live_source_cards(urls: Iterable[str] = DEFAULT_SOURCE_URLS) -> List[TrendCard]:
    """Best-effort live source check.

    This is intentionally disabled by default in production runs. Enable it by
    setting REVERIE_STORY_RESEARCH_LIVE=1 before a research refresh command.
    """
    cards: List[TrendCard] = []
    for url in urls:
        try:
            title = _fetch_title(url)
        except Exception:
            continue
        if not title:
            continue
        cards.append(
            TrendCard(
                id=f"live-{_stable_id(title)}",
                title=title[:80],
                source_title=title[:120],
                source_url=url,
                observed_at=_today(),
                modes=["general"],
                motifs=["최신 이슈", "구체적 생활 디테일"],
                human_conflict="최근 이슈를 직접 재현하지 않고 인물의 선택 갈등으로 추상화한다.",
                evidence_object="뉴스를 본 휴대폰 화면이나 가족 단체방 캡처",
                story_angles=["최근 이슈를 생활 속 오해와 선택의 책임으로 바꿔 쓴다."],
                do_not_include=["기사 문장 복사", "실명 피해자", "확인 안 된 사실 단정"],
                policy_notes=["출처는 시장조사용이며 대본은 창작 재구성으로 처리한다."],
            )
        )
    return cards


def format_cards_for_prompt(cards: Sequence[TrendCard]) -> str:
    if not cards:
        return ""

    lines = [
        "[Market Research Context]",
        "Use these as abstract story ingredients only. 그대로 복사하지 말고, 그대로 재현하지 말 것.",
    ]
    for index, card in enumerate(cards, 1):
        source_host = urlparse(card.source_url).netloc or "source"
        lines.append(f"{index}. {card.title}")
        lines.append(f"   - source: {card.source_title} [{source_host}]")
        if card.motifs:
            lines.append(f"   - trend motifs: {', '.join(card.motifs[:6])}")
        if card.human_conflict:
            lines.append(f"   - human conflict: {card.human_conflict}")
        if card.evidence_object:
            lines.append(f"   - evidence object: {card.evidence_object}")
        if card.story_angles:
            lines.append(f"   - usable angles: {' / '.join(card.story_angles[:2])}")
        blocked = list(dict.fromkeys([*ACTIONABLE_FORBIDDEN, *card.do_not_include]))
        lines.append(f"   - do not include: {', '.join(blocked[:10])}")
    lines.append("[Research Use Rule] 최신감은 모티프/소품/갈등에만 반영하고, 뉴스 원문·실명·기관 단정·사기 절차는 배제.")
    return "\n".join(lines)


def build_market_research_context(
    *,
    category: str,
    mode: str = "",
    topic_seed: str = "",
    max_cards: int = 2,
    cache_dir: Optional[os.PathLike[str] | str] = None,
    include_live: Optional[bool] = None,
) -> StoryResearchBundle:
    modes = _normalize_mode(category, mode)
    warnings: List[str] = []
    cards = [*_default_cards(), *_load_cached_cards(cache_dir)]

    live_enabled = include_live
    if live_enabled is None:
        live_enabled = os.getenv("REVERIE_STORY_RESEARCH_LIVE", "").strip() == "1"
    if live_enabled:
        live_cards = fetch_live_source_cards()
        if live_cards:
            cards.extend(live_cards)
        else:
            warnings.append("live source fetch returned no cards; using cached/default cards")

    ranked = [card for card in _rank_cards(cards, modes, topic_seed) if _matches_mode(card, modes)]
    if not ranked:
        ranked = _rank_cards(cards, ["general"], topic_seed)
    selected = ranked[: max(1, max_cards)]
    context = format_cards_for_prompt(selected)
    quality = min(100, 60 + len(selected) * 12 + sum(1 for c in selected if c.source_url) * 4)
    return StoryResearchBundle(
        cards=list(selected),
        context=context,
        quality_score=quality,
        warnings=warnings,
    )


def score_story_freshness(
    topic: str,
    *,
    context: str = "",
    cards: Optional[Sequence[TrendCard]] = None,
) -> StoryFreshnessReport:
    topic_text = topic or ""
    text = f"{topic_text}\n{context or ''}"
    score = 72
    issues: List[str] = []
    strengths: List[str] = []

    for pattern in CLICHE_PATTERNS:
        if pattern and pattern in topic_text:
            score -= 9
            issues.append(f"진부한 상투어 감지: {pattern}")

    matched_specific = [token for token in SPECIFICITY_TOKENS if token in text]
    if matched_specific:
        boost = min(20, len(matched_specific) * 4)
        score += boost
        strengths.append(f"최신/구체 디테일 포함: {', '.join(matched_specific[:5])}")
    else:
        score -= 10
        issues.append("최신 이슈나 구체적 생활 소품이 부족함")

    if cards:
        card_motifs = []
        for card in cards:
            card_motifs.extend(getattr(card, "motifs", []) or [])
        if any(motif in text for motif in card_motifs):
            score += 8
            strengths.append("시장조사 카드 모티프와 연결됨")

    if len(re.findall(r"[가-힣]{2,}", topic or "")) < 5:
        score -= 6
        issues.append("주제가 너무 짧아 장면 차별성이 약함")

    if re.search(r"실화|충격|소름", topic or ""):
        score -= 6
        issues.append("정책/수익화 리스크가 있는 과장 표현 포함")

    score = max(0, min(100, score))
    if score >= 80 and not strengths:
        strengths.append("진부 패턴이 적고 소재가 비교적 선명함")
    return StoryFreshnessReport(score=score, issues=list(dict.fromkeys(issues)), strengths=list(dict.fromkeys(strengths)))
