import json
import logging
from types import SimpleNamespace

import pytest


def test_create_story_llm_selects_claude_cli(monkeypatch):
    import llm.factory as factory

    sentinel = object()
    monkeypatch.setattr(factory.config, "STORY_LLM_PROVIDER", "claude_cli", raising=False)
    monkeypatch.setattr(factory.config, "STORY_LLM_MODEL", "", raising=False)
    monkeypatch.setattr(factory.config, "CLAUDE_CLI_MODEL", "sonnet", raising=False)
    monkeypatch.setattr(factory, "ClaudeCliStoryAdapter", lambda **kwargs: sentinel)

    result = factory.create_story_llm()

    assert result is sentinel


def test_create_story_llm_accepts_claude_alias(monkeypatch):
    import llm.factory as factory

    sentinel = object()
    monkeypatch.setattr(factory.config, "STORY_LLM_PROVIDER", "claude", raising=False)
    monkeypatch.setattr(factory.config, "STORY_LLM_MODEL", "", raising=False)
    monkeypatch.setattr(factory.config, "CLAUDE_CLI_MODEL", "sonnet", raising=False)
    monkeypatch.setattr(factory, "ClaudeCliStoryAdapter", lambda **kwargs: sentinel)

    result = factory.create_story_llm()

    assert result is sentinel


def test_scenario_planner_init_no_longer_requires_gemini_key(monkeypatch):
    import modules_pro.scenario_planner as planner_module

    class DummyModel:
        model_name = "claude-cli:test"

    monkeypatch.setattr(planner_module.config, "GEMINI_API_KEY", None, raising=False)
    monkeypatch.setattr(planner_module.config, "STORY_LLM_PROVIDER", "claude_cli", raising=False)
    monkeypatch.setattr(planner_module.ScenarioPlanner, "_setup_model", lambda self: DummyModel())

    planner = planner_module.ScenarioPlanner(prompt_mode=planner_module.PromptMode.CLASSIC)

    assert planner.model.model_name == "claude-cli:test"


def test_scenario_planner_uses_single_writer_for_claude(monkeypatch):
    import modules_pro.scenario_planner as planner_module

    class DummyModel:
        model_name = "claude-cli:test"

    monkeypatch.setattr(planner_module.config, "STORY_LLM_PROVIDER", "claude_cli", raising=False)
    monkeypatch.setattr(planner_module.ScenarioPlanner, "_setup_model", lambda self: DummyModel())

    planner = planner_module.ScenarioPlanner(prompt_mode=planner_module.PromptMode.CLASSIC)

    assert planner.single_writer_mode is True
    assert planner.writer1 is planner.writer2 is planner.writer3


def test_scenario_planner_keeps_multi_writer_for_gemini(monkeypatch):
    import modules_pro.scenario_planner as planner_module

    class DummyModel:
        model_name = "gemini:test"

    monkeypatch.setattr(planner_module.config, "STORY_LLM_PROVIDER", "gemini", raising=False)
    monkeypatch.setattr(planner_module.ScenarioPlanner, "_setup_model", lambda self: DummyModel())

    planner = planner_module.ScenarioPlanner(prompt_mode=planner_module.PromptMode.CLASSIC)

    assert planner.single_writer_mode is False
    assert planner.writer1 is not planner.writer2
    assert planner.writer2 is not planner.writer3


def test_claude_cli_adapter_builds_expected_command(monkeypatch):
    import llm.claude_cli_adapter as adapter_module

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"script_list":[]}', stderr="")

    monkeypatch.setattr(adapter_module.shutil, "which", lambda value: f"C:/bin/{value}.exe")
    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    monkeypatch.setattr(adapter_module.config, "STORY_LLM_TIMEOUT_SEC", 45, raising=False)
    monkeypatch.setattr(adapter_module.config, "CLAUDE_CLI_SETTING_SOURCES", "project,local", raising=False)
    monkeypatch.setattr(adapter_module.config, "CLAUDE_CLI_NO_SESSION_PERSISTENCE", True, raising=False)

    adapter = adapter_module.ClaudeCliStoryAdapter(
        cli_path="claude",
        model_name="sonnet",
        extra_args="--max-turns 1",
    )
    response = adapter.generate_content("hello")

    assert response.text == '{"script_list":[]}'
    cmd, kwargs = calls[0]
    assert cmd[:6] == [
        "C:/bin/claude.exe",
        "-p",
        "--output-format",
        "text",
        "--model",
        "sonnet",
    ]
    assert cmd[6:] == [
        "--setting-sources",
        "project,local",
        "--no-session-persistence",
        "--max-turns",
        "1",
    ]
    assert kwargs["input"] == "hello"
    assert kwargs["timeout"] == 45


def test_claude_cli_adapter_retries_without_newer_flags(monkeypatch):
    import llm.claude_cli_adapter as adapter_module

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if len(calls) == 1:
            return SimpleNamespace(returncode=1, stdout="", stderr="error: unknown option '--setting-sources'")
        return SimpleNamespace(returncode=0, stdout='{"script_list":[]}', stderr="")

    monkeypatch.setattr(adapter_module.shutil, "which", lambda value: f"C:/bin/{value}.exe")
    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    monkeypatch.setattr(adapter_module.config, "CLAUDE_CLI_SETTING_SOURCES", "project,local", raising=False)
    monkeypatch.setattr(adapter_module.config, "CLAUDE_CLI_NO_SESSION_PERSISTENCE", True, raising=False)

    adapter = adapter_module.ClaudeCliStoryAdapter(cli_path="claude", model_name="sonnet")

    response = adapter.generate_content("hello")

    assert response.text == '{"script_list":[]}'
    assert calls[0][6:] == ["--setting-sources", "project,local", "--no-session-persistence"]
    assert calls[1][6:] == []


def test_claude_cli_adapter_injects_sampling_hint_from_generation_config(monkeypatch):
    import llm.claude_cli_adapter as adapter_module

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(kwargs["input"])
        return SimpleNamespace(returncode=0, stdout='{"script_list":[]}', stderr="")

    monkeypatch.setattr(adapter_module.shutil, "which", lambda value: f"C:/bin/{value}.exe")
    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)

    adapter = adapter_module.ClaudeCliStoryAdapter(cli_path="claude", model_name="sonnet")
    adapter.generate_content(
        "hello",
        generation_config={"temperature": 0.95, "top_p": 0.95, "top_k": 80},
    )

    assert "[Sampling hint]" in calls[0]
    assert "more novelty" in calls[0]
    assert "broader spread" in calls[0]


def test_claude_cli_adapter_retries_once_with_longer_timeout_after_timeout(monkeypatch):
    import llm.claude_cli_adapter as adapter_module

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(kwargs["timeout"])
        if len(calls) == 1:
            raise adapter_module.subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])
        return SimpleNamespace(returncode=0, stdout='{"script_list":[]}', stderr="")

    monkeypatch.setattr(adapter_module.shutil, "which", lambda value: f"C:/bin/{value}.exe")
    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    monkeypatch.setattr(adapter_module.config, "STORY_LLM_TIMEOUT_SEC", 120, raising=False)

    adapter = adapter_module.ClaudeCliStoryAdapter(cli_path="claude", model_name="sonnet")

    response = adapter.generate_content("hello")

    assert response.text == '{"script_list":[]}'
    assert calls == [120, 300]


def test_claude_cli_adapter_rejects_empty_output(monkeypatch):
    import llm.claude_cli_adapter as adapter_module

    monkeypatch.setattr(adapter_module.shutil, "which", lambda value: f"C:/bin/{value}.exe")
    monkeypatch.setattr(
        adapter_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="   ", stderr=""),
    )

    adapter = adapter_module.ClaudeCliStoryAdapter(cli_path="claude", model_name="sonnet")

    with pytest.raises(RuntimeError, match="empty response"):
        adapter.generate_content("hello")


def test_pack_content_default_turn_range_was_widened():
    from config.pack_config import PackContent

    content = PackContent()

    assert content.min_turns == 45
    assert content.max_turns == 70


def test_resolve_story_timeout_is_more_generous_for_claude_cli(monkeypatch):
    import modules_pro.script_writers as writers_module

    monkeypatch.setattr(writers_module.config, "STORY_LLM_PROVIDER", "claude_cli", raising=False)
    monkeypatch.setattr(writers_module.config, "STORY_LLM_TIMEOUT_SEC", 600, raising=False)

    assert writers_module._resolve_story_timeout(75) == 750


def test_scenario_planner_compact_context_respects_custom_turn_budget():
    from modules_pro.scenario_planner import ScenarioPlanner

    planner = ScenarioPlanner.__new__(ScenarioPlanner)
    script = [
        {
            "role": "주인공" if i % 2 == 0 else "조력자",
            "text": f"테스트 대사 {i}",
            "emotion": "scared" if i in {4, 11, 18, 25, 32} else "calm",
        }
        for i in range(1, 41)
    ]

    context = planner._format_script_as_context(
        script,
        compact=True,
        max_key_turns=12,
        edge_turns=4,
    )
    preserved_turns = [
        line for line in context.splitlines()
        if line.startswith("[") and "] (" in line
    ]

    assert len(preserved_turns) <= 12
    assert "[1] (calm) 조력자: 테스트 대사 1" in context
    assert "[40] (calm) 주인공: 테스트 대사 40" in context


def test_enhanced_script_writer_accepts_exact_short_test_turns(monkeypatch):
    import modules_pro.script_writers as writers_module

    class DummyModel:
        def generate_content(self, *args, **kwargs):
            turns = [
                {
                    "role": "민혁",
                    "voice_type": "man",
                    "text": f"테스트 대사 {idx}",
                    "emotion": "calm",
                    "sfx_tag": "",
                }
                for idx in range(1, 18)
            ]
            return SimpleNamespace(text=json.dumps({"script_list": turns}, ensure_ascii=False))

    monkeypatch.setattr(writers_module, "PACK_CONFIG_AVAILABLE", False, raising=False)
    monkeypatch.setattr(writers_module, "safe_print", lambda *args, **kwargs: None, raising=False)

    writer = writers_module.EnhancedScriptWriter(DummyModel(), "작가1(빌드업)")
    result = writer.write_part(
        topic="테스트 공포",
        category="horror",
        mode="horror",
        target_turns=17,
        story_bible="간단한 바이블",
        prev_summary="없음(시작)",
        instruction="도입부를 쓴다",
        forbidden="반복 금지",
    )

    assert len(result) == 17


def test_enhanced_script_writer_recovers_short_claude_output(monkeypatch):
    import modules_pro.script_writers as writers_module

    class DummyModel:
        def __init__(self):
            self.calls = 0

        def generate_content(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                turn_range = range(1, 27)
            else:
                turn_range = range(25, 38)

            turns = [
                {
                    "role": "민수",
                    "voice_type": "young_man",
                    "text": f"테스트 대사 {idx}",
                    "emotion": "calm",
                    "sfx_tag": "",
                }
                for idx in turn_range
            ]
            return SimpleNamespace(text=json.dumps({"script_list": turns}, ensure_ascii=False))

    model = DummyModel()
    monkeypatch.setattr(writers_module.config, "STORY_LLM_PROVIDER", "claude_cli", raising=False)
    monkeypatch.setattr(writers_module, "PACK_CONFIG_AVAILABLE", False, raising=False)
    monkeypatch.setattr(writers_module, "safe_print", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(writers_module.ScriptWriter, "_emotion_gate", staticmethod(lambda *args, **kwargs: True))

    writer = writers_module.EnhancedScriptWriter(model, "작가1(빌드업)")
    result = writer.write_part(
        topic="테스트 주제",
        category="drama",
        mode="drama",
        target_turns=37,
        story_bible="간단한 스토리 바이블",
        prev_summary="없음",
        instruction="장면을 이어가라",
        forbidden="반복 금지",
    )

    assert len(result) == 37
    assert result[-1]["text"] == "테스트 대사 37"
    assert model.calls == 2


def test_enhanced_script_writer_prefers_local_emotion_force_correct_before_retry(monkeypatch):
    import modules_pro.script_writers as writers_module

    class DummyModel:
        def __init__(self):
            self.calls = 0

        def generate_content(self, *args, **kwargs):
            self.calls += 1
            turns = [
                {
                    "role": "민수",
                    "voice_type": "young_man",
                    "text": f"테스트 대사 {idx}",
                    "emotion": "calm",
                    "sfx_tag": "",
                }
                for idx in range(1, 38)
            ]
            return SimpleNamespace(text=json.dumps({"script_list": turns}, ensure_ascii=False))

    def fake_gate(script, *_args, **_kwargs):
        return any(turn.get("emotion") == "scared" for turn in script)

    def fake_force_correct(script, *_args, **_kwargs):
        corrected = [dict(turn) for turn in script]
        corrected[0]["emotion"] = "scared"
        return corrected

    model = DummyModel()
    monkeypatch.setattr(writers_module.config, "STORY_LLM_PROVIDER", "claude_cli", raising=False)
    monkeypatch.setattr(writers_module, "PACK_CONFIG_AVAILABLE", False, raising=False)
    monkeypatch.setattr(writers_module, "safe_print", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(writers_module.EnhancedScriptWriter, "_emotion_gate", staticmethod(fake_gate))
    monkeypatch.setattr(writers_module.EnhancedScriptWriter, "_emotion_force_correct", staticmethod(fake_force_correct))

    writer = writers_module.EnhancedScriptWriter(model, "작가1(빌드업)")
    result = writer.write_part(
        topic="테스트 주제",
        category="drama",
        mode="drama",
        target_turns=37,
        story_bible="간단한 스토리 바이블",
        prev_summary="없음",
        instruction="장면을 이어가라",
        forbidden="반복 금지",
    )

    assert len(result) == 37
    assert result[0]["emotion"] == "scared"
    assert model.calls == 1


def test_normalize_script_skips_missing_pack_warning_when_name_is_inferred(monkeypatch, caplog):
    import modules_pro.script_writers as writers_module

    monkeypatch.setattr(writers_module, "PACK_CONFIG_AVAILABLE", True, raising=False)
    monkeypatch.setattr(writers_module.ACTIVE_PACK, "is_loaded", True, raising=False)
    monkeypatch.setattr(writers_module.ACTIVE_PACK, "allowed_emotions", ["calm"], raising=False)
    monkeypatch.setattr(writers_module, "get_character_config", lambda: {"narrator": "narrator"}, raising=False)

    with caplog.at_level(logging.WARNING, logger="script_writers"):
        result = writers_module.ScriptWriter._normalize_script(
            [{"role": "민지", "text": "괜찮아요", "emotion": "calm", "voice_type": ""}]
        )

    assert result[0]["voice_type"] != "narrator"
    assert not any("character_config에 누락된 캐릭터" in record.message for record in caplog.records)
