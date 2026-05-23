from insight.trend_collector import TrendCollector


def test_collect_trending_redacts_secret_in_errors(tmp_path):
    secret = "sk-" + ("c" * 32)

    class FailingVideos:
        def list(self, *args, **kwargs):
            raise RuntimeError(f"youtube request failed for OPENAI_API_KEY={secret}")

    class FakeYoutube:
        def videos(self):
            return FailingVideos()

    collector = TrendCollector.__new__(TrendCollector)
    collector.youtube = FakeYoutube()
    collector.data_dir = tmp_path

    result = collector.collect_trending(country_code="KR", save_to_file=False)

    assert result.errors
    assert secret not in " ".join(result.errors)
    assert any("OPENAI_API_KEY=<redacted>" in error for error in result.errors)


def test_collect_multiple_countries_redacts_secret_in_errors(monkeypatch):
    secret = "hf_" + ("c" * 28)

    collector = TrendCollector.__new__(TrendCollector)

    def fail_collect(*args, **kwargs):
        raise RuntimeError(f"multi country failed for HF_TOKEN={secret}")

    monkeypatch.setattr(collector, "collect_trending", fail_collect)

    results = collector.collect_multiple_countries(["KR"], max_results_per_country=1)

    errors = results["KR"].errors
    assert errors
    assert secret not in " ".join(errors)
    assert any("HF_TOKEN=<redacted>" in error for error in errors)


def test_collect_faceless_friendly_redacts_secret_in_errors(monkeypatch):
    secret = "ya29." + ("c" * 28)

    collector = TrendCollector.__new__(TrendCollector)

    def fail_collect(*args, **kwargs):
        raise RuntimeError(f"faceless category failed for GOOGLE_TOKEN={secret}")

    monkeypatch.setattr(collector, "collect_trending", fail_collect)
    monkeypatch.setattr(collector, "_save_result", lambda result: None)

    result = collector.collect_faceless_friendly(country_code="KR", max_results=4)

    assert result.errors
    assert secret not in " ".join(result.errors)
    assert any("GOOGLE_TOKEN=<redacted>" in error for error in result.errors)
