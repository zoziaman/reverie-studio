from utils.auto_optimizer import AutoOptimizer


def test_run_optimization_cycle_redacts_secret_in_errors(monkeypatch, tmp_path):
    import utils.youtube_analytics as youtube_analytics

    secret = "sk-" + ("a" * 32)

    class FailingAnalytics:
        def __init__(self, *args, **kwargs):
            raise RuntimeError(f"analytics init failed for OPENAI_API_KEY={secret}")

    monkeypatch.setattr(youtube_analytics, "YouTubeAnalytics", FailingAnalytics)

    optimizer = AutoOptimizer(str(tmp_path))
    result = optimizer.run_optimization_cycle()

    assert secret not in " ".join(result["errors"])
    assert any("OPENAI_API_KEY=<redacted>" in error for error in result["errors"])


def test_execute_thumbnail_change_redacts_secret_in_error(monkeypatch, tmp_path):
    import utils.youtube_uploader as youtube_uploader

    secret = "hf_" + ("t" * 28)
    thumb_path = tmp_path / "thumb.jpg"
    thumb_path.write_bytes(b"fake")

    class FailingUploader:
        def __init__(self, *args, **kwargs):
            pass

        def update_thumbnail(self, *args, **kwargs):
            raise RuntimeError(f"thumbnail upload failed for HF_TOKEN={secret}")

    monkeypatch.setattr(youtube_uploader, "YouTubeUploader", FailingUploader)

    optimizer = AutoOptimizer(str(tmp_path))
    optimizer.on_thumbnail_regenerate = lambda video_id, title: str(thumb_path)

    result = optimizer._execute_thumbnail_change("video-1", "Title", "low CTR")

    assert result["success"] is False
    assert secret not in result["error"]
    assert "HF_TOKEN=<redacted>" in result["error"]
