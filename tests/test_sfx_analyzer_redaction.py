import logging
import threading

from core.sfx_analyzer import SFXAnalyzer, ScriptSegment


def test_sfx_ai_failure_log_redacts_gemini_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("m" * 32)

    class FakeModel:
        def generate_content(self, prompt):
            raise RuntimeError(f"request failed for ?key={api_key}")

    analyzer = SFXAnalyzer.__new__(SFXAnalyzer)
    analyzer.model = FakeModel()
    analyzer._lock = threading.Lock()

    monkeypatch.setattr(analyzer, "_keyword_based_analysis", lambda segments, category: [])
    caplog.set_level(logging.ERROR)

    cues = analyzer._ai_analyze_batch(
        [ScriptSegment(index=0, text="test", start_ms=0, end_ms=1000)],
        category="horror",
        intensity="medium",
    )

    assert cues == []
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text
