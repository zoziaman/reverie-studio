from utils.prompt_optimizer import PromptOptimizer


def test_collect_and_analyze_redacts_secret_in_errors(monkeypatch, tmp_path):
    import utils.youtube_analytics as youtube_analytics

    secret = "sk-" + ("p" * 32)

    class FailingAnalytics:
        def __init__(self, *args, **kwargs):
            raise RuntimeError(f"analytics init failed for OPENAI_API_KEY={secret}")

    monkeypatch.setattr(youtube_analytics, "YouTubeAnalytics", FailingAnalytics)

    optimizer = PromptOptimizer(str(tmp_path))
    result = optimizer.collect_and_analyze()

    assert result["errors"]
    assert secret not in " ".join(result["errors"])
    assert any("OPENAI_API_KEY=<redacted>" in error for error in result["errors"])
