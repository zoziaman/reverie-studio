import logging
import json

from modules_pro import script_writers
from modules_pro.script_writers import EnhancedScriptWriter, ScriptWriter


def _call_hybrid(writer):
    return writer._write_part_hybrid(
        topic="topic",
        category="horror",
        mode="horror",
        target_turns=10,
        story_bible="bible",
        prev_summary="",
        instruction="write",
        forbidden="",
        base_prompt="prompt",
        gen_config=object(),
    )


def test_hybrid_gemini_init_failure_redacts_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("w" * 32)

    def fail_create_story_llm(provider):
        raise RuntimeError(f"create failed for GEMINI_API_KEY={api_key}")

    monkeypatch.setattr("llm.factory.create_story_llm", fail_create_story_llm)
    writer = ScriptWriter(model=object(), role_name="Writer")
    caplog.set_level(logging.WARNING)

    result = _call_hybrid(writer)

    assert result is None
    assert api_key not in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in caplog.text


def test_hybrid_gemini_draft_failure_redacts_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("d" * 32)

    class FakeGeminiModel:
        def generate_content(self, prompt, timeout=None, generation_config=None):
            raise RuntimeError(f"draft failed for ?key={api_key}")

    monkeypatch.setattr("llm.factory.create_story_llm", lambda provider: FakeGeminiModel())
    monkeypatch.setattr(script_writers.time, "sleep", lambda seconds: None)
    writer = ScriptWriter(model=object(), role_name="Writer")
    caplog.set_level(logging.WARNING)

    result = _call_hybrid(writer)

    assert result is None
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text


def test_hybrid_rewrite_failure_redacts_api_key_and_returns_draft(monkeypatch, caplog):
    api_key = "AIza" + ("r" * 32)
    draft = [
        {"role": "narrator", "voice_type": "narrator", "text": f"turn {i}", "emotion": "calm"}
        for i in range(10)
    ]

    class FakeGeminiModel:
        def generate_content(self, prompt, timeout=None, generation_config=None):
            return type("Response", (), {"text": json.dumps({"script_list": draft}, ensure_ascii=False)})()

    class FakeRewriteModel:
        def generate_content(self, prompt, timeout=None, generation_config=None):
            raise RuntimeError(f"rewrite failed for GEMINI_API_KEY={api_key}")

    monkeypatch.setattr("llm.factory.create_story_llm", lambda provider: FakeGeminiModel())
    monkeypatch.setattr(script_writers.time, "sleep", lambda seconds: None)
    writer = ScriptWriter(model=FakeRewriteModel(), role_name="Writer")
    caplog.set_level(logging.WARNING)

    result = _call_hybrid(writer)

    assert result == draft
    assert api_key not in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in caplog.text


def test_basic_write_part_api_failure_redacts_api_key_in_log(monkeypatch, caplog):
    api_key = "AIza" + ("b" * 32)

    class FakeModel:
        def generate_content(self, prompt, timeout=None, generation_config=None):
            raise RuntimeError(f"basic write failed for ?key={api_key}")

    monkeypatch.setattr(script_writers, "_get_story_provider", lambda: "gemini")
    monkeypatch.setattr(script_writers, "PACK_CONFIG_AVAILABLE", False)
    monkeypatch.setattr(script_writers.time, "sleep", lambda seconds: None)
    writer = ScriptWriter(model=FakeModel(), role_name="Writer")
    caplog.set_level(logging.WARNING)

    result = writer.write_part(
        topic="topic",
        category="horror",
        mode="horror",
        target_turns=3,
        story_bible="bible",
        prev_summary="",
        instruction="write",
        forbidden="",
        attempt_limit=1,
    )

    assert result
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text


def test_enhanced_write_part_api_failure_redacts_api_key_in_log_and_console(monkeypatch, caplog, capsys):
    api_key = "AIza" + ("e" * 32)

    class FakeModel:
        def generate_content(self, prompt, timeout=None, generation_config=None):
            raise RuntimeError(f"enhanced write failed for GEMINI_API_KEY={api_key}")

    monkeypatch.setattr(script_writers, "_get_story_provider", lambda: "gemini")
    monkeypatch.setattr(script_writers, "PACK_CONFIG_AVAILABLE", False)
    monkeypatch.setattr(script_writers.time, "sleep", lambda seconds: None)
    writer = EnhancedScriptWriter(model=FakeModel(), role_name="Writer")
    caplog.set_level(logging.WARNING)

    result = writer.write_part(
        topic="topic",
        category="horror",
        mode="horror",
        target_turns=3,
        story_bible="bible",
        prev_summary="",
        instruction="write",
        forbidden="",
        attempt_limit=1,
    )

    stdout = capsys.readouterr().out
    assert result
    assert api_key not in caplog.text
    assert api_key not in stdout
    assert "GEMINI_API_KEY=<redacted>" in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in stdout
