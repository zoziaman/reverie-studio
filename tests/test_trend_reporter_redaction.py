import logging

from insight.trend_reporter import TrendReporter


def test_generate_ai_insights_redacts_gemini_failure_log(caplog):
    api_key = "AIza" + ("q" * 32)

    class FakeGeminiModel:
        def generate_content(self, prompt):
            raise RuntimeError(f"request failed for GEMINI_API_KEY={api_key}")

    reporter = TrendReporter.__new__(TrendReporter)
    reporter.gemini_model = FakeGeminiModel()

    caplog.set_level(logging.WARNING)

    summary, recommendations = reporter._generate_ai_insights([], [], [], [])

    assert summary
    assert recommendations
    assert api_key not in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in caplog.text
