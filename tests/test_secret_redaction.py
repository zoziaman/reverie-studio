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


def test_redact_sensitive_text_hides_public_snapshot_token_patterns():
    secrets = {
        "openai": "sk-" + ("o" * 32),
        "github": "ghp_" + ("g" * 36),
        "aws": "AKIA" + ("A" * 16),
        "stripe": "sk_live_" + ("s" * 24),
        "huggingface": "hf_" + ("h" * 28),
        "npm": "npm_" + ("n" * 28),
        "oauth": "ya29." + ("y" * 28),
        "slack": "xoxb-" + ("1" * 12) + "-" + ("s" * 24),
        "discord": "https://discord.com/api/webhooks/1234567890/" + ("D" * 48),
        "telegram": "bot123456:" + ("T" * 36),
    }
    message = " ".join(f"{name}={secret}" for name, secret in secrets.items())

    redacted = redact_sensitive_text(message)

    for secret in secrets.values():
        assert secret not in redacted
    assert "<redacted-openai-key>" in redacted
    assert "<redacted-github-token>" in redacted
    assert "<redacted-aws-access-key>" in redacted
    assert "<redacted-stripe-live-key>" in redacted
    assert "<redacted-huggingface-token>" in redacted
    assert "<redacted-npm-token>" in redacted
    assert "<redacted-google-oauth-token>" in redacted
    assert "<redacted-slack-token>" in redacted
    assert "<redacted-discord-webhook>" in redacted
    assert "<redacted-telegram-bot-token>" in redacted


def test_redact_sensitive_text_hides_generic_secret_env_assignments():
    redacted = redact_sensitive_text(
        "REVERIE_SECRET_KEY=local-secret-value "
        "ADMIN_PASSWORD:super-secret "
        "CUSTOM_WEBHOOK_URL=https://example.invalid/hook"
    )

    assert "local-secret-value" not in redacted
    assert "super-secret" not in redacted
    assert "https://example.invalid/hook" not in redacted
    assert "REVERIE_SECRET_KEY=<redacted>" in redacted
    assert "ADMIN_PASSWORD:<redacted>" in redacted
    assert "CUSTOM_WEBHOOK_URL=<redacted>" in redacted


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
