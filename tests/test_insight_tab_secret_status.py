from insight.insight_tab import _format_api_key_status


def test_format_api_key_status_hides_configured_key_value():
    api_key = "AIza" + ("c" * 32)

    status_text, status_color = _format_api_key_status(api_key)

    assert status_text == "연결됨 (값 숨김)"
    assert status_color == "#00AA00"
    assert api_key[:10] not in status_text


def test_format_api_key_status_reports_missing_key():
    status_text, status_color = _format_api_key_status("")

    assert status_text == "API 키 없음 - settings.json에 youtube_api_key 추가 필요"
    assert status_color == "#AA0000"
