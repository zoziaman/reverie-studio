# -*- coding: utf-8 -*-
"""
IP-Adapter Bridge (IP-Adapter 연동 모듈)

v55.0.0: 이미지 일관성을 위한 IP-Adapter 연동
- SD WebUI ControlNet 확장 API 활용
- 참조 이미지 기반 캐릭터 일관성 유지
- IP-Adapter Face/Full 모드 지원

Author: Reverie Studio
"""

import os
import base64
import logging
import requests
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class IPAdapterMode(Enum):
    """IP-Adapter 모드"""
    FACE = "ip-adapter-face"           # 얼굴 일관성 (ip-adapter-faceid)
    FULL = "ip-adapter-full"           # 전체 스타일 (ip-adapter-plus)
    FACE_PLUS = "ip-adapter-face-plus" # 얼굴 + 스타일


@dataclass
class IPAdapterConfig:
    """IP-Adapter 설정"""
    enabled: bool = False
    mode: IPAdapterMode = IPAdapterMode.FACE
    weight: float = 0.7                 # 영향력 (0.0 ~ 1.0)
    reference_images: List[str] = field(default_factory=list)  # 참조 이미지 경로들

    # ControlNet 설정
    control_mode: str = "Balanced"      # Balanced, My prompt is more important, ControlNet is more important
    resize_mode: str = "Crop and Resize"

    # 고급 설정
    start_step: float = 0.0             # 적용 시작 (0.0 ~ 1.0)
    end_step: float = 1.0               # 적용 종료 (0.0 ~ 1.0)


class IPAdapterBridge:
    """
    IP-Adapter 연동 브릿지

    SD WebUI의 ControlNet 확장을 통해 IP-Adapter 기능 활용
    캐릭터/스타일 일관성 유지

    v55.0.0: 초기 구현
    """

    # IP-Adapter 모델 매핑 (ControlNet 확장 기준)
    MODEL_MAP = {
        IPAdapterMode.FACE: "ip-adapter-faceid_sd15",
        IPAdapterMode.FULL: "ip-adapter-plus_sd15",
        IPAdapterMode.FACE_PLUS: "ip-adapter-plus-face_sd15",
    }

    # SDXL 모델 매핑
    MODEL_MAP_SDXL = {
        IPAdapterMode.FACE: "ip-adapter-faceid_sdxl",
        IPAdapterMode.FULL: "ip-adapter-plus_sdxl_vit-h",
        IPAdapterMode.FACE_PLUS: "ip-adapter-plus-face_sdxl_vit-h",
    }

    def __init__(self, sd_url: str = None):
        """
        초기화

        Args:
            sd_url: SD WebUI URL (기본: config에서 로드)
        """
        if sd_url is None:
            try:
                from config.settings import config
                sd_url = config.SD_URL
            except Exception:
                sd_url = "http://127.0.0.1:7860"

        self.sd_url = sd_url.rstrip('/')
        self._available = None
        self._available_models = []
        self._is_sdxl = False

        logger.info(f"IPAdapterBridge 초기화: {self.sd_url}")

    def check_availability(self) -> Tuple[bool, str]:
        """
        IP-Adapter 사용 가능 여부 확인

        Returns:
            (bool, str): (사용 가능 여부, 상태 메시지)
        """
        try:
            # ControlNet 확장 확인
            res = requests.get(f"{self.sd_url}/controlnet/model_list", timeout=10)

            if res.status_code != 200:
                self._available = False
                return False, "ControlNet 확장이 설치되지 않았습니다."

            models = res.json().get("model_list", [])
            self._available_models = [m for m in models if "ip-adapter" in m.lower()]

            if not self._available_models:
                self._available = False
                return False, "IP-Adapter 모델이 설치되지 않았습니다."

            # SDXL 모델 여부 확인
            self._is_sdxl = any("sdxl" in m.lower() for m in self._available_models)

            self._available = True
            return True, f"IP-Adapter 사용 가능 ({len(self._available_models)}개 모델)"

        except requests.exceptions.ConnectionError:
            self._available = False
            return False, "SD WebUI에 연결할 수 없습니다."
        except Exception as e:
            self._available = False
            return False, f"확인 중 오류: {e}"

    @property
    def is_available(self) -> bool:
        """IP-Adapter 사용 가능 여부"""
        if self._available is None:
            self.check_availability()
        return self._available

    def get_available_models(self) -> List[str]:
        """사용 가능한 IP-Adapter 모델 목록"""
        if self._available is None:
            self.check_availability()
        return self._available_models

    def _encode_image(self, image_path: str) -> Optional[str]:
        """
        이미지를 Base64로 인코딩

        Args:
            image_path: 이미지 파일 경로

        Returns:
            str: Base64 인코딩된 이미지 (실패 시 None)
        """
        if not os.path.exists(image_path):
            logger.warning(f"이미지 파일 없음: {image_path}")
            return None

        try:
            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"이미지 인코딩 실패: {e}")
            return None

    def _get_model_name(self, mode: IPAdapterMode) -> str:
        """
        모드에 맞는 모델명 반환

        Args:
            mode: IP-Adapter 모드

        Returns:
            str: 모델명
        """
        model_map = self.MODEL_MAP_SDXL if self._is_sdxl else self.MODEL_MAP
        preferred_model = model_map.get(mode, "ip-adapter-faceid_sd15")

        # 실제 설치된 모델 중에서 매칭
        for available in self._available_models:
            if preferred_model.lower() in available.lower():
                return available

        # 매칭 실패 시 첫 번째 모델 사용
        if self._available_models:
            logger.warning(f"선호 모델 '{preferred_model}' 없음, '{self._available_models[0]}' 사용")
            return self._available_models[0]

        return preferred_model

    def build_controlnet_args(
        self,
        config: IPAdapterConfig,
        reference_image_path: str = None
    ) -> Dict[str, Any]:
        """
        ControlNet API 인자 생성

        Args:
            config: IP-Adapter 설정
            reference_image_path: 참조 이미지 경로 (config에서 오버라이드)

        Returns:
            Dict: ControlNet API 인자 (alwayson_scripts 형태)
        """
        if not config.enabled:
            return {}

        if not self.is_available:
            logger.warning("IP-Adapter를 사용할 수 없습니다.")
            return {}

        # 참조 이미지 결정
        ref_images = config.reference_images
        if reference_image_path:
            ref_images = [reference_image_path]

        if not ref_images:
            logger.warning("참조 이미지가 없습니다.")
            return {}

        # 첫 번째 참조 이미지 사용
        ref_image_b64 = self._encode_image(ref_images[0])
        if not ref_image_b64:
            return {}

        # 모델명
        model_name = self._get_model_name(config.mode)

        # ControlNet 유닛 설정
        controlnet_unit = {
            "enabled": True,
            "module": "ip-adapter_clip_sd15",  # preprocessor
            "model": model_name,
            "weight": config.weight,
            "image": ref_image_b64,
            "resize_mode": config.resize_mode,
            "control_mode": config.control_mode,
            "guidance_start": config.start_step,
            "guidance_end": config.end_step,
        }

        # SDXL용 preprocessor
        if self._is_sdxl:
            controlnet_unit["module"] = "ip-adapter_clip_sdxl"

        # Face 모드 전용 설정
        if config.mode in [IPAdapterMode.FACE, IPAdapterMode.FACE_PLUS]:
            controlnet_unit["module"] = "ip-adapter-auto"

        return {
            "alwayson_scripts": {
                "controlnet": {
                    "args": [controlnet_unit]
                }
            }
        }

    def enhance_payload(
        self,
        base_payload: Dict[str, Any],
        ip_config: IPAdapterConfig,
        reference_image_path: str = None
    ) -> Dict[str, Any]:
        """
        기존 txt2img payload에 IP-Adapter 설정 추가

        Args:
            base_payload: 기존 txt2img API payload
            ip_config: IP-Adapter 설정
            reference_image_path: 참조 이미지 경로 (선택)

        Returns:
            Dict: IP-Adapter가 추가된 payload
        """
        if not ip_config.enabled:
            return base_payload

        # ControlNet 인자 생성
        cn_args = self.build_controlnet_args(ip_config, reference_image_path)

        if not cn_args:
            return base_payload

        # 기존 payload에 병합
        result = base_payload.copy()

        if "alwayson_scripts" not in result:
            result["alwayson_scripts"] = {}

        # 기존 ControlNet 설정이 있으면 유닛 추가
        if "controlnet" in result["alwayson_scripts"]:
            existing_args = result["alwayson_scripts"]["controlnet"].get("args", [])
            new_args = cn_args["alwayson_scripts"]["controlnet"]["args"]
            result["alwayson_scripts"]["controlnet"]["args"] = existing_args + new_args
        else:
            result["alwayson_scripts"]["controlnet"] = cn_args["alwayson_scripts"]["controlnet"]

        logger.info(f"IP-Adapter 설정 추가: mode={ip_config.mode.value}, weight={ip_config.weight}")
        return result


# ========== 싱글톤 인스턴스 ==========

_bridge_instance: Optional[IPAdapterBridge] = None

def get_ip_adapter_bridge(sd_url: str = None) -> IPAdapterBridge:
    """
    IPAdapterBridge 싱글톤 가져오기

    Args:
        sd_url: SD WebUI URL (최초 호출 시에만 적용)

    Returns:
        IPAdapterBridge: 싱글톤 인스턴스
    """
    global _bridge_instance

    if _bridge_instance is None:
        _bridge_instance = IPAdapterBridge(sd_url)

    return _bridge_instance
