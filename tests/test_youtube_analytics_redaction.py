import logging

from utils.youtube_analytics import YouTubeAnalytics, _analytics_load_pickle
import utils.gemini_compat as gemini_compat


def test_analytics_load_pickle_failure_redacts_api_key(monkeypatch, tmp_path, caplog):
    api_key = "AIza" + ("a" * 32)
    token_path = tmp_path / "youtube_token.pickle"
    token_path.write_bytes(b"not a pickle")

    def fail_load(_handle):
        raise RuntimeError(f"token decode failed for ?key={api_key}")

    monkeypatch.setattr("utils.youtube_analytics.pickle.load", fail_load)
    caplog.set_level(logging.ERROR)

    result = _analytics_load_pickle(str(token_path))

    assert result is None
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text


def test_channel_stats_failure_redacts_api_key_in_log(caplog):
    api_key = "AIza" + ("c" * 32)

    class FailingRequest:
        def execute(self):
            raise RuntimeError(f"channels failed for GEMINI_API_KEY={api_key}")

    class FakeChannels:
        def list(self, **kwargs):
            return FailingRequest()

    class FakeService:
        def channels(self):
            return FakeChannels()

    analytics = object.__new__(YouTubeAnalytics)
    analytics.service = FakeService()
    caplog.set_level(logging.ERROR)

    result = analytics.get_channel_stats()

    assert result is None
    assert api_key not in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in caplog.text


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
