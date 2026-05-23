import logging

from modules_pro.scene_analyzer import SceneAnalyzer


def test_analyze_dialogue_failure_redacts_api_key_in_retry_logs(monkeypatch, caplog):
    api_key = "AIza" + ("c" * 32)

    class FakeGeminiClient:
        def generate_content(self, prompt, timeout=None):
            raise RuntimeError(f"request failed for ?key={api_key}")

    monkeypatch.setattr(SceneAnalyzer, "GEMINI_RETRY_DELAY", 0)

    analyzer = SceneAnalyzer(gemini_client=FakeGeminiClient())
    caplog.set_level(logging.WARNING)

    result = analyzer.analyze_dialogue("문이 삐걱 열렸다", speaker="narrator", index=3)

    assert result.scene_id == "scene_0003"
    assert result.dialogue_index == 3
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text


def test_parallel_batch_exception_redacts_api_key_in_log(monkeypatch, caplog):
    api_key = "AIza" + ("p" * 32)

    def fail_analysis(self, **kwargs):
        raise RuntimeError(f"parallel request failed for GEMINI_API_KEY={api_key}")

    analyzer = SceneAnalyzer(gemini_client=object())
    monkeypatch.setattr(SceneAnalyzer, "analyze_dialogue", fail_analysis)
    caplog.set_level(logging.ERROR)

    results = analyzer._analyze_batch_parallel([
        {"speaker": "narrator", "text": "문이 열렸다"}
    ])

    assert len(results) == 1
    assert results[0].scene_id == "scene_0000"
    assert api_key not in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in caplog.text


def test_chunked_batch_failure_redacts_api_key_in_fallback_log(monkeypatch, caplog):
    api_key = "AIza" + ("b" * 32)

    def fail_single_call(self, *args, **kwargs):
        raise RuntimeError(f"batch request failed for ?key={api_key}")

    def fallback_parallel(self, dialogues):
        return [self._fallback_analysis(d["text"], d["speaker"], i) for i, d in enumerate(dialogues)]

    analyzer = SceneAnalyzer(gemini_client=object())
    monkeypatch.setattr(SceneAnalyzer, "BATCH_CHUNK_SIZE", 1)
    monkeypatch.setattr(SceneAnalyzer, "_analyze_batch_single_call", fail_single_call)
    monkeypatch.setattr(SceneAnalyzer, "_analyze_batch_parallel", fallback_parallel)
    caplog.set_level(logging.WARNING)

    results = analyzer._analyze_batch_chunked([
        {"speaker": "narrator", "text": "불이 꺼졌다"}
    ])

    assert len(results) == 1
    assert results[0].scene_id == "scene_0000"
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text
