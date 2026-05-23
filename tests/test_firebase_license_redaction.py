from utils.firebase_license import _redact_license_key_for_log


def test_redact_license_key_for_log_hides_middle_segments():
    assert _redact_license_key_for_log("TEST-1234-5678-ABCD") == "TEST-****-****-ABCD"
    assert _redact_license_key_for_log("TEST-12345-ABCDE") == "TEST-****-ABCDE"


def test_redact_license_key_for_log_handles_short_values():
    assert _redact_license_key_for_log("") == "****"
    assert _redact_license_key_for_log(None) == "****"
    assert _redact_license_key_for_log("ABC123") == "****"
