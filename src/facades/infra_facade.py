# src/facades/infra_facade.py
"""
v57.6.8: Infrastructure Facade - 유틸리티/코어 통합 인터페이스

utils, core 레이어의 통합 진입점:
- PackageManager (패키지 관리)
- FontHelper (폰트)
- UtopiaEngine (자동화)
- ChannelRegistry (채널 관리)
- FeedbackLoop, PromptOptimizer 등

GUI에서 직접 utils/core를 import하지 않고 이 Facade를 통해 접근
"""

import logging
from typing import Optional, Dict, Any, Callable, List

logger = logging.getLogger(__name__)


class InfraFacade:
    """
    인프라/유틸리티 Facade

    자주 사용되는 유틸리티 기능을 단일 인터페이스로 제공
    """

    _instance: Optional['InfraFacade'] = None

    def __init__(self, data_dir: str = None):
        """초기화"""
        self._data_dir = data_dir

        # 지연 로드용 캐시
        self._package_manager = None
        self._font_helper = None
        self._channel_registry = None
        self._utopia_engine = None
        self._feedback_loop = None
        self._prompt_optimizer = None
        self._upload_scheduler = None
        self._template_manager = None
        self._batch_queue = None
        self._model_manager = None
        self._server_manager = None
        self._production_stats = None

        # MediaFactory getter (Pipeline에서 주입)
        self._media_factory_getter: Optional[Callable] = None

    # =========================================================
    # 의존성 주입
    # =========================================================

    def set_data_dir(self, data_dir: str):
        """데이터 디렉토리 설정"""
        self._data_dir = data_dir

    def set_media_factory_getter(self, getter: Callable):
        """MediaFactory getter 주입 (UtopiaEngine용)"""
        self._media_factory_getter = getter

    # =========================================================
    # 패키지 관리
    # =========================================================

    @property
    def package_manager(self):
        """PackageManager 인스턴스"""
        if self._package_manager is None:
            from utils.package_manager import get_package_manager
            self._package_manager = get_package_manager()
        return self._package_manager

    def get_package_list(self) -> List[Dict]:
        """패키지 목록 반환"""
        return self.package_manager.list_packages()

    def install_package(self, package_id: str) -> bool:
        """패키지 설치"""
        return self.package_manager.install(package_id)

    # =========================================================
    # 폰트 관리
    # =========================================================

    @property
    def font_helper(self):
        """FontHelper 인스턴스"""
        if self._font_helper is None:
            from utils.font_helper import FontHelper
            self._font_helper = FontHelper()
        return self._font_helper

    def get_available_fonts(self) -> List[str]:
        """사용 가능한 폰트 목록"""
        return self.font_helper.get_available_fonts()

    def get_font_path(self, font_name: str) -> Optional[str]:
        """폰트 경로 반환"""
        return self.font_helper.get_font_path(font_name)

    # =========================================================
    # 채널 관리
    # =========================================================

    @property
    def channel_registry(self):
        """ChannelRegistry 인스턴스"""
        if self._channel_registry is None:
            from utils.channel_registry import get_channel_registry
            self._channel_registry = get_channel_registry()
        return self._channel_registry

    def get_channel(self, channel_id: str):
        """채널 정보 반환"""
        return self.channel_registry.get_channel(channel_id)

    def list_channels(self) -> List:
        """채널 목록 반환"""
        return self.channel_registry.list_channels()

    # =========================================================
    # 유토피아 (자동화)
    # =========================================================

    def get_utopia_engine(self, channel_type: str = "daily_life_toon", channel_id: str = None):
        """UtopiaEngine 인스턴스"""
        from utils.utopia_engine import get_utopia_engine
        return get_utopia_engine(
            data_dir=self._data_dir,
            channel_type=channel_type,
            channel_id=channel_id,
            media_factory_getter=self._media_factory_getter
        )

    # =========================================================
    # 피드백/최적화
    # =========================================================

    def get_feedback_loop(self, channel_type: str = "daily_life_toon"):
        """FeedbackLoop 인스턴스"""
        from utils.feedback_loop import get_feedback_loop
        return get_feedback_loop(self._data_dir, channel_type)

    def get_prompt_optimizer(self, channel_type: str = "daily_life_toon"):
        """PromptOptimizer 인스턴스"""
        from utils.prompt_optimizer import get_prompt_optimizer
        return get_prompt_optimizer(self._data_dir, channel_type)

    def get_upload_scheduler(self, channel_type: str = "daily_life_toon"):
        """UploadScheduler 인스턴스"""
        from utils.upload_scheduler import get_upload_scheduler
        return get_upload_scheduler(self._data_dir, channel_type)

    # =========================================================
    # 템플릿/배치
    # =========================================================

    @property
    def template_manager(self):
        """TemplateManager 인스턴스"""
        if self._template_manager is None:
            from utils.template_manager import get_template_manager
            self._template_manager = get_template_manager()
        return self._template_manager

    @property
    def batch_queue(self):
        """BatchQueue 인스턴스"""
        if self._batch_queue is None:
            from utils.batch_queue import get_batch_queue
            self._batch_queue = get_batch_queue()
        return self._batch_queue

    def add_to_batch(self, json_path: str, channel: str, priority: int = 0):
        """배치 큐에 작업 추가 — v60.1.0 Phase F1"""
        self.batch_queue.add(json_path, channel, priority)

    def get_batch_status(self) -> Dict[str, Any]:
        """배치 큐 상태 조회 — v60.1.0 Phase F1"""
        return self.batch_queue.get_status()

    # =========================================================
    # 하드웨어
    # =========================================================

    def get_hardware_id(self) -> str:
        """하드웨어 ID 반환"""
        from utils.hardware_id import get_hardware_id
        return get_hardware_id()

    # =========================================================
    # 모델/서버 관리
    # =========================================================

    @property
    def model_manager(self):
        """ModelManager 인스턴스"""
        if self._model_manager is None:
            from utils.model_manager import get_model_manager
            self._model_manager = get_model_manager()
        return self._model_manager

    @property
    def server_manager(self):
        """ServerManager 인스턴스"""
        if self._server_manager is None:
            from utils.server_manager import get_server_manager
            self._server_manager = get_server_manager()
        return self._server_manager

    # =========================================================
    # 통계
    # =========================================================

    @property
    def production_stats(self):
        """ProductionStats 인스턴스"""
        if self._production_stats is None:
            from utils.production_stats import get_production_stats
            self._production_stats = get_production_stats()
        return self._production_stats

    # =========================================================
    # Core 모듈
    # =========================================================

    def get_sfx_manager(self):
        """SFXManager 인스턴스"""
        from core.sfx_manager import get_sfx_manager
        return get_sfx_manager()

    def get_character_manager(self):
        """CharacterManager 인스턴스"""
        from core.character_manager import get_character_manager
        return get_character_manager()

    def get_ip_adapter_bridge(self):
        """IPAdapterBridge 인스턴스"""
        from core.ip_adapter_bridge import get_ip_adapter_bridge
        return get_ip_adapter_bridge()


# =========================================================
# 싱글톤 접근자
# =========================================================

_facade_instance: Optional[InfraFacade] = None


def get_infra_facade(data_dir: str = None) -> InfraFacade:
    """InfraFacade 싱글톤 인스턴스 반환"""
    global _facade_instance
    if _facade_instance is None:
        _facade_instance = InfraFacade(data_dir)
    elif data_dir and _facade_instance._data_dir != data_dir:
        _facade_instance.set_data_dir(data_dir)
    return _facade_instance
