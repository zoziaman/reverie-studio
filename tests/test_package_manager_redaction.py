import logging

from utils.package_manager import ChannelPackage, PackageManager


def test_export_package_failure_redacts_secret_in_log_and_return(monkeypatch, tmp_path, caplog):
    secret = "github_pat_" + ("g" * 32)
    package = ChannelPackage(
        package_id="redaction_test",
        package_name="Redaction Test",
        channel_type="test",
    )

    manager = object.__new__(PackageManager)
    manager.security = None

    def fail_copy(_package, _temp_dir):
        raise RuntimeError(f"voice model copy failed for token {secret}")

    monkeypatch.setattr(manager, "_copy_voice_models_to_package", fail_copy)
    caplog.set_level(logging.ERROR)

    success, message = manager.export_package(
        package,
        str(tmp_path / "redaction_test.revpack"),
        include_preview=False,
    )

    assert success is False
    assert secret not in message
    assert secret not in caplog.text
    assert "<redacted-github-token>" in message
    assert "<redacted-github-token>" in caplog.text


def test_import_package_failure_redacts_secret_in_log_and_result(monkeypatch, caplog):
    secret = "npm_" + ("n" * 28)
    manager = object.__new__(PackageManager)

    def fail_get_pack_id(_package_path):
        raise RuntimeError(f"package scan failed for NPM_TOKEN={secret}")

    monkeypatch.setattr(manager, "_get_pack_id_from_file", fail_get_pack_id)
    caplog.set_level(logging.ERROR)

    result = manager.import_package("broken.revpack")

    assert result.success is False
    assert secret not in result.error
    assert secret not in caplog.text
    assert "NPM_TOKEN=<redacted>" in result.error
    assert "NPM_TOKEN=<redacted>" in caplog.text
