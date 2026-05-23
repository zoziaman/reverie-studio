import logging

from utils import nsfw_detector
from utils.nsfw_detector import GeminiContentReviewer


def test_gemini_review_failure_redacts_api_key_in_return_and_log(monkeypatch, caplog):
    api_key = "AIza" + ("n" * 32)

    def fail_vision_content(model, prompt, image_paths):
        raise RuntimeError(f"request failed for ?key={api_key}")

    reviewer = GeminiContentReviewer.__new__(GeminiContentReviewer)
    reviewer.model = object()

    monkeypatch.setattr(nsfw_detector, "generate_vision_content", fail_vision_content)
    caplog.set_level(logging.ERROR)

    status, reason = reviewer._gemini_review("thumbnail.png", "horror")

    assert status == "ERROR"
    assert api_key not in reason
    assert api_key not in caplog.text
    assert "key=<redacted>" in reason
    assert "key=<redacted>" in caplog.text


def test_prompt_fix_failure_redacts_api_key_in_log(caplog):
    api_key = "AIza" + ("f" * 32)

    class FakeModel:
        def generate_content(self, prompt):
            raise RuntimeError(f"request failed for GEMINI_API_KEY={api_key}")

    reviewer = GeminiContentReviewer.__new__(GeminiContentReviewer)
    reviewer.model = FakeModel()

    caplog.set_level(logging.ERROR)

    fixed_prompt = reviewer.suggest_fixed_prompt("safe prompt", "unsafe reason")

    assert fixed_prompt is None
    assert api_key not in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in caplog.text
