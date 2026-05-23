# src/utils/sd_model_manager.py
"""
v36 - Stable Diffusion 모델 관리자

기능:
1. SD WebUI 모델 목록 조회
2. 채널별 모델 설정 관리
3. LoRA/VAE 관리
4. 프롬프트 프리셋 관리
"""

import os
import json
import requests
import logging
import threading
import base64
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, Future

from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)


@dataclass
class SDModelInfo:
    """SD 모델 정보"""
    filename: str               # 파일명 (예: dreamshaper_8.safetensors)
    title: str                  # WebUI 표시명
    model_name: str             # 모델 이름 (확장자 제외)
    hash: str = ""              # 모델 해시
    sha256: str = ""            # SHA256 해시
    size_mb: float = 0          # 파일 크기 (MB)
    thumbnail: Optional[bytes] = None  # 썸네일 이미지 (PNG bytes)

    @classmethod
    def from_api_response(cls, data: Dict) -> 'SDModelInfo':
        """WebUI API 응답에서 생성"""
        filename = data.get("filename", data.get("model_name", ""))
        title = data.get("title", filename)
        model_name = data.get("model_name", Path(filename).stem if filename else "")

        return cls(
            filename=filename,
            title=title,
            model_name=model_name,
            hash=data.get("hash", ""),
            sha256=data.get("sha256", ""),
        )


@dataclass
class LoRAInfo:
    """LoRA 정보"""
    filename: str
    name: str
    alias: str = ""
    path: str = ""

    @classmethod
    def from_api_response(cls, data: Dict) -> 'LoRAInfo':
        return cls(
            filename=data.get("filename", ""),
            name=data.get("name", ""),
            alias=data.get("alias", ""),
            path=data.get("path", ""),
        )


@dataclass
class VAEInfo:
    """VAE 정보"""
    filename: str
    model_name: str

    @classmethod
    def from_api_response(cls, data: Dict) -> 'VAEInfo':
        return cls(
            filename=data.get("filename", data.get("model_name", "")),
            model_name=data.get("model_name", ""),
        )


@dataclass
class PromptPreset:
    """프롬프트 프리셋"""
    name: str
    positive: str
    negative: str
    description: str = ""


@dataclass
class ChannelSDConfig:
    """채널별 SD 설정"""
    channel_id: str                           # horror, senior_touching, senior_makjang

    # 모델 설정
    checkpoint_realistic: str = ""            # 실사 모델
    checkpoint_illustration: str = ""         # 일러스트 모델
    vae: str = "Automatic"                    # VAE (Automatic = 자동)

    # LoRA 설정 (리스트 - 여러 개 적용 가능)
    loras: List[Dict[str, Any]] = field(default_factory=list)  # [{"name": "xxx", "weight": 0.7}, ...]

    # 프롬프트 프리셋
    positive_prompt: str = ""
    negative_prompt: str = ""

    # 생성 설정
    sampler: str = "DPM++ 2M Karras"
    steps: int = 30
    cfg_scale: float = 7.0
    width: int = 1280
    height: int = 720

    # 후처리
    enable_hr: bool = False                   # Hires.fix
    hr_scale: float = 1.5
    hr_upscaler: str = "Latent"
    denoising_strength: float = 0.4

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'ChannelSDConfig':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SDModelManager:
    """
    SD 모델 관리자

    - SD WebUI API를 통해 모델 목록 조회
    - 채널별 모델/프롬프트 설정 관리
    - 설정 파일 저장/로드
    - 비동기 모델 로딩 지원 (v36 제미나이 피드백)
    """

    def __init__(self, sd_url: str = None):
        """
        Args:
            sd_url: SD WebUI URL (기본값: config에서 로드)
        """
        from config.settings import config
        self.config = config
        self.sd_url = sd_url or config.SD_URL

        # 설정 파일 경로
        self.config_dir = Path(config.DATA_DIR) / "sd_config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.channel_config_path = self.config_dir / "channel_sd_config.json"
        self.presets_path = self.config_dir / "prompt_presets.json"
        self.thumbnails_dir = self.config_dir / "thumbnails"
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)

        # 캐시
        self._models_cache: List[SDModelInfo] = []
        self._loras_cache: List[LoRAInfo] = []
        self._vaes_cache: List[VAEInfo] = []
        self._samplers_cache: List[str] = []
        self._thumbnails_cache: Dict[str, bytes] = {}

        # 비동기 작업 관리
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="SDManager")
        self._loading_model: Optional[str] = None
        self._model_load_callbacks: List[Callable[[bool, str], None]] = []

        # 채널 설정 로드
        self._channel_configs: Dict[str, ChannelSDConfig] = {}
        self._load_channel_configs()

        # 프리셋 로드
        self._presets: Dict[str, PromptPreset] = {}
        self._load_presets()

    # ==================== 리소스 정리 ====================

    def close(self):
        """v62.19: ThreadPoolExecutor 정리 (애플리케이션 종료 시 호출)"""
        if hasattr(self, '_executor') and self._executor:
            try:
                self._executor.shutdown(wait=False)
                logger.debug("[SDModelManager] executor shutdown 완료")
            except Exception as e:
                logger.debug(f"[SDModelManager] executor shutdown 실패 (무시): {e}")

    def __del__(self):
        """소멸자: executor 정리"""
        try:
            self.close()
        except Exception:
            pass

    # ==================== API 연동 ====================

    def check_connection(self) -> bool:
        """SD WebUI 연결 확인"""
        try:
            res = requests.get(f"{self.sd_url}/sdapi/v1/sd-models", timeout=5)
            return res.status_code == 200
        except Exception as e:
            logger.warning(f"[SDModelManager] WebUI 연결 실패: {e}")
            return False

    def get_models(self, force_refresh: bool = False) -> List[SDModelInfo]:
        """설치된 SD 모델 목록 조회"""
        if self._models_cache and not force_refresh:
            return self._models_cache

        try:
            res = requests.get(f"{self.sd_url}/sdapi/v1/sd-models", timeout=10)
            if res.status_code == 200:
                models = [SDModelInfo.from_api_response(m) for m in res.json()]
                self._models_cache = models
                logger.info(f"[SDModelManager] {len(models)}개 모델 로드됨")
                return models
        except Exception as e:
            logger.error(f"[SDModelManager] 모델 목록 조회 실패: {e}")

        return []

    def get_loras(self, force_refresh: bool = False) -> List[LoRAInfo]:
        """설치된 LoRA 목록 조회"""
        if self._loras_cache and not force_refresh:
            return self._loras_cache

        try:
            res = requests.get(f"{self.sd_url}/sdapi/v1/loras", timeout=10)
            if res.status_code == 200:
                loras = [LoRAInfo.from_api_response(l) for l in res.json()]
                self._loras_cache = loras
                logger.info(f"[SDModelManager] {len(loras)}개 LoRA 로드됨")
                return loras
        except Exception as e:
            logger.error(f"[SDModelManager] LoRA 목록 조회 실패: {e}")

        return []

    def get_vaes(self, force_refresh: bool = False) -> List[VAEInfo]:
        """설치된 VAE 목록 조회"""
        if self._vaes_cache and not force_refresh:
            return self._vaes_cache

        try:
            res = requests.get(f"{self.sd_url}/sdapi/v1/sd-vae", timeout=10)
            if res.status_code == 200:
                vaes = [VAEInfo.from_api_response(v) for v in res.json()]
                self._vaes_cache = vaes
                logger.info(f"[SDModelManager] {len(vaes)}개 VAE 로드됨")
                return vaes
        except Exception as e:
            logger.error(f"[SDModelManager] VAE 목록 조회 실패: {e}")

        return []

    def get_samplers(self, force_refresh: bool = False) -> List[str]:
        """사용 가능한 샘플러 목록"""
        if self._samplers_cache and not force_refresh:
            return self._samplers_cache

        try:
            res = requests.get(f"{self.sd_url}/sdapi/v1/samplers", timeout=10)
            if res.status_code == 200:
                samplers = [s.get("name", "") for s in res.json()]
                self._samplers_cache = samplers
                return samplers
        except Exception as e:
            logger.error(f"[SDModelManager] 샘플러 목록 조회 실패: {e}")

        # 기본 샘플러 목록
        return [
            "DPM++ 2M Karras",
            "DPM++ SDE Karras",
            "Euler a",
            "Euler",
            "DDIM",
            "UniPC",
        ]

    def get_current_model(self) -> Optional[str]:
        """현재 로드된 모델 조회"""
        try:
            res = requests.get(f"{self.sd_url}/sdapi/v1/options", timeout=10)
            if res.status_code == 200:
                return res.json().get("sd_model_checkpoint")
        except Exception as e:
            logger.error(f"[SDModelManager] 현재 모델 조회 실패: {e}")
        return None

    def set_model(self, model_name: str) -> bool:
        """모델 변경 (동기)"""
        try:
            logger.info(f"[SDModelManager] 모델 변경 요청: {model_name}")
            res = requests.post(
                f"{self.sd_url}/sdapi/v1/options",
                json={"sd_model_checkpoint": model_name},
                timeout=300  # 대용량 모델은 로딩에 5분까지 소요될 수 있음
            )
            if res.status_code == 200:
                logger.info(f"[SDModelManager] 모델 변경 완료: {model_name}")
                return True
        except Exception as e:
            logger.error(f"[SDModelManager] 모델 변경 실패: {e}")
        return False

    def set_model_async(self, model_name: str,
                        on_complete: Optional[Callable[[bool, str], None]] = None,
                        on_progress: Optional[Callable[[str], None]] = None) -> Future:
        """
        비동기 모델 변경 (v36 제미나이 피드백)

        SD/Flux 모델은 용량이 커서 로딩에 시간이 오래 걸림.
        메인 스레드를 블로킹하지 않도록 별도 스레드에서 실행.

        Args:
            model_name: 로드할 모델 이름
            on_complete: 완료 콜백 (success: bool, message: str)
            on_progress: 진행 상태 콜백 (상태 메시지)

        Returns:
            Future 객체 (작업 추적용)
        """
        self._loading_model = model_name

        def _load_task():
            try:
                if on_progress:
                    on_progress(f"모델 로딩 중: {model_name}")

                logger.info(f"[SDModelManager] 비동기 모델 로딩 시작: {model_name}")

                res = requests.post(
                    f"{self.sd_url}/sdapi/v1/options",
                    json={"sd_model_checkpoint": model_name},
                    timeout=300  # 5분 타임아웃
                )

                self._loading_model = None

                if res.status_code == 200:
                    logger.info(f"[SDModelManager] 비동기 모델 로딩 완료: {model_name}")
                    if on_complete:
                        on_complete(True, f"모델 로딩 완료: {model_name}")
                    return True
                else:
                    error_msg = f"HTTP {res.status_code}"
                    logger.error(f"[SDModelManager] 모델 로딩 실패: {error_msg}")
                    if on_complete:
                        on_complete(False, f"모델 로딩 실패: {error_msg}")
                    return False

            except requests.exceptions.Timeout:
                self._loading_model = None
                error_msg = "타임아웃 (5분 초과)"
                logger.error(f"[SDModelManager] {error_msg}")
                if on_complete:
                    on_complete(False, error_msg)
                return False

            except Exception as e:
                self._loading_model = None
                safe_error = redact_sensitive_text(e)
                logger.error(f"[SDModelManager] 모델 로딩 예외: {safe_error}")
                if on_complete:
                    on_complete(False, safe_error)
                return False

        return self._executor.submit(_load_task)

    def is_loading(self) -> bool:
        """모델 로딩 중인지 확인"""
        return self._loading_model is not None

    def get_loading_model(self) -> Optional[str]:
        """현재 로딩 중인 모델명"""
        return self._loading_model

    def set_vae(self, vae_name: str) -> bool:
        """VAE 변경"""
        try:
            res = requests.post(
                f"{self.sd_url}/sdapi/v1/options",
                json={"sd_vae": vae_name},
                timeout=30
            )
            return res.status_code == 200
        except Exception as e:
            logger.error(f"[SDModelManager] VAE 변경 실패: {e}")
        return False

    def refresh_models(self) -> bool:
        """모델 목록 새로고침 (WebUI에서 다시 스캔)"""
        try:
            res = requests.post(f"{self.sd_url}/sdapi/v1/refresh-checkpoints", timeout=30)
            if res.status_code == 200:
                self._models_cache = []  # 캐시 클리어
                return True
        except Exception as e:
            logger.error(f"[SDModelManager] 모델 새로고침 실패: {e}")
        return False

    def refresh_loras(self) -> bool:
        """LoRA 목록 새로고침"""
        try:
            res = requests.post(f"{self.sd_url}/sdapi/v1/refresh-loras", timeout=30)
            if res.status_code == 200:
                self._loras_cache = []
                return True
        except Exception as e:
            logger.error(f"[SDModelManager] LoRA 새로고침 실패: {e}")
        return False

    # ==================== 썸네일 관리 (v36 제미나이 피드백) ====================

    def get_model_thumbnail(self, model: SDModelInfo) -> Optional[bytes]:
        """
        모델 썸네일 이미지 가져오기

        SD WebUI의 모델 폴더에서 preview 이미지를 찾거나,
        캐시된 썸네일을 반환합니다.

        Args:
            model: 모델 정보

        Returns:
            PNG 이미지 bytes 또는 None
        """
        # 캐시 확인
        cache_key = model.model_name or model.filename
        if cache_key in self._thumbnails_cache:
            return self._thumbnails_cache[cache_key]

        # 로컬 캐시 파일 확인
        cached_thumb = self.thumbnails_dir / f"{cache_key}.png"
        if cached_thumb.exists():
            try:
                thumb_data = cached_thumb.read_bytes()
                self._thumbnails_cache[cache_key] = thumb_data
                return thumb_data
            except (OSError, Exception) as e:
                logger.debug(f"썸네일 캐시 읽기 실패: {e}")

        # WebUI API로 썸네일 시도 (일부 확장 설치 시 지원)
        thumb_data = self._fetch_thumbnail_from_api(model)
        if thumb_data:
            self._cache_thumbnail(cache_key, thumb_data)
            return thumb_data

        return None

    def _fetch_thumbnail_from_api(self, model: SDModelInfo) -> Optional[bytes]:
        """
        WebUI API를 통해 모델 썸네일 가져오기

        일부 SD WebUI 확장(예: Civitai Helper)이 설치된 경우
        모델 정보에 preview 이미지가 포함될 수 있음
        """
        try:
            # 모델 해시로 썸네일 조회 시도
            if model.hash:
                res = requests.get(
                    f"{self.sd_url}/sdapi/v1/thumb/{model.hash}",
                    timeout=5
                )
                if res.status_code == 200 and res.content:
                    return res.content

            # 모델 파일명 기반 preview 이미지 조회 시도
            # (일부 API 확장에서 지원)
            model_name = Path(model.filename).stem
            res = requests.get(
                f"{self.sd_url}/sd_extra_networks/thumb?filename={model_name}",
                timeout=5
            )
            if res.status_code == 200 and res.content:
                return res.content

        except Exception as e:
            logger.debug(f"[SDModelManager] 썸네일 API 조회 실패: {e}")

        return None

    def _cache_thumbnail(self, cache_key: str, data: bytes):
        """썸네일 캐시 저장"""
        try:
            self._thumbnails_cache[cache_key] = data
            cache_path = self.thumbnails_dir / f"{cache_key}.png"
            cache_path.write_bytes(data)
            logger.debug(f"[SDModelManager] 썸네일 캐시 저장: {cache_key}")
        except Exception as e:
            logger.warning(f"[SDModelManager] 썸네일 캐시 저장 실패: {e}")

    def get_thumbnail_async(self, model: SDModelInfo,
                            callback: Callable[[Optional[bytes]], None]):
        """
        비동기 썸네일 로드

        Args:
            model: 모델 정보
            callback: 완료 콜백 (이미지 bytes 또는 None)
        """
        def _fetch():
            thumb = self.get_model_thumbnail(model)
            callback(thumb)

        self._executor.submit(_fetch)

    # ==================== 채널 설정 관리 ====================

    def _load_channel_configs(self):
        """채널 설정 로드"""
        if self.channel_config_path.exists():
            try:
                with open(self.channel_config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for channel_id, cfg_data in data.items():
                        self._channel_configs[channel_id] = ChannelSDConfig.from_dict(cfg_data)
                logger.info(f"[SDModelManager] {len(self._channel_configs)}개 채널 설정 로드됨")
            except Exception as e:
                logger.error(f"[SDModelManager] 채널 설정 로드 실패: {e}")

        # 기본 채널 설정 생성
        self._ensure_default_configs()

    def _ensure_default_configs(self):
        """기본 채널 설정이 없으면 생성"""
        # v61: MeinaMix V12 전 장르 통일 (팩 설정이 우선, 이건 폴백)
        default_channels = {
            "daily_life_toon": ChannelSDConfig(
                channel_id="daily_life_toon",
                checkpoint_realistic="",
                checkpoint_illustration="mistoonAnime_v10Noobai.safetensors",
                positive_prompt="premium Korean webtoon video-toon, layered background, character foreground, clean line art, expressive face, daily-life lighting",
                negative_prompt="photorealistic, 3d render, chibi, cropped head, cut off hair, deformed face, text, watermark, UI overlay, lowres, bad anatomy",
            ),
            "mystery_toon": ChannelSDConfig(
                channel_id="mystery_toon",
                checkpoint_realistic="",
                checkpoint_illustration="mistoonAnime_v10Noobai.safetensors",
                positive_prompt="premium Korean mystery webtoon video-toon, layered background, character foreground, restrained shadows, clean line art, expressive eyes",
                negative_prompt="photorealistic, 3d render, gore, monster, chibi, cropped head, cut off hair, deformed face, text, watermark, UI overlay, lowres, bad anatomy",
            ),
        }

        changed = False
        for channel_id, default_cfg in default_channels.items():
            if channel_id not in self._channel_configs:
                self._channel_configs[channel_id] = default_cfg
                changed = True

        if changed:
            self._save_channel_configs()

    def _save_channel_configs(self):
        """채널 설정 저장"""
        try:
            data = {cid: cfg.to_dict() for cid, cfg in self._channel_configs.items()}
            with open(self.channel_config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("[SDModelManager] 채널 설정 저장됨")
        except Exception as e:
            logger.error(f"[SDModelManager] 채널 설정 저장 실패: {e}")

    def get_channel_config(self, channel_id: str) -> ChannelSDConfig:
        """채널 설정 조회"""
        if channel_id in self._channel_configs:
            return self._channel_configs[channel_id]

        # 없으면 기본 설정 생성
        cfg = ChannelSDConfig(channel_id=channel_id)
        self._channel_configs[channel_id] = cfg
        return cfg

    def set_channel_config(self, channel_id: str, config: ChannelSDConfig) -> bool:
        """채널 설정 저장"""
        try:
            config.channel_id = channel_id
            self._channel_configs[channel_id] = config
            self._save_channel_configs()
            return True
        except Exception as e:
            logger.error(f"[SDModelManager] 채널 설정 저장 실패: {e}")
            return False

    def get_all_channel_configs(self) -> Dict[str, ChannelSDConfig]:
        """모든 채널 설정 조회"""
        return self._channel_configs.copy()

    # ==================== 프리셋 관리 ====================

    def _load_presets(self):
        """프롬프트 프리셋 로드"""
        if self.presets_path.exists():
            try:
                with open(self.presets_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for name, preset_data in data.items():
                        self._presets[name] = PromptPreset(**preset_data)
            except Exception as e:
                logger.error(f"[SDModelManager] 프리셋 로드 실패: {e}")

        # 기본 프리셋
        self._ensure_default_presets()

    def _ensure_default_presets(self):
        """기본 프리셋이 없으면 생성"""
        default_presets = {
            "videotoon_daily": PromptPreset(
                name="videotoon_daily",
                positive="premium Korean webtoon video-toon, layered background, character foreground cutout, clean cel shading, expressive face",
                negative="photorealistic, 3d render, chibi, cropped head, cut off hair, text, watermark, UI overlay, deformed, bad anatomy",
                description="일상 영상툰 레이어 스타일",
            ),
            "videotoon_mystery": PromptPreset(
                name="videotoon_mystery",
                positive="premium Korean mystery webtoon video-toon, layered background, character foreground cutout, restrained shadows, expressive eyes",
                negative="photorealistic, 3d render, gore, monster, chibi, cropped head, cut off hair, text, watermark, UI overlay, deformed, bad anatomy",
                description="미스터리 영상툰 레이어 스타일",
            ),
            "realistic_korean": PromptPreset(
                name="realistic_korean",
                positive="photorealistic, korean, masterpiece, best quality, 8k uhd, professional photography",
                negative="anime, cartoon, drawing, illustration, lowres, blurry, bad anatomy",
                description="한국인 실사 스타일",
            ),
        }

        changed = False
        for name, preset in default_presets.items():
            if name not in self._presets:
                self._presets[name] = preset
                changed = True

        if changed:
            self._save_presets()

    def _save_presets(self):
        """프리셋 저장"""
        try:
            data = {name: asdict(preset) for name, preset in self._presets.items()}
            with open(self.presets_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[SDModelManager] 프리셋 저장 실패: {e}")

    def get_presets(self) -> Dict[str, PromptPreset]:
        """모든 프리셋 조회"""
        return self._presets.copy()

    def get_preset(self, name: str) -> Optional[PromptPreset]:
        """프리셋 조회"""
        return self._presets.get(name)

    def save_preset(self, preset: PromptPreset) -> bool:
        """프리셋 저장"""
        try:
            self._presets[preset.name] = preset
            self._save_presets()
            return True
        except Exception as e:
            logger.error(f"[SDModelManager] 프리셋 저장 실패: {e}")
            return False

    def delete_preset(self, name: str) -> bool:
        """프리셋 삭제"""
        if name in self._presets:
            del self._presets[name]
            self._save_presets()
            return True
        return False

    # ==================== 헬퍼 메서드 ====================

    def build_generation_params(self, channel_id: str,
                                  prompt: str,
                                  use_realistic: bool = False) -> Dict[str, Any]:
        """
        채널 설정을 기반으로 이미지 생성 파라미터 구성

        Args:
            channel_id: 채널 ID
            prompt: 기본 프롬프트 (장면 묘사)
            use_realistic: 실사 모델 사용 여부

        Returns:
            SD WebUI txt2img API 파라미터
        """
        cfg = self.get_channel_config(channel_id)

        # 체크포인트 선택
        checkpoint = cfg.checkpoint_realistic if use_realistic else cfg.checkpoint_illustration

        # 프롬프트 구성
        full_positive = f"{prompt}, {cfg.positive_prompt}" if cfg.positive_prompt else prompt
        full_negative = cfg.negative_prompt

        # LoRA 적용
        if cfg.loras:
            lora_tags = []
            for lora in cfg.loras:
                name = lora.get("name", "")
                weight = lora.get("weight", 0.7)
                if name:
                    lora_tags.append(f"<lora:{name}:{weight}>")
            if lora_tags:
                full_positive = f"{full_positive}, {' '.join(lora_tags)}"

        params = {
            "prompt": full_positive,
            "negative_prompt": full_negative,
            "sampler_name": cfg.sampler,
            "steps": cfg.steps,
            "cfg_scale": cfg.cfg_scale,
            "width": cfg.width,
            "height": cfg.height,
        }

        # Hires.fix
        if cfg.enable_hr:
            params.update({
                "enable_hr": True,
                "hr_scale": cfg.hr_scale,
                "hr_upscaler": cfg.hr_upscaler,
                "denoising_strength": cfg.denoising_strength,
            })

        return params, checkpoint

    def apply_channel_settings(self, channel_id: str, use_realistic: bool = False) -> bool:
        """
        채널 설정을 WebUI에 적용 (모델 + VAE 변경)

        Args:
            channel_id: 채널 ID
            use_realistic: 실사 모델 사용 여부

        Returns:
            성공 여부
        """
        cfg = self.get_channel_config(channel_id)

        # 체크포인트 변경
        checkpoint = cfg.checkpoint_realistic if use_realistic else cfg.checkpoint_illustration
        if checkpoint:
            current = self.get_current_model()
            if current != checkpoint:
                if not self.set_model(checkpoint):
                    return False

        # VAE 변경
        if cfg.vae and cfg.vae != "Automatic":
            self.set_vae(cfg.vae)

        return True


# 싱글톤 인스턴스
_manager_instance: Optional[SDModelManager] = None

def get_sd_model_manager() -> SDModelManager:
    """SDModelManager 싱글톤 인스턴스 반환"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = SDModelManager()
    return _manager_instance
