from utils.story_research import (
    build_market_research_context,
    score_story_freshness,
)


def test_market_research_context_uses_source_backed_motifs_without_actionable_details():
    bundle = build_market_research_context(
        category="senior",
        mode="scam_alert",
        topic_seed="오픈뱅킹 등록 알림",
        max_cards=2,
    )

    assert bundle.cards
    assert "Market Research Context" in bundle.context
    assert "source:" in bundle.context
    assert "오픈뱅킹" in bundle.context
    assert "실제 전화번호" in bundle.context
    assert "그대로 재현하지 말 것" in bundle.context
    assert bundle.quality_score >= 70


def test_story_freshness_score_penalizes_generic_cliche_and_rewards_specific_trend():
    generic = score_story_freshness("문자 하나로 통장이 비어버린 사기 경보 드라마")
    specific = score_story_freshness(
        "오픈뱅킹 등록 알림을 놓친 가족이 안심차단 전 마지막 출금 기록을 추적하는 사기 경보 드라마"
    )

    assert generic.score < 70
    assert specific.score > generic.score
    assert any("진부" in item for item in generic.issues)
    assert any("최신" in item or "구체" in item for item in specific.strengths)


def test_story_freshness_does_not_penalize_cliche_terms_inside_research_context():
    report = score_story_freshness(
        "오픈뱅킹 등록 알림을 놓친 부부가 경찰서에서 마지막 지급정지 기록을 따라가는 사기 경보 드라마",
        context="trend motifs: 가족 사칭, 딥보이스, 실시간 탐지",
    )

    assert report.passed
    assert not any("가족 사칭" in item for item in report.issues)
