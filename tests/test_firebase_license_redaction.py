import logging

from utils.firebase_license import CloudFunctionsClient, _redact_license_key_for_log


def test_redact_license_key_for_log_hides_middle_segments():
    assert _redact_license_key_for_log("TEST-1234-5678-ABCD") == "TEST-****-****-ABCD"
    assert _redact_license_key_for_log("TEST-12345-ABCDE") == "TEST-****-ABCDE"


def test_redact_license_key_for_log_handles_short_values():
    assert _redact_license_key_for_log("") == "****"
    assert _redact_license_key_for_log(None) == "****"
    assert _redact_license_key_for_log("ABC123") == "****"


def test_check_package_ownership_exception_redacts_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("c" * 32)
    client = CloudFunctionsClient()
    client._available = True
    monkeypatch.setattr(client, "_get_machine_id", lambda: "machine")

    def fail_post(*args, **kwargs):
        raise RuntimeError(f"ownership request failed for ?key={api_key}")

    monkeypatch.setattr("utils.firebase_license.requests.post", fail_post)

    caplog.set_level(logging.ERROR)

    valid, message = client.check_package_ownership("TEST-1234-5678-ABCD", "horror")

    assert valid is False
    assert api_key not in caplog.text
    assert api_key not in message
    assert "key=<redacted>" in caplog.text
    assert "key=<redacted>" in message


def test_get_owned_packs_exception_redacts_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("l" * 32)
    client = CloudFunctionsClient()
    client._available = True

    def fail_post(*args, **kwargs):
        raise RuntimeError(f"owned packs failed for GEMINI_API_KEY={api_key}")

    monkeypatch.setattr("utils.firebase_license.requests.post", fail_post)

    caplog.set_level(logging.ERROR)

    success, message, packs = client.get_owned_packs("TEST-1234-5678-ABCD")

    assert success is False
    assert packs == []
    assert api_key not in caplog.text
    assert api_key not in message
    assert "GEMINI_API_KEY=<redacted>" in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in message


def test_get_pack_key_exception_redacts_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("k" * 32)
    client = CloudFunctionsClient()
    client._available = True

    def fail_post(*args, **kwargs):
        raise RuntimeError(f"pack key failed for ?key={api_key}")

    monkeypatch.setattr("utils.firebase_license.requests.post", fail_post)

    caplog.set_level(logging.WARNING)

    result = client.get_pack_key("TEST-1234-5678-ABCD", "hwid", "horror")

    assert result is None
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text
