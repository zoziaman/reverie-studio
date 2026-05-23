import logging

from utils.youtube_analytics import YouTubeAnalytics
import utils.gemini_compat as gemini_compat


def test_analyze_with_gemini_failure_redacts_api_key_in_log(monkeypatch, caplog):
    api_key = "AIza" + ("y" * 32)

    class FakeModel:
        def generate_content(self, prompt):
            raise RuntimeError(f"request failed for ?key={api_key}")

    monkeypatch.setattr(gemini_compat, "configure_gemini", lambda key: True)
    monkeypatch.setattr(gemini_compat, "get_gemini_model", lambda model_name: FakeModel())

    analytics = object.__new__(YouTubeAnalytics)
    caplog.set_level(logging.ERROR)

    result = analytics.analyze_with_gemini(
        {"period": {}, "video_count": 1, "insights": []},
        api_key=api_key,
    )

    assert result is None
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text
