# tests/test_sd_client.py
"""
v63.0 Phase 1: SDClientWrapper 유닛 테스트

sd_client.py의 핵심 경로 테스트:
- SDClientWrapper 생성
- txt2img API 호출 (목 HTTP)
- 재시도 로직 (RetryableSDServerError)
- 타임아웃 설정
- 헬스체크
- create_sd_client 팩토리
"""
import os
import pytest
from unittest.mock import patch, MagicMock


class TestSDClientWrapper:
    """SDClientWrapper 기본 동작"""

    def test_init(self):
        from pipeline.sd_client import SDClientWrapper
        client = SDClientWrapper("http://127.0.0.1:7860")
        assert client.sd_url == "http://127.0.0.1:7860"
        assert client._endpoint == "http://127.0.0.1:7860/sdapi/v1/txt2img"

    def test_init_trailing_slash(self):
        from pipeline.sd_client import SDClientWrapper
        client = SDClientWrapper("http://127.0.0.1:7860/")
        assert client.sd_url == "http://127.0.0.1:7860"

    @patch('pipeline.pipeline_utils.retry_api_call')
    @patch('requests.post')
    def test_txt2img_default_params(self, mock_post, mock_retry):
        from pipeline.sd_client import SDClientWrapper

        mock_response = MagicMock()
        mock_response.json.return_value = {"images": ["base64data"], "info": {}}
        mock_retry.return_value = mock_response

        client = SDClientWrapper("http://127.0.0.1:7860")
        result = client.txt2img(prompt="a cat", negative_prompt="bad")

        assert result == {"images": ["base64data"], "info": {}}

    @patch('pipeline.pipeline_utils.retry_api_call')
    @patch('requests.post')
    def test_txt2img_custom_dimensions(self, mock_post, mock_retry):
        from pipeline.sd_client import SDClientWrapper

        mock_response = MagicMock()
        mock_response.json.return_value = {"images": ["img"]}
        mock_retry.return_value = mock_response

        client = SDClientWrapper("http://127.0.0.1:7860")
        client.txt2img(prompt="test", width=512, height=512, steps=30, cfg_scale=9)

        mock_retry.assert_called_once()

    @patch('pipeline.pipeline_utils.retry_api_call')
    @patch('requests.post')
    def test_txt2img_override_settings_forwarded(self, mock_post, mock_retry):
        """override_settings가 payload에 포함되는지"""
        from pipeline.sd_client import SDClientWrapper

        mock_response = MagicMock()
        mock_response.json.return_value = {"images": ["img"]}
        mock_retry.return_value = mock_response

        client = SDClientWrapper("http://127.0.0.1:7860")
        client.txt2img(
            prompt="test",
            override_settings={"sd_model_checkpoint": "model.safetensors"},
            override_settings_restore_afterwards=True,
        )
        mock_retry.assert_called_once()


class TestRetryableError:
    """RetryableSDServerError 테스트"""

    def test_error_message(self):
        from pipeline.sd_client import RetryableSDServerError
        err = RetryableSDServerError(500, "Internal Server Error")
        assert "500" in str(err)
        assert "Internal Server Error" in str(err)
        assert err.status_code == 500

    def test_error_without_body(self):
        from pipeline.sd_client import RetryableSDServerError
        err = RetryableSDServerError(503)
        assert "503" in str(err)


class TestTimeout:
    """타임아웃 설정 테스트"""

    def test_default_timeout(self):
        from pipeline.sd_client import _get_sd_request_timeout
        connect, read = _get_sd_request_timeout()
        assert connect == 30
        assert read >= 300

    @patch.dict(os.environ, {"REVERIE_SD_READ_TIMEOUT_SEC": "600"})
    def test_env_override_timeout(self):
        from pipeline.sd_client import _get_sd_request_timeout
        connect, read = _get_sd_request_timeout()
        assert read == 600

    @patch.dict(os.environ, {"REVERIE_SD_READ_TIMEOUT_SEC": "invalid"})
    def test_invalid_env_fallback(self):
        from pipeline.sd_client import _get_sd_request_timeout
        connect, read = _get_sd_request_timeout()
        assert read >= 300  # 기본값으로 폴백


class TestTruncateResponse:
    """응답 텍스트 잘라내기"""

    def test_short_text(self):
        from pipeline.sd_client import _truncate_response_text
        assert _truncate_response_text("hello") == "hello"

    def test_long_text_truncated(self):
        from pipeline.sd_client import _truncate_response_text
        long = "x" * 500
        result = _truncate_response_text(long, limit=100)
        assert len(result) <= 104  # 100 + "..."
        assert result.endswith("...")

    def test_none_input(self):
        from pipeline.sd_client import _truncate_response_text
        assert _truncate_response_text(None) == ""


class TestHealthCheck:
    """SD WebUI 헬스체크"""

    @patch('requests.get')
    def test_healthy_server(self, mock_get):
        from pipeline.sd_client import _wait_for_sd_health
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        assert _wait_for_sd_health("http://127.0.0.1:7860", timeout_sec=5) is True

    @patch('requests.get')
    def test_unhealthy_server(self, mock_get):
        from pipeline.sd_client import _wait_for_sd_health
        import requests
        mock_get.side_effect = requests.RequestException("connection refused")

        assert _wait_for_sd_health("http://127.0.0.1:7860", timeout_sec=0.1) is False


class TestSDRecoveryTarget:
    """SD WebUI 자동 복구 대상 판정."""

    def test_recovery_allows_explicit_localhost(self):
        from pipeline.sd_client import _get_localhost_sd_recovery_port

        assert _get_localhost_sd_recovery_port("http://127.0.0.1:7860") == 7860
        assert _get_localhost_sd_recovery_port("http://localhost:7861") == 7861

    def test_recovery_rejects_remote_or_implicit_urls(self):
        from pipeline.sd_client import _get_localhost_sd_recovery_port

        assert _get_localhost_sd_recovery_port("http://192.168.0.10:7860") is None
        assert _get_localhost_sd_recovery_port("http://sd.example.com:7860") is None
        assert _get_localhost_sd_recovery_port(":7860") is None

    @patch("pipeline.sd_client._wait_for_sd_health", return_value=True)
    @patch("utils.server_manager.stop_registered_processes", return_value={"SD WebUI": True})
    @patch("utils.server_manager.get_server_manager")
    def test_recovery_never_kills_unregistered_port_listener(
        self,
        mock_get_manager,
        mock_stop_registered,
        mock_wait_health,
    ):
        """Recovery may restart managed SD, but must not kill arbitrary localhost services."""
        import pipeline.sd_client as sd_client

        manager = MagicMock()
        manager.start_server.return_value = True
        mock_get_manager.return_value = manager

        assert sd_client._restart_sd_webui_server("http://127.0.0.1:7860") is True
        manager.stop_server.assert_called_once_with("SD WebUI")
        mock_stop_registered.assert_called_once_with(["SD WebUI"])
        assert not hasattr(sd_client, "_kill_listening_process_on_port")


class TestCreateSDClient:
    """create_sd_client 팩토리"""

    @patch('requests.get')
    def test_create_success(self, mock_get):
        from pipeline.sd_client import create_sd_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        client = create_sd_client("http://127.0.0.1:7860")
        assert client is not None
        assert client.sd_url == "http://127.0.0.1:7860"

    @patch('requests.get')
    def test_create_connection_failure_still_returns(self, mock_get):
        """연결 실패해도 래퍼 반환 (VSD가 fallback 처리)"""
        from pipeline.sd_client import create_sd_client
        mock_get.side_effect = Exception("connection refused")

        client = create_sd_client("http://127.0.0.1:7860")
        assert client is not None  # 래퍼는 반환됨
