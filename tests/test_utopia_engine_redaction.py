from utils.utopia_engine import UtopiaEngine, UtopiaState


def test_generate_video_now_redacts_secret_in_error_state_and_logs(monkeypatch, tmp_path):
    secret = "sk-" + ("z" * 32)
    engine = UtopiaEngine(
        str(tmp_path),
        channel_type="senior",
        media_factory_getter=lambda: object(),
    )
    engine.config["generation"]["use_personalization"] = False
    log_messages = []
    state_changes = []
    engine.on_log = log_messages.append
    engine.on_state_change = lambda state, reason: state_changes.append((state, reason))

    def failing_generation(*args, **kwargs):
        raise RuntimeError(f"generation failed for OPENAI_API_KEY={secret}")

    monkeypatch.setattr(engine, "_execute_generation", failing_generation)

    result = engine.generate_video_now(
        topic="public template",
        title="Public template",
        run_async=False,
    )

    assert result["success"] is False
    assert result["error"]
    assert secret not in result["error"]
    assert "OPENAI_API_KEY=<redacted>" in result["error"]
    assert engine._current_state is UtopiaState.ERROR
    assert state_changes[-1][0] is UtopiaState.ERROR
    assert secret not in state_changes[-1][1]
    assert secret not in "\n".join(log_messages)


def test_lazy_prompt_optimizer_load_redacts_secret_in_logs(monkeypatch, tmp_path, caplog):
    import utils.prompt_optimizer as prompt_optimizer

    secret = "sk-" + ("l" * 32)

    def failing_prompt_optimizer(*args, **kwargs):
        raise RuntimeError(f"optimizer load failed for OPENAI_API_KEY={secret}")

    monkeypatch.setattr(prompt_optimizer, "get_prompt_optimizer", failing_prompt_optimizer)
    caplog.set_level("ERROR")
    engine = UtopiaEngine(
        str(tmp_path),
        channel_type="senior",
        media_factory_getter=lambda: object(),
    )

    assert engine.prompt_optimizer is None

    assert secret not in caplog.text
    assert "OPENAI_API_KEY=<redacted>" in caplog.text
