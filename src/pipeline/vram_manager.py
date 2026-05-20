# src/pipeline/vram_manager.py
"""
v60.1.0 Phase 5: VRAM 관리 모듈

media_factory.py에서 추출한 SD WebUI VRAM 언로드/리로드 로직.
SDXL(~6GB VRAM) + SoVITS TTS가 동시에 GPU를 못 쓰는 문제 해결.
TTS 전에 SD 언로드 → TTS 풀스피드 → 이미지 생성 전 리로드.

원본 위치: media_factory.py L1755-1781
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class VRAMManager:
    """SD WebUI VRAM 관리

    RTX 4060 Ti 8GB 환경에서 SD와 TTS의 VRAM 충돌 방지.
    SD 체크포인트를 RAM으로 언로드/리로드하여 TTS에 VRAM 양보.
    """

    def __init__(self, sd_url: str):
        self.sd_url = sd_url.rstrip('/')
        self._unloaded = False

    def unload_checkpoint(self) -> bool:
        """SD WebUI 체크포인트를 VRAM에서 언로드 (RAM으로 이동)

        Returns:
            bool: 언로드 성공 여부
        """
        try:
            import requests
            resp = requests.post(
                f"{self.sd_url}/sdapi/v1/unload-checkpoint",
                timeout=10
            )
            if resp.status_code == 200:
                self._unloaded = True
                logger.info("[SD] 체크포인트 언로드 완료 (VRAM 해방)")
                return True
            else:
                logger.warning(f"[SD] 언로드 실패 (status={resp.status_code})")
                return False
        except Exception as e:
            logger.warning(f"[SD] 언로드 요청 실패 (무시): {e}")
            return False

    def reload_checkpoint(self, max_retries: int = 2) -> bool:
        """SD WebUI 체크포인트를 VRAM에 다시 로드

        리로드 실패 시 이미지 생성이 불가하므로 재시도 포함.
        공통 retry_api_call()로 네트워크 재시도 위임.

        Args:
            max_retries: 최대 재시도 횟수 (기본 2회)

        Returns:
            bool: 리로드 성공 여부
        """
        try:
            import requests
            from pipeline.pipeline_utils import retry_api_call

            resp = retry_api_call(
                requests.post,
                f"{self.sd_url}/sdapi/v1/reload-checkpoint",
                timeout=120,
                max_retries=max_retries,
                base_delay=3.0,
                context="SD-reload",
            )
            if resp.status_code == 200:
                self._unloaded = False
                logger.info("[SD] 체크포인트 리로드 완료 (VRAM 로드)")
                return True
            else:
                logger.warning(f"[SD] 리로드 실패 (status={resp.status_code})")
                return False
        except Exception as e:
            logger.error(f"[SD] 체크포인트 리로드 최종 실패 — 이미지 생성에 영향 가능: {e}")
            return False

    @property
    def is_unloaded(self) -> bool:
        """현재 체크포인트가 언로드 상태인지"""
        return self._unloaded

    def release_tts_vram(self):
        """TTS 리소스 해제 및 VRAM 캐시 정리

        gc.collect() + torch.cuda.empty_cache() 호출.
        """
        import gc
        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("[VRAM] CUDA 캐시 정리 완료")
        except ImportError:
            pass
