from utils.feedback_loop import FeedbackLoop


def _feedback_loop_with_video(tmp_path):
    loop = FeedbackLoop(str(tmp_path), channel_type="senior")
    loop.tracking["videos"]["video-1"] = {
        "video_id": "video-1",
        "title": "Test video",
        "actions_taken": [],
    }
    return loop


def test_trigger_auto_improvement_redacts_optimizer_exception(monkeypatch, tmp_path):
    import utils.auto_optimizer as auto_optimizer

    secret = "sk-" + ("f" * 32)

    def fail_optimizer(*args, **kwargs):
        raise RuntimeError(f"optimizer init failed for OPENAI_API_KEY={secret}")

    monkeypatch.setattr(auto_optimizer, "get_auto_optimizer", fail_optimizer)

    loop = _feedback_loop_with_video(tmp_path)
    result = loop.trigger_auto_improvement("video-1")

    assert result["success"] is False
    assert secret not in result["error"]
    assert "OPENAI_API_KEY=<redacted>" in result["error"]


def test_trigger_auto_improvement_redacts_optimizer_error_result(monkeypatch, tmp_path):
    import utils.auto_optimizer as auto_optimizer

    secret = "hf_" + ("f" * 28)

    class FakeOptimizer:
        def execute_thumbnail_change(self, *args, **kwargs):
            return {
                "success": False,
                "error": f"thumbnail change failed for HF_TOKEN={secret}",
            }

    monkeypatch.setattr(auto_optimizer, "get_auto_optimizer", lambda *args, **kwargs: FakeOptimizer())

    loop = _feedback_loop_with_video(tmp_path)
    result = loop.trigger_auto_improvement("video-1")

    assert result["success"] is False
    assert secret not in result["error"]
    assert "HF_TOKEN=<redacted>" in result["error"]
