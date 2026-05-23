import logging

from utils.package_security import PackageSecurityManager


def _manager_with_decrypt_error(exc):
    class FailingEncryption:
        def decrypt(self, data):
            raise exc

    manager = object.__new__(PackageSecurityManager)
    manager.encryption = FailingEncryption()
    return manager


def test_verify_and_decrypt_value_error_redacts_secret_in_return():
    secret = "sk-" + ("p" * 32)
    manager = _manager_with_decrypt_error(
        ValueError(f"invalid package token for OPENAI_API_KEY={secret}")
    )

    success, message, payload = manager.verify_and_decrypt(b"bad-package")

    assert success is False
    assert payload is None
    assert secret not in message
    assert "OPENAI_API_KEY=<redacted>" in message


def test_verify_and_decrypt_exception_redacts_secret_in_log_and_return(caplog):
    secret = "xoxb-" + ("1" * 12) + "-" + ("s" * 24)
    manager = _manager_with_decrypt_error(
        RuntimeError(f"decrypt failed for SLACK_BOT_TOKEN={secret}")
    )
    caplog.set_level(logging.ERROR)

    success, message, payload = manager.verify_and_decrypt(b"bad-package")

    assert success is False
    assert payload is None
    assert secret not in message
    assert secret not in caplog.text
    assert "SLACK_BOT_TOKEN=<redacted>" in message
    assert "SLACK_BOT_TOKEN=<redacted>" in caplog.text
