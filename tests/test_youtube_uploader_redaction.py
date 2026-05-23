import logging
from unittest.mock import MagicMock

from utils.youtube_uploader import YouTubeUploader, _load_encrypted_pickle


def test_load_encrypted_pickle_failure_redacts_api_key(monkeypatch, tmp_path, caplog):
    api_key = "AIza" + ("u" * 32)
    token_path = tmp_path / "youtube_token.pickle"
    token_path.write_bytes(b"not a pickle")

    def fail_load(_handle):
        raise RuntimeError(f"token decode failed for ?key={api_key}")

    monkeypatch.setattr("utils.youtube_uploader.pickle.load", fail_load)

    caplog.set_level(logging.ERROR)

    result = _load_encrypted_pickle(str(token_path))

    assert result is None
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text


def test_update_thumbnail_failure_redacts_api_key_in_log_and_return(monkeypatch, tmp_path, caplog):
    api_key = "AIza" + ("t" * 32)
    thumbnail_path = tmp_path / "thumbnail.jpg"
    thumbnail_path.write_bytes(b"fake jpg")

    class FailingRequest:
        def execute(self):
            raise RuntimeError(f"thumbnail update failed for GEMINI_API_KEY={api_key}")

    class FakeThumbnails:
        def set(self, **kwargs):
            return FailingRequest()

    class FakeService:
        def thumbnails(self):
            return FakeThumbnails()

    uploader = YouTubeUploader(channel_type="horror")
    uploader.service = FakeService()

    monkeypatch.setattr("utils.youtube_uploader.MediaFileUpload", lambda *args, **kwargs: MagicMock())
    caplog.set_level(logging.ERROR)

    result = uploader.update_thumbnail("video123", str(thumbnail_path))

    assert result["success"] is False
    assert api_key not in caplog.text
    assert api_key not in result["error"]
    assert "GEMINI_API_KEY=<redacted>" in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in result["error"]


def test_update_video_metadata_failure_redacts_api_key_in_log_and_return(monkeypatch, caplog):
    api_key = "AIza" + ("m" * 32)

    class FailingRequest:
        def execute(self):
            raise RuntimeError(f"metadata update failed for ?key={api_key}")

    class FakeVideos:
        def update(self, **kwargs):
            return FailingRequest()

    class FakeService:
        def videos(self):
            return FakeVideos()

    uploader = YouTubeUploader(channel_type="horror")
    uploader.service = FakeService()
    monkeypatch.setattr(
        uploader,
        "get_video_info",
        lambda video_id: {
            "video_id": video_id,
            "title": "old title",
            "description": "old description",
        },
    )
    caplog.set_level(logging.ERROR)

    result = uploader.update_video_metadata("video123", title="new title")

    assert result["success"] is False
    assert api_key not in caplog.text
    assert api_key not in result["error"]
    assert "key=<redacted>" in caplog.text
    assert "key=<redacted>" in result["error"]
