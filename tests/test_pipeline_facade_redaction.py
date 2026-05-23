import logging

from facades.pipeline_facade import PipelineFacade, ProductionMode


def _secret():
    return "AIza" + ("p" * 32)


def _raise_with_secret(message):
    def _raiser(*args, **kwargs):
        raise RuntimeError(message)

    return _raiser


def _assert_redacted_error(error_text, caplog, api_key, expected_marker):
    assert api_key not in caplog.text
    assert api_key not in error_text
    assert expected_marker in caplog.text
    assert expected_marker in error_text


def test_generate_scenario_failure_redacts_log_and_returned_error(monkeypatch, caplog):
    api_key = _secret()
    facade = PipelineFacade()
    monkeypatch.setattr(
        facade,
        "_get_scenario_planner",
        _raise_with_secret(f"planner failed for ?key={api_key}"),
    )

    caplog.set_level(logging.ERROR)

    result = facade.generate_scenario("topic")

    assert result["success"] is False
    _assert_redacted_error(result["error"], caplog, api_key, "key=<redacted>")


def test_generate_video_failure_redacts_log_and_returned_error(monkeypatch, caplog):
    api_key = _secret()
    facade = PipelineFacade()
    monkeypatch.setattr(
        facade,
        "_get_media_factory",
        _raise_with_secret(f"factory failed for GEMINI_API_KEY={api_key}"),
    )

    caplog.set_level(logging.ERROR)

    result = facade.generate_video("topic", mode=ProductionMode.FULL)

    assert result.success is False
    _assert_redacted_error(result.error, caplog, api_key, "GEMINI_API_KEY=<redacted>")


def test_produce_video_with_gui_failure_redacts_log_and_returned_error(monkeypatch, caplog):
    api_key = _secret()
    facade = PipelineFacade()
    monkeypatch.setattr(
        facade,
        "_get_media_factory",
        _raise_with_secret(f"gui production failed for ?key={api_key}"),
    )

    caplog.set_level(logging.ERROR)

    result = facade.produce_video_with_gui(channel="horror")

    assert result.success is False
    _assert_redacted_error(result.error, caplog, api_key, "key=<redacted>")


def test_produce_batch_failure_redacts_log_and_returned_error(monkeypatch, caplog):
    api_key = _secret()
    facade = PipelineFacade()
    monkeypatch.setattr(
        facade,
        "_get_media_factory",
        _raise_with_secret(f"batch failed for GEMINI_API_KEY={api_key}"),
    )

    caplog.set_level(logging.ERROR)

    results = facade.produce_batch(channel="horror")

    assert len(results) == 1
    assert results[0].success is False
    _assert_redacted_error(results[0].error, caplog, api_key, "GEMINI_API_KEY=<redacted>")
