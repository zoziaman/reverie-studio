# src/modules_pro/image_generator.py
# ============================================================
# v56.1: ImageGenerator - SD WebUI 기반 이미지 생성기
# MediaFactory에서 분리된 이미지 생성 전담 모듈
# ============================================================
import os
import sys
import time
import logging
import requests
import subprocess
from typing import Dict, Optional

from config.settings import config

# 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("image_generator")
except ImportError:
    logger = logging.getLogger("image_generator")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)


class ImageGenerator:
    """
    SD WebUI 기반 이미지 생성기

    v56.1: MediaFactory에서 분리된 이미지 생성 전담 클래스
    - SD WebUI 연결/시동
    - 모델 설정
    - txt2img 생성
    - IP-Adapter 일관성 적용
    """

    def __init__(self, channel: str = "daily_life_toon", sd_url: str = None):
        """
        초기화

        Args:
            channel: 채널 타입 (horror, senior_makjang, senior_touching 등)
            sd_url: SD WebUI URL (기본: config.SD_URL)
        """
        self.channel = channel
        self.sd_url = sd_url or config.SD_URL

        # 일관성 설정 (IP-Adapter)
        self._consistency_enabled = False
        self._consistency_config = None
        self._fixed_seed = None

        logger.info(f"[ImageGenerator] 초기화: channel={channel}, sd_url={self.sd_url}")

    def check_connection(self) -> bool:
        """SD WebUI 연결 확인"""
        try:
            res = requests.get(f"{self.sd_url}/sdapi/v1/sd-models", timeout=5)
            return res.status_code == 200
        except Exception:
            return False

    def boot_sd_webui(self) -> bool:
        """SD WebUI 자동 시동"""
        logger.info("[ImageGenerator] SD WebUI 자동 시동 시도")

        sd_root = config.SD_WEBUI_ROOT
        is_windows = sys.platform == 'win32'

        if is_windows:
            sd_python = os.path.join(sd_root, "venv", "Scripts", "python.exe")
        else:
            sd_python = os.path.join(sd_root, "venv", "bin", "python")
        sd_launch = os.path.join(sd_root, "launch.py")

        if not os.path.exists(sd_python) or not os.path.exists(sd_launch):
            logger.error(f"[ImageGenerator] SD WebUI 경로 없음")
            return False

        try:
            popen_kwargs = {"cwd": sd_root}
            if is_windows:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

            subprocess.Popen(
                [sd_python, sd_launch, "--api", "--xformers"],
                **popen_kwargs
            )
            logger.info("[ImageGenerator] SD WebUI 시동 명령 전송")

            # 준비 대기 (최대 180초)
            for i in range(90):
                time.sleep(2)
                if self.check_connection():
                    logger.info("[ImageGenerator] SD WebUI 시동 완료")
                    return True

            logger.error("[ImageGenerator] SD WebUI 시동 타임아웃")
            return False

        except Exception as e:
            logger.error(f"[ImageGenerator] SD WebUI 시동 실패: {e}")
            return False

    def set_model(self, target_model: str = None, target_vae: str = None) -> bool:
        """
        SD 모델 + VAE 설정

        v59.2.4: VAE 자동 적용 추가, 팩 설정 기본값 사용

        Args:
            target_model: 모델 파일명 (None이면 채널별 기본 모델)
            target_vae: VAE 파일명 (None이면 변경 안 함, "Automatic"이면 자동)
        """
        if target_model is None:
            # v61: 팩 설정 없을 때 폴백 (MeinaMix V12 통일)
            target_model = "meinamix_v12Final.safetensors"

        # 현재 모델 확인
        current_model = None
        current_vae = None
        for attempt in range(3):
            try:
                opt_res = requests.get(f"{self.sd_url}/sdapi/v1/options", timeout=5).json()
                current_model = opt_res.get("sd_model_checkpoint")
                current_vae = opt_res.get("sd_vae")
                break
            except Exception as e:
                delay = 1.0 * (2 ** attempt)
                logger.warning(f"[ImageGenerator] 옵션 조회 실패, 재시도 {attempt+1}/3")
                time.sleep(delay)

        if current_model is None:
            # SD WebUI 자동 시동 시도
            if self.boot_sd_webui():
                try:
                    opt_res = requests.get(f"{self.sd_url}/sdapi/v1/options", timeout=5).json()
                    current_model = opt_res.get("sd_model_checkpoint")
                    current_vae = opt_res.get("sd_vae")
                except Exception as e:
                    logger.warning(f"[ImageGenerator] SD WebUI 옵션 조회 실패: {e}")

        if current_model is None:
            logger.error("[ImageGenerator] SD WebUI 연결 실패")
            return False

        # 모델 교체 필요 여부 확인
        model_changed = False
        if target_model not in str(current_model):
            logger.info(f"[ImageGenerator] 모델 교체: {current_model} -> {target_model}")
            for attempt in range(3):
                try:
                    requests.post(
                        f"{self.sd_url}/sdapi/v1/options",
                        json={"sd_model_checkpoint": target_model},
                        timeout=180
                    )
                    time.sleep(5)
                    logger.info(f"[ImageGenerator] 모델 스위칭 완료: {target_model}")
                    model_changed = True
                    break
                except Exception as e:
                    delay = 2.0 * (2 ** attempt)
                    logger.warning(f"[ImageGenerator] 모델 스위칭 실패, 재시도 {attempt+1}/3")
                    time.sleep(delay)

            if not model_changed:
                logger.error(f"[ImageGenerator] 모델 스위칭 최종 실패")
                return False
        else:
            logger.info(f"[ImageGenerator] 이미 최적 모델 장착: {current_model}")

        # v59.2.4: VAE 적용
        if target_vae and target_vae not in str(current_vae or ""):
            logger.info(f"[ImageGenerator] VAE 교체: {current_vae} -> {target_vae}")
            try:
                requests.post(
                    f"{self.sd_url}/sdapi/v1/options",
                    json={"sd_vae": target_vae},
                    timeout=30
                )
                logger.info(f"[ImageGenerator] VAE 적용 완료: {target_vae}")
            except Exception as e:
                logger.warning(f"[ImageGenerator] VAE 적용 실패 (계속 진행): {e}")
        elif target_vae:
            logger.info(f"[ImageGenerator] 이미 올바른 VAE 장착: {current_vae}")

        return True

    def enable_consistency(self, reference_image: str, mode: str = "face", weight: float = 0.7, seed: int = None):
        """
        이미지 일관성 활성화 (IP-Adapter)

        Args:
            reference_image: 참조 이미지 경로
            mode: "face", "full", "face_plus"
            weight: 영향력 (0.0~1.0)
            seed: 고정 시드 (None이면 랜덤)
        """
        try:
            from core.ip_adapter_bridge import get_ip_adapter_bridge, IPAdapterConfig, IPAdapterMode

            mode_map = {
                "face": IPAdapterMode.FACE,
                "full": IPAdapterMode.FULL,
                "face_plus": IPAdapterMode.FACE_PLUS
            }

            self._consistency_config = IPAdapterConfig(
                enabled=True,
                mode=mode_map.get(mode, IPAdapterMode.FACE),
                weight=weight,
                reference_images=[reference_image]
            )
            self._consistency_enabled = True
            self._fixed_seed = seed

            logger.info(f"[ImageGenerator] 일관성 활성화: mode={mode}, weight={weight}")

        except ImportError:
            logger.warning("[ImageGenerator] IP-Adapter 모듈 없음, 일관성 비활성화")
            self._consistency_enabled = False

    def disable_consistency(self):
        """이미지 일관성 비활성화"""
        self._consistency_enabled = False
        self._consistency_config = None
        self._fixed_seed = None
        logger.info("[ImageGenerator] 일관성 비활성화")

    def apply_consistency_to_payload(self, payload: Dict) -> Dict:
        """
        txt2img 페이로드에 IP-Adapter 설정 적용

        Args:
            payload: 기존 txt2img 페이로드

        Returns:
            일관성 설정이 추가된 페이로드
        """
        if not self._consistency_enabled or not self._consistency_config:
            return payload

        try:
            from core.ip_adapter_bridge import get_ip_adapter_bridge

            bridge = get_ip_adapter_bridge(self.sd_url)
            result = bridge.enhance_payload(payload, self._consistency_config)

            # 고정 시드 적용
            if self._fixed_seed is not None:
                result["seed"] = self._fixed_seed

            return result

        except Exception as e:
            logger.warning(f"[ImageGenerator] IP-Adapter 적용 실패: {e}")
            return payload

    @property
    def consistency_enabled(self) -> bool:
        """일관성 활성화 여부"""
        return self._consistency_enabled

    @property
    def fixed_seed(self) -> Optional[int]:
        """고정 시드"""
        return self._fixed_seed
