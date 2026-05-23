import logging
import threading

from PIL import Image

from utils import thumbnail_reviewer
from utils.thumbnail_reviewer import ThumbnailReviewer


def test_review_thumbnail_failure_redacts_api_key_in_log(monkeypatch, tmp_path, caplog):
    api_key = "AIza" + ("r" * 32)
    thumbnail_path = tmp_path / "thumbnail.png"
    Image.new("RGB", (1280, 720), color=(20, 20, 20)).save(thumbnail_path)

    def fail_vision_content(model, prompt, image_paths):
        raise RuntimeError(f"request failed for ?key={api_key}")

    reviewer = ThumbnailReviewer.__new__(ThumbnailReviewer)
    reviewer.model = object()
    reviewer.vision_available = True
    reviewer._api_lock = threading.Lock()

    monkeypatch.setattr(thumbnail_reviewer, "generate_vision_content", fail_vision_content)
    caplog.set_level(logging.ERROR)

    result = reviewer.review_thumbnail(str(thumbnail_path), title="test")

    assert result["review_text"] == "Fallback review (Gemini unavailable)"
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text


def test_fallback_review_load_failure_redacts_api_key_in_return(monkeypatch):
    api_key = "AIza" + ("i" * 32)

    def fail_open(path):
        raise RuntimeError(f"image load failed for GEMINI_API_KEY={api_key}")

    reviewer = ThumbnailReviewer.__new__(ThumbnailReviewer)

    monkeypatch.setattr(Image, "open", fail_open)

    result = reviewer._fallback_review("thumbnail.png")

    assert result["passed"] is False
    assert api_key not in result["issues"][0]
    assert api_key not in result["review_text"]
    assert "GEMINI_API_KEY=<redacted>" in result["issues"][0]
    assert "GEMINI_API_KEY=<redacted>" in result["review_text"]
