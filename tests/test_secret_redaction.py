import logging

import utils.gemini_compat as gemini_compat
from utils.secret_redaction import redact_sensitive_text


def test_redact_sensitive_text_hides_gemini_url_query_key():
    api_key = "AIza" + ("g" * 32)
    message = (
        "403 Client Error: Forbidden for url: "
        f"https://generativelanguage.googleapis.com/v1beta/models/model:generateContent?key={api_key}&alt=json"
    )

    redacted = redact_sensitive_text(message)

    assert api_key not in redacted
    assert "key=<redacted>" in redacted
    assert "&alt=json" in redacted


def test_redact_sensitive_text_hides_google_api_key_outside_url():
    api_key = "AIza" + ("h" * 32)

    redacted = redact_sensitive_text(f"configuration failed for key {api_key}")

    assert api_key not in redacted
    assert "<redacted-google-api-key>" in redacted


def test_redact_sensitive_text_hides_environment_assignment_values():
    api_key = "AIza" + ("i" * 32)

    redacted = redact_sensitive_text(f"GEMINI_API_KEY={api_key}")

    assert api_key not in redacted
    assert redacted == "GEMINI_API_KEY=<redacted>"


def test_gemini_configure_logs_redacted_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("k" * 32)

    class FakeGenAI:
        __version__ = "test"

        class Client:
            def __init__(self, api_key=None):
                raise RuntimeError(f"request failed for ?key={api_key}")

    monkeypatch.setattr(gemini_compat, "GEMINI_AVAILABLE", True)
    monkeypatch.setattr(gemini_compat, "genai_new", FakeGenAI, raising=False)
    caplog.set_level(logging.ERROR)

    assert gemini_compat.configure_gemini(api_key) is False

    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text
