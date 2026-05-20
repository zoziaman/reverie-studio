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
