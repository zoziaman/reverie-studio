from utils.youtube_policy_guard import prepare_upload_metadata


def test_sanitizes_unverified_true_story_claims_and_softens_shock_terms():
    result = prepare_upload_metadata(
        title="충격 실화 | 소름 돋는 사건",
        description="실화를 바탕으로 재구성했습니다.",
        tags=["실화괴담", "충격", "미스터리"],
        channel_mode="horror",
        verified_true_story=False,
    )

    assert "실화" not in result.title
    assert "충격" not in result.title
    assert "실화" not in "".join(result.tags)
    assert "AI 음성/이미지/편집 도구" in result.description
    assert result.errors == []
    assert result.warnings


def test_adds_scam_prevention_disclaimer_for_scam_alert_mode():
    result = prepare_upload_metadata(
        title="보이스피싱 예방 드라마",
        description="문자와 계좌 내역을 확인하는 장면입니다.",
        tags=["사기예방", "보이스피싱"],
        channel_mode="scam_alert",
    )

    assert "예방 목적의 창작 재구성" in result.description
    assert "따라 하도록 돕기 위한 영상이 아닙니다" in result.description
    assert result.errors == []


def test_blocks_public_metadata_with_real_contact_or_account_patterns():
    result = prepare_upload_metadata(
        title="보이스피싱 문자 원문 공개",
        description="010-1234-5678 계좌 123-456-789012로 보내라는 문자",
        tags=["사기예방"],
        channel_mode="scam_alert",
        privacy="public",
    )

    assert result.ok is False
    assert any("개인정보" in error or "계좌" in error for error in result.errors)


def test_preserves_verified_true_story_claims_when_explicitly_allowed():
    result = prepare_upload_metadata(
        title="실화 기반 시니어 드라마",
        description="검증된 제보를 바탕으로 제작했습니다.",
        tags=["실화", "시니어"],
        channel_mode="touching",
        verified_true_story=True,
    )

    assert "실화" in result.title
    assert "실화" in result.tags
    assert result.errors == []
