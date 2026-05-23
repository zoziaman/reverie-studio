from datetime import datetime


def test_scheduler_defaults_reduce_mass_upload_cadence(tmp_path):
    from utils.upload_scheduler import UploadScheduler

    scheduler = UploadScheduler(str(tmp_path), channel_type="senior")

    assert scheduler.config["daily_upload_limit"] <= 2
    assert scheduler.config["min_gap_hours"] >= 8


def test_scheduler_queue_stores_policy_metadata_defaults(tmp_path):
    from utils.upload_scheduler import UploadScheduler

    video_path = tmp_path / "video.mp4"
    thumbnail_path = tmp_path / "thumb.jpg"
    video_path.write_bytes(b"fake mp4")
    thumbnail_path.write_bytes(b"fake jpg")

    scheduler = UploadScheduler(str(tmp_path), channel_type="senior")
    item = scheduler.add_to_queue(
        video_path=str(video_path),
        thumbnail_path=str(thumbnail_path),
        title="반전 드라마",
        description="창작 드라마입니다.",
        scheduled_time=datetime(2026, 4, 28, 18, 0, 0),
        metadata={"channel_mode": "makjang"},
    )

    assert item["metadata"]["contains_synthetic_media"] is True
    assert item["metadata"]["verified_true_story"] is False
    assert item["metadata"]["channel_mode"] == "makjang"


def test_scheduler_redacts_secret_in_upload_failure_state_and_callback(monkeypatch, tmp_path):
    from utils.upload_scheduler import UploadScheduler
    import utils.youtube_uploader as youtube_uploader

    secret = "sk-" + ("u" * 32)
    video_path = tmp_path / "video.mp4"
    thumbnail_path = tmp_path / "thumb.jpg"
    video_path.write_bytes(b"fake mp4")
    thumbnail_path.write_bytes(b"fake jpg")

    class FailingUploader:
        def __init__(self, *args, **kwargs):
            pass

        def authenticate(self):
            return True

        def upload_video(self, *args, **kwargs):
            raise RuntimeError(f"upload failed for YOUTUBE_TOKEN={secret}")

    monkeypatch.setattr(youtube_uploader, "YouTubeUploader", FailingUploader)

    scheduler = UploadScheduler(str(tmp_path), channel_type="senior")
    scheduler.config["max_retries"] = 1
    failure_callbacks = []
    logs = []
    scheduler.on_upload_fail = lambda item, error: failure_callbacks.append((item, error))
    scheduler.on_log = logs.append

    item = scheduler.add_to_queue(
        video_path=str(video_path),
        thumbnail_path=str(thumbnail_path),
        title="Upload failure case",
        description="Policy-safe dry run",
    )

    assert scheduler._execute_upload(item) is False

    assert secret not in item["error"]
    assert "YOUTUBE_TOKEN=<redacted>" in item["error"]
    assert failure_callbacks
    assert secret not in failure_callbacks[0][1]
    assert "YOUTUBE_TOKEN=<redacted>" in failure_callbacks[0][1]
    assert secret not in "\n".join(logs)


def test_scheduler_redacts_secret_in_feedback_registration_error(monkeypatch, tmp_path):
    from utils.upload_scheduler import UploadScheduler
    import utils.feedback_loop as feedback_loop

    secret = "hf_" + ("f" * 28)

    def failing_feedback_loop(*args, **kwargs):
        raise RuntimeError(f"feedback registration failed for HF_TOKEN={secret}")

    monkeypatch.setattr(feedback_loop, "get_feedback_loop", failing_feedback_loop)

    scheduler = UploadScheduler(str(tmp_path), channel_type="senior")
    logs = []
    scheduler.on_log = logs.append
    item = {"title": "Feedback failure case"}

    assert scheduler._register_to_feedback_loop("video-1", item) is False

    assert item["feedback_registered"] is False
    assert secret not in item["feedback_error"]
    assert "HF_TOKEN=<redacted>" in item["feedback_error"]
    assert secret not in "\n".join(logs)
