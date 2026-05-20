from core.script_quality_gate import ScriptQualityError, assert_script_quality, evaluate_script_quality


def test_quality_gate_rejects_repetitive_script():
    script = [
        {"role": "나레이션", "text": "오래된 골목길, 작은 이발소가 하나 있었습니다."},
        {"role": "나레이션", "text": "주인 할아버지는 50년째 그 자리를 지키고 있었습니다."},
        {"role": "할아버지", "text": "어서 오세요."},
        {"role": "남자", "text": "할아버지, 잘 지내셨어요?"},
    ] * 12

    report = evaluate_script_quality(
        "빗소리 ASMR 들으며 나뭇잎에 그림 그리기 챌린지",
        script,
        category="senior",
        mode="makjang",
    )

    assert report.passed is False
    assert any(issue.code == "low_uniqueness" for issue in report.issues)
    assert any(issue.code == "duplicate_spike" for issue in report.issues)


def test_quality_gate_accepts_balanced_horror_script():
    script = []
    for idx in range(8):
        script.extend(
            [
                {"role": "나레이션", "text": f"폭설이 오두막 창문을 때리던 밤, 철길 진동이 {idx+1}번째로 울렸습니다."},
                {"role": "진우", "text": f"서희야, {idx+1}칸 아래 폐철길에서 또 마찰음이 들려."},
                {"role": "서희", "text": f"이번엔 확실해요. 척추를 긁는 소리처럼 점점 가까워져요. {idx+1}번은 더 선명했어요."},
            ]
        )

    report = assert_script_quality(
        "폭설로 고립된 오두막 바닥의 폐철길 아래에서 들려오는 기괴한 마찰음",
        script,
        category="horror",
        mode="horror",
    )

    assert report.passed is True
    assert report.score > 70


def test_quality_gate_raises_on_fatal_issue():
    script = [{"role": "나레이션", "text": "fallback", "_is_fallback": True}] * 5

    try:
        assert_script_quality("테스트 주제", script, category="horror", mode="horror")
    except ScriptQualityError as exc:
        assert exc.report.passed is False
        assert any(issue.code == "fallback_marker" for issue in exc.report.issues)
    else:
        raise AssertionError("ScriptQualityError was not raised")


def test_quality_gate_uses_pack_driven_thresholds(monkeypatch):
    import core.script_quality_gate as gate_module

    monkeypatch.setattr(
        gate_module,
        "get_script_quality_config",
        lambda **kwargs: type(
            "Cfg",
            (),
            {
                "min_non_narrator_roles": 1,
                "max_narration_ratio": 0.9,
                "min_turns_for_gate": 20,
                "max_ellipsis_ratio": 0.5,
                "warn_topic_overlap_ratio": 0.1,
            },
        )(),
    )

    script = []
    for idx in range(20):
        script.append({"role": "?섎젅?댁뀡", "text": f"?뚯뒪??二쇱젣 ?섎젅?댁뀡 {idx}"})
    script.append({"role": "二쇱씤怨?", "text": "?뚯뒪??二쇱젣?먯꽌 吏꾩쭨 ??꾩슂???쒕쭩."})

    report = evaluate_script_quality(
        "?뚯뒪??二쇱젣",
        script,
        category="custom",
        mode="custom",
    )

    assert report.passed is True
