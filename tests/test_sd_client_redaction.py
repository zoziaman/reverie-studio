import logging
from unittest.mock import patch


@patch("requests.get")
def test_create_sd_client_connection_failure_redacts_api_key_in_log(mock_get, caplog):
    from pipeline.sd_client import create_sd_client

    api_key = "AIza" + ("w" * 32)
    mock_get.side_effect = Exception(f"connection refused for ?key={api_key}")

    caplog.set_level(logging.WARNING)

    client = create_sd_client("http://127.0.0.1:7860")

    assert client is not None
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text
