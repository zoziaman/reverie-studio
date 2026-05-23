import logging

from core.evaluators import StoryCritic


def test_story_critic_story_bible_failure_redacts_error_and_returns_result(caplog):
    api_key = "AIza" + ("t" * 32)

    class FakeModel:
        def generate_content(self, prompt):
            raise RuntimeError(f"request failed for GEMINI_API_KEY={api_key}")

    critic = StoryCritic.__new__(StoryCritic)
    critic.threshold = 80
    critic._model = FakeModel()

    caplog.set_level(logging.ERROR)

    result = critic.evaluate_story_bible("story bible", channel_type="daily_life_toon")

    assert result.score == 0
    assert result.passed is False
    assert api_key not in result.feedback
    assert api_key not in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in result.feedback
    assert "GEMINI_API_KEY=<redacted>" in caplog.text
