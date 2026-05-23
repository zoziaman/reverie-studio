# src/pipeline/sd_client.py
"""
v60.1.0 Phase 3: SD WebUI API 래퍼 클래스

media_factory.py에서 추출한 _SDClientWrapper + _create_sd_client_wrapper.
SD WebUI txt2img API 호출 담당.

원본 위치: media_factory.py L165-241
"""
import logging
import os
import time
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)

# v60.1.0: API retry 상수
_SD_MAX_RETRIES = 3
_SD_BASE_DELAY = 2.0
_SD_CONNECT_TIMEOUT = 30
_SD_DEFAULT_READ_TIMEOUT = 300
_SD_MIN_READ_TIMEOUT = 300
_SD_SERVER_RECOVERY_ATTEMPTS = 1
_SD_HEALTHCHECK_TIMEOUT = 60.0
_SD_HEALTHCHECK_INTERVAL = 2.0


class RetryableSDServerError(Exception):
    """Raised when SD WebUI returns a retryable 5xx response."""

    def __init__(self, status_code: int, body_preview: str = ""):
        self.status_code = status_code
        self.body_preview = body_preview
        message = f"SD server returned {status_code}"
        if body_preview:
            message = f"{message}: {body_preview}"
        super().__init__(message)


def _get_sd_request_timeout() -> tuple[int, int]:
    """Use a short connect timeout and a longer read timeout for heavy SD jobs."""
    raw_value = os.environ.get("REVERIE_SD_READ_TIMEOUT_SEC", str(_SD_DEFAULT_READ_TIMEOUT))
    try:
        read_timeout = int(str(raw_value).strip())
    except (TypeError, ValueError):
        read_timeout = _SD_DEFAULT_READ_TIMEOUT
    return (_SD_CONNECT_TIMEOUT, max(_SD_MIN_READ_TIMEOUT, read_timeout))


def _truncate_response_text(text: str, limit: int = 300) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def _wait_for_sd_health(sd_url: str, timeout_sec: float = _SD_HEALTHCHECK_TIMEOUT) -> bool:
    import requests

    deadline = time.time() + timeout_sec
    health_url = f"{sd_url.rstrip('/')}/sdapi/v1/sd-models"
    while time.time() < deadline:
        try:
            resp = requests.get(health_url, timeout=5)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(_SD_HEALTHCHECK_INTERVAL)
    return False


def _get_localhost_sd_recovery_port(sd_url: str) -> Optional[int]:
    """Return a port only when the configured SD URL explicitly targets localhost."""
    try:
        parsed = urlparse(sd_url or "")
        host = (parsed.hostname or "").strip().lower()
        if host not in {"localhost", "127.0.0.1", "::1"}:
            return None
        return parsed.port or 7860
    except Exception:
        return None


def _restart_sd_webui_server(sd_url: str) -> bool:
    port = _get_localhost_sd_recovery_port(sd_url)
    if port is None:
        logger.warning(f"[SD] skipping local SD WebUI recovery for non-local URL: {sd_url}")
        return False

    logger.warning(f"[SD] attempting SD WebUI recovery on port {port}")

    manager = None
    try:
        from utils.server_manager import get_server_manager, stop_registered_processes

        manager = get_server_manager()
        try:
            manager.stop_server("SD WebUI")
        except Exception as exc:
            logger.debug(f"[SD] manager stop_server failed: {exc}")
        try:
            stop_registered_processes(["SD WebUI"])
        except Exception as exc:
            logger.debug(f"[SD] stop_registered_processes failed: {exc}")
    except Exception as exc:
        logger.debug(f"[SD] server manager unavailable for recovery: {exc}")

    if manager is None:
        logger.error("[SD] no ServerManager available for SD WebUI restart")
        return False

    try:
        if not manager.start_server("SD WebUI"):
            logger.error("[SD] ServerManager.start_server('SD WebUI') failed")
            return False
    except Exception as exc:
        logger.error(f"[SD] SD WebUI restart threw: {exc}")
        return False

    healthy = _wait_for_sd_health(sd_url)
    if not healthy:
        logger.error("[SD] SD WebUI did not become healthy after restart")
    return healthy


class SDClientWrapper:
    """SD WebUI txt2img API 래퍼

    VSD(VisualDirector)가 사용하는 간단한 SD WebUI 클라이언트.
    requests.post로 txt2img endpoint를 호출하고 결과(base64 이미지)를 반환.
    """

    def __init__(self, sd_url: str):
        self.sd_url = sd_url.rstrip('/')
        self._endpoint = f"{self.sd_url}/sdapi/v1/txt2img"
        logger.info(f"[SDWrapper] SD 클라이언트 래퍼 생성: {self.sd_url}")

    def txt2img(self, **params) -> Dict[str, Any]:
        """
        SD WebUI txt2img API 호출

        Args:
            **params: SD API payload 파라미터
                - prompt, negative_prompt, width, height, steps, cfg_scale, seed 등

        Returns:
            {"images": [base64_image_str, ...], "info": {...}}
        """
        import requests

        # VSD PromptComposer의 to_api_params() 형식을 SD WebUI payload로 변환
        payload = {
            "prompt": params.get("prompt", ""),
            "negative_prompt": params.get("negative_prompt", ""),
            "width": params.get("width", 768),
            "height": params.get("height", 432),  # v62.10: 512→432 (프로젝트 기준 768×432, 16:9 비율)
            "steps": params.get("steps", 20),
            "cfg_scale": params.get("cfg_scale", 7),
            "seed": params.get("seed", -1),
            "sampler_name": params.get("sampler_name", "DPM++ 2M"),
            "batch_size": params.get("batch_size", 1),
            "n_iter": params.get("n_iter", 1),
        }

        # 추가 파라미터 (override, hr 등) 전달
        # v59.3.0: FIX-9 - override_settings_restore_afterwards 추가 (모델/VAE 영구 변경 방지)
        for key in ["override_settings", "override_settings_restore_afterwards",
                     "hr_scale", "enable_hr", "denoising_strength",
                     "hr_upscaler", "hr_second_pass_steps", "scheduler"]:
            if key in params:
                payload[key] = params[key]

        # v60.1.0: 공통 retry 유틸 사용 (지수 백오프 + 지터)
        from pipeline.pipeline_utils import RETRYABLE_NETWORK, _get_requests_retryable, retry_api_call

        def _post_txt2img():
            response = requests.post(
                self._endpoint,
                json=payload,
                timeout=_get_sd_request_timeout(),
            )
            if response.status_code >= 500:
                raise RetryableSDServerError(
                    response.status_code,
                    _truncate_response_text(response.text),
                )
            response.raise_for_status()
            return response

        retryable = (RetryableSDServerError,) + RETRYABLE_NETWORK + _get_requests_retryable()

        for recovery_attempt in range(_SD_SERVER_RECOVERY_ATTEMPTS + 1):
            try:
                res = retry_api_call(
                    _post_txt2img,
                    max_retries=_SD_MAX_RETRIES,
                    base_delay=_SD_BASE_DELAY,
                    retryable_exceptions=retryable,
                    context="SD",
                )
                return res.json()
            except RetryableSDServerError as exc:
                logger.error(f"[SD] txt2img server error after retries: {exc}")
                if recovery_attempt < _SD_SERVER_RECOVERY_ATTEMPTS and _restart_sd_webui_server(self.sd_url):
                    logger.warning("[SD] SD WebUI recovered, retrying txt2img once")
                    continue
                raise requests.exceptions.HTTPError(str(exc)) from exc


def create_sd_client(sd_url: str) -> Optional[SDClientWrapper]:
    """SD 클라이언트 래퍼 생성 (SD WebUI 접속 가능 시에만)

    원본: media_factory._create_sd_client_wrapper() L228
    """
    import requests
    try:
        res = requests.get(f"{sd_url.rstrip('/')}/sdapi/v1/sd-models", timeout=5)
        if res.status_code == 200:
            return SDClientWrapper(sd_url)
        else:
            logger.warning(f"[SDWrapper] SD WebUI 응답 이상: status={res.status_code}")
            return SDClientWrapper(sd_url)  # 일단 생성 (에러는 호출 시 발생)
    except Exception as e:
        logger.warning(f"[SDWrapper] SD WebUI 연결 확인 실패: {redact_sensitive_text(e)}")
        # 연결 불가해도 래퍼는 생성 (VSD가 fallback 처리)
        return SDClientWrapper(sd_url)
