import logging
import threading

from core.translator import ContentTranslator


def _translator_with_model(model):
    translator = object.__new__(ContentTranslator)
    translator._model = model
    translator._api_lock = threading.Lock()
    return translator


def test_translate_scenario_failure_redacts_api_key_in_return_and_log(caplog):
    api_key = "AIza" + ("s" * 32)

    class FakeModel:
        def generate_content(self, prompt):
            raise RuntimeError(f"request failed for ?key={api_key}")

    translator = _translator_with_model(FakeModel())
    caplog.set_level(logging.ERROR)

    result = translator.translate_scenario(
        {"title": "원본", "scenes": [{"text": "대사"}]},
        target_language="en",
    )

    assert result.success is False
    assert api_key not in result.error_message
    assert api_key not in caplog.text
    assert "key=<redacted>" in result.error_message
    assert "key=<redacted>" in caplog.text


def test_translate_metadata_failure_redacts_api_key_in_return_and_log(caplog):
    api_key = "AIza" + ("m" * 32)

    class FakeModel:
        def generate_content(self, prompt):
            raise RuntimeError(f"request failed for GEMINI_API_KEY={api_key}")

    translator = _translator_with_model(FakeModel())
    caplog.set_level(logging.ERROR)

    result = translator.translate_metadata(
        title="원본",
        description="설명",
        tags=["태그"],
        target_language="en",
    )

    assert result.success is False
    assert api_key not in result.error_message
    assert api_key not in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in result.error_message
    assert "GEMINI_API_KEY=<redacted>" in caplog.text
