import logging
from types import SimpleNamespace

from utils.firebase_license import (
    CloudFunctionsClient,
    FirebaseLicenseValidator,
    HybridLicenseValidator,
    _redact_license_key_for_log,
)


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def _validator_with_collection_error(exc):
    class FailingDb:
        def collection(self, name):
            raise exc

    validator = object.__new__(FirebaseLicenseValidator)
    validator.initialized = True
    validator.db = FailingDb()
    return validator


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


def test_check_package_ownership_error_response_redacts_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("e" * 32)
    client = CloudFunctionsClient()
    client._available = True
    monkeypatch.setattr(client, "_get_machine_id", lambda: "machine")
    monkeypatch.setattr(
        "utils.firebase_license.requests.post",
        lambda *args, **kwargs: _FakeResponse(403, {"message": f"denied for ?key={api_key}"}),
    )

    caplog.set_level(logging.ERROR)

    valid, message = client.check_package_ownership("TEST-1234-5678-ABCD", "horror")

    assert valid is False
    assert api_key not in caplog.text
    assert api_key not in message
    assert "key=<redacted>" in caplog.text
    assert "key=<redacted>" in message


def test_get_owned_packs_error_response_redacts_api_key(monkeypatch):
    api_key = "AIza" + ("g" * 32)
    client = CloudFunctionsClient()
    client._available = True
    monkeypatch.setattr(
        "utils.firebase_license.requests.post",
        lambda *args, **kwargs: _FakeResponse(
            403,
            {"error": f"owned pack denied for GEMINI_API_KEY={api_key}"},
        ),
    )

    success, message, packs = client.get_owned_packs("TEST-1234-5678-ABCD")

    assert success is False
    assert packs == []
    assert api_key not in message
    assert "GEMINI_API_KEY=<redacted>" in message


def test_get_pack_key_error_response_redacts_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("r" * 32)
    client = CloudFunctionsClient()
    client._available = True
    monkeypatch.setattr(
        "utils.firebase_license.requests.post",
        lambda *args, **kwargs: _FakeResponse(200, {"error": f"pack key denied for ?key={api_key}"}),
    )

    caplog.set_level(logging.WARNING)

    result = client.get_pack_key("TEST-1234-5678-ABCD", "hwid", "horror")

    assert result is None
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text


def test_firebase_validate_exception_redacts_secret_in_return():
    secret = "sk-" + ("v" * 32)
    validator = _validator_with_collection_error(
        RuntimeError(f"license lookup failed for OPENAI_API_KEY={secret}")
    )

    valid, message, info = validator.validate("TEST-1234-5678-ABCD", "hwid")

    assert valid is False
    assert info is None
    assert secret not in message
    assert "OPENAI_API_KEY=<redacted>" in message


def test_firebase_add_pack_exception_redacts_secret_in_return():
    secret = "hf_" + ("p" * 28)
    validator = _validator_with_collection_error(
        RuntimeError(f"pack update failed for HF_TOKEN={secret}")
    )

    success, message = validator.add_pack_to_license("TEST-1234-5678-ABCD", "horror")

    assert success is False
    assert secret not in message
    assert "HF_TOKEN=<redacted>" in message


def _make_hybrid_validator():
    validator = object.__new__(HybridLicenseValidator)
    validator.data_dir = "C:/tmp/reverie-license-test"
    validator._load_saved_license_key = lambda: "TEST-1234-5678-ABCD"
    validator._check_ownership_offline = lambda pack_id: (False, "offline")
    validator._get_cached_packs = lambda: []
    validator._update_ownership_cache = lambda pack_id, owned: None
    validator._cache_owned_packs = lambda packs: None
    validator.online_validator = SimpleNamespace(
        is_available=lambda: False,
        check_package_ownership=lambda *args, **kwargs: (False, "unused"),
        get_owned_packs=lambda *args, **kwargs: [],
    )
    return validator


def test_hybrid_package_ownership_cloud_fallback_redacts_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("h" * 32)
    validator = _make_hybrid_validator()

    cloud = SimpleNamespace(
        is_available=True,
        check_package_ownership=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(f"cloud ownership failed for ?key={api_key}")
        ),
    )
    monkeypatch.setattr("utils.firebase_license.get_cloud_functions_client", lambda: cloud)

    caplog.set_level(logging.WARNING)

    valid, message = validator.check_package_ownership("horror")

    assert valid is False
    assert message == "offline"
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text


def test_hybrid_package_ownership_direct_firebase_fallback_redacts_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("d" * 32)
    validator = _make_hybrid_validator()
    validator.online_validator = SimpleNamespace(
        is_available=lambda: True,
        check_package_ownership=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(f"direct firebase failed for GEMINI_API_KEY={api_key}")
        ),
    )

    cloud = SimpleNamespace(is_available=False)
    monkeypatch.setattr("utils.firebase_license.get_cloud_functions_client", lambda: cloud)

    caplog.set_level(logging.WARNING)

    valid, message = validator.check_package_ownership("horror")

    assert valid is False
    assert message == "offline"
    assert api_key not in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in caplog.text


def test_hybrid_owned_packs_cloud_fallback_redacts_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("q" * 32)
    validator = _make_hybrid_validator()

    cloud = SimpleNamespace(
        is_available=True,
        get_owned_packs=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(f"cloud packs failed for ?key={api_key}")
        ),
    )
    monkeypatch.setattr("utils.firebase_license.get_cloud_functions_client", lambda: cloud)

    caplog.set_level(logging.WARNING)

    packs = validator.get_owned_packs()

    assert packs == []
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text


def test_hybrid_owned_packs_direct_firebase_fallback_redacts_api_key(monkeypatch, caplog):
    api_key = "AIza" + ("z" * 32)
    validator = _make_hybrid_validator()
    validator.online_validator = SimpleNamespace(
        is_available=lambda: True,
        get_owned_packs=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(f"direct packs failed for GEMINI_API_KEY={api_key}")
        ),
    )

    cloud = SimpleNamespace(is_available=False)
    monkeypatch.setattr("utils.firebase_license.get_cloud_functions_client", lambda: cloud)

    caplog.set_level(logging.WARNING)

    packs = validator.get_owned_packs()

    assert packs == []
    assert api_key not in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in caplog.text
