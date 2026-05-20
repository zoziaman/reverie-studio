# src/facades/config_facade.py
"""
v57.6.8: Config Facade - 설정 통합 인터페이스

config 레이어의 통합 진입점:
- ReverieSettings (전역 설정)
- 채널별 설정
- 환경 설정

GUI에서 직접 config를 import하지 않고 이 Facade를 통해 접근
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ConfigFacade:
    """
    설정 Facade

    모든 설정 관련 기능을 단일 인터페이스로 제공
    """

    _instance: Optional['ConfigFacade'] = None
    _DEFAULT_CHANNEL_STYLES: Dict[str, Dict[str, Any]] = {
        "horror": {"bgm_volume": 0.20, "subtitle_size": 36, "speaker_size": 28},
        "senior": {"bgm_volume": 0.18, "subtitle_size": 42, "speaker_size": 32},
        "default": {"bgm_volume": 0.15, "subtitle_size": 36, "speaker_size": 28},
    }

    def __init__(self):
        """초기화"""
        self._settings = None
        self._settings_manager = None
        self._settings_manager_unavailable = False

    # =========================================================
    # 전역 설정
    # =========================================================

    @property
    def settings(self):
        """ReverieSettings 인스턴스"""
        if self._settings is None:
            from config.settings import config
            self._settings = config
        return self._settings

    # =========================================================
    # 경로 설정
    # =========================================================

    @property
    def data_dir(self) -> str:
        """데이터 디렉토리"""
        return getattr(self.settings, 'DATA_DIR', 'data')

    @property
    def output_dir(self) -> str:
        """출력 디렉토리"""
        return getattr(self.settings, 'OUTPUT_DIR', 'output')

    @property
    def assets_dir(self) -> str:
        """에셋 디렉토리"""
        return getattr(self.settings, 'ASSETS_DIR', 'assets')

    # =========================================================
    # 서버 URL
    # =========================================================

    @property
    def sd_url(self) -> str:
        """SD WebUI URL"""
        return getattr(self.settings, 'SD_URL', 'http://127.0.0.1:7860')

    @property
    def sovits_url(self) -> str:
        """SoVITS URL"""
        return getattr(self.settings, 'SOVITS_URL', 'http://127.0.0.1:9880')

    # =========================================================
    # 영상 설정
    # =========================================================

    @property
    def video_width(self) -> int:
        """영상 너비"""
        return getattr(self.settings, 'VIDEO_WIDTH', 1920)

    @property
    def video_height(self) -> int:
        """영상 높이"""
        return getattr(self.settings, 'VIDEO_HEIGHT', 1080)

    @property
    def fps(self) -> int:
        """FPS"""
        return getattr(self.settings, 'FPS', 30)

    # =========================================================
    # 채널별 설정
    # =========================================================

    def get_profile(self, channel: str) -> Dict[str, Any]:
        """채널 프로필 반환"""
        return self.settings.get_profile(channel)

    def get_channel_style(self, channel: str) -> Dict[str, Any]:
        """
        채널별 스타일 설정 반환

        Returns:
            {bgm_volume, subtitle_size, speaker_size}
        """
        settings_manager = self._get_settings_manager()
        if settings_manager:
            try:
                style = settings_manager.get_channel_style(channel)
                if isinstance(style, dict) and style:
                    return dict(style)
            except Exception as e:
                logging.getLogger(__name__).debug(f"[ConfigFacade] 채널 스타일 조회 실패, 기본값 사용: {e}")
        return self._default_channel_style(channel)

    def _get_settings_manager(self):
        if self._settings_manager is not None:
            return self._settings_manager
        if self._settings_manager_unavailable:
            return None
        try:
            from gui.settings_manager import SettingsManager
            self._settings_manager = SettingsManager(self.data_dir)
        except Exception as e:
            self._settings_manager_unavailable = True
            logger.debug(f"[ConfigFacade] SettingsManager lazy-load skipped: {e}")
            return None
        return self._settings_manager

    @classmethod
    def _default_channel_style(cls, channel: str) -> Dict[str, Any]:
        key = str(channel or "").strip().lower()
        default_style = cls._DEFAULT_CHANNEL_STYLES.get(key, cls._DEFAULT_CHANNEL_STYLES["default"])
        return dict(default_style)

    # =========================================================
    # API 키
    # =========================================================

    def get_api_key(self, service: str) -> Optional[str]:
        """
        API 키 반환

        Args:
            service: gemini, youtube, openai 등

        Returns:
            API 키 또는 None
        """
        key_map = {
            "gemini": "GEMINI_API_KEY",
            "youtube": "YOUTUBE_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        attr_name = key_map.get(service, f"{service.upper()}_API_KEY")
        return getattr(self.settings, attr_name, None)

    # =========================================================
    # 설정 변경
    # =========================================================

    def set(self, key: str, value: Any):
        """설정 값 변경"""
        if hasattr(self.settings, key):
            setattr(self.settings, key, value)
            logger.info(f"[ConfigFacade] {key} = {value}")

    def get(self, key: str, default: Any = None) -> Any:
        """설정 값 조회"""
        return getattr(self.settings, key, default)

    # =========================================================
    # 렌더링 설정
    # =========================================================

    @property
    def render_engine(self) -> str:
        """렌더링 엔진 (v60.1.0: remotion만 지원)"""
        return getattr(self.settings, 'RENDER_ENGINE', 'remotion')

    @property
    def remotion_concurrency(self) -> int:
        """Remotion 동시성"""
        return getattr(self.settings, 'REMOTION_CONCURRENCY', 6)

    # =========================================================
    # TTS 설정
    # =========================================================

    @property
    def tts_engine(self) -> str:
        """TTS 엔진 (sovits, supertonic)"""
        return getattr(self.settings, 'TTS_ENGINE', 'sovits')

    # =========================================================
    # v60.1.0 Phase F1: 추가 속성
    # =========================================================

    @property
    def sd_model(self) -> str:
        """현재 SD 체크포인트 모델명"""
        return getattr(self.settings, 'SD_MODEL', 'meinamix_v12Final')  # v61: MeinaMix V12 통일

    @property
    def tts_settings(self) -> Dict[str, Any]:
        """TTS 관련 전체 설정"""
        return {
            'engine': self.tts_engine,
            'sovits_url': self.sovits_url,
            'hybrid_enabled': getattr(
                self.settings,
                'TTS_HYBRID_ENABLED',
                getattr(self.settings, 'HYBRID_TTS', False),
            ),
            'supertonic_default_voice': getattr(self.settings, 'SUPERTONIC_DEFAULT_VOICE', 'M1'),
            'supertonic_total_steps': getattr(self.settings, 'SUPERTONIC_TOTAL_STEPS', 5),
            'supertonic_speed': getattr(self.settings, 'SUPERTONIC_SPEED', 1.05),
        }

    @property
    def image_settings(self) -> Dict[str, Any]:
        """이미지 생성 관련 설정"""
        return {
            'sd_url': self.sd_url,
            'sd_model': self.sd_model,
            'consistency_enabled': getattr(self.settings, 'CONSISTENCY', True),
        }


# =========================================================
# 싱글톤 접근자
# =========================================================

_facade_instance: Optional[ConfigFacade] = None


def get_config_facade() -> ConfigFacade:
    """ConfigFacade 싱글톤 인스턴스 반환"""
    global _facade_instance
    if _facade_instance is None:
        _facade_instance = ConfigFacade()
    return _facade_instance
