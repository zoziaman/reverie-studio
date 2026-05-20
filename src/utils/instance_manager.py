# src/utils/instance_manager.py
"""
v54.7.2: 전역 인스턴스 관리자 (InstanceManager)

모든 유토피아 시스템 모듈의 인스턴스를 중앙에서 관리
- 동일한 channel_type/channel_id에 대해 항상 같은 인스턴스 반환
- 인스턴스 간 데이터 일관성 보장
- 메모리 효율적인 싱글톤 패턴
- v54.7.2: 순환 참조 방지를 위한 초기화 순서 관리

사용법:
    from utils.instance_manager import get_instance_manager

    manager = get_instance_manager()
    optimizer = manager.get_auto_optimizer(data_dir, channel_type)
    scheduler = manager.get_upload_scheduler(data_dir, channel_type)

초기화 순서 (의존성):
    1. PromptOptimizer - 독립적
    2. FeedbackLoop - 독립적
    3. AutoOptimizer - FeedbackLoop 사용 (lazy import로 해결)
    4. UploadScheduler - FeedbackLoop 사용 가능
    5. UtopiaEngine - 모든 모듈 사용

주의사항:
    - 모든 모듈은 lazy import로 순환 참조 방지
    - 초기화 중 다른 모듈 접근 시 get_* 메서드 사용
"""
import logging
from typing import Dict, Any, Optional, Callable
import threading

logger = logging.getLogger(__name__)


class InstanceManager:
    """
    전역 인스턴스 관리자

    모든 유토피아 모듈의 인스턴스를 중앙에서 관리하여
    데이터 일관성과 메모리 효율성을 보장

    v54.7.2: 순환 참조 방지 및 초기화 순서 관리
    """

    _lock = threading.Lock()

    def __init__(self):
        # 모듈별 인스턴스 캐시
        self._auto_optimizer: Dict[str, Any] = {}
        self._prompt_optimizer: Dict[str, Any] = {}
        self._upload_scheduler: Dict[str, Any] = {}
        self._feedback_loop: Dict[str, Any] = {}
        self._utopia_engine: Dict[str, Any] = {}

        # 기본 데이터 디렉토리
        self._default_data_dir: Optional[str] = None

        # v54.7.2: 초기화 중 플래그 (순환 참조 감지용)
        self._initializing: Dict[str, bool] = {}

    def _get_cache_key(self, channel_type: str, channel_id: str = None) -> str:
        """캐시 키 생성"""
        if channel_id:
            return f"{channel_type}:{channel_id}"
        return channel_type

    def _get_data_dir(self, data_dir: str = None) -> str:
        """데이터 디렉토리 가져오기"""
        if data_dir:
            return data_dir

        if self._default_data_dir:
            return self._default_data_dir

        try:
            from config.settings import config
            self._default_data_dir = config.DATA_DIR
            return self._default_data_dir
        except Exception:
            return "data"

    def get_auto_optimizer(
        self,
        data_dir: str = None,
        channel_type: str = "horror"
    ):
        """
        AutoOptimizer 인스턴스 가져오기

        v54.7.2: 순환 참조 방지
        - AutoOptimizer → FeedbackLoop 의존성 있음
        - FeedbackLoop이 먼저 초기화되어야 함

        v54.7.3: None 반환 시 호출자 주의사항
        - 초기화 중 순환 참조 감지 시 None 반환
        - 호출자는 반드시 None 체크 필요
        - None 반환 시 해당 기능 스킵 또는 로깅

        Returns:
            AutoOptimizer | None: 순환 참조 감지 시 None
        """
        key = self._get_cache_key(channel_type)
        init_key = f"auto_optimizer:{key}"

        with self._lock:
            # v54.7.3: 순환 참조 감지 - 상세 로깅
            if self._initializing.get(init_key):
                logger.warning(
                    f"순환 참조 감지: AutoOptimizer ({key}) - "
                    f"호출자는 None 반환을 처리해야 함"
                )
                return None

            if key not in self._auto_optimizer:
                self._initializing[init_key] = True
                try:
                    from utils.auto_optimizer import AutoOptimizer
                    self._auto_optimizer[key] = AutoOptimizer(
                        self._get_data_dir(data_dir),
                        channel_type
                    )
                finally:
                    self._initializing[init_key] = False

            return self._auto_optimizer[key]

    def get_prompt_optimizer(
        self,
        data_dir: str = None,
        channel_type: str = "horror",
        channel_id: str = None
    ):
        """PromptOptimizer 인스턴스 가져오기"""
        key = self._get_cache_key(channel_type, channel_id)

        with self._lock:
            if key not in self._prompt_optimizer:
                from utils.prompt_optimizer import PromptOptimizer
                self._prompt_optimizer[key] = PromptOptimizer(
                    self._get_data_dir(data_dir),
                    channel_type,
                    channel_id
                )
            return self._prompt_optimizer[key]

    def get_upload_scheduler(
        self,
        data_dir: str = None,
        channel_type: str = "horror"
    ):
        """UploadScheduler 인스턴스 가져오기"""
        key = self._get_cache_key(channel_type)

        with self._lock:
            if key not in self._upload_scheduler:
                from utils.upload_scheduler import UploadScheduler
                self._upload_scheduler[key] = UploadScheduler(
                    self._get_data_dir(data_dir),
                    channel_type
                )
            return self._upload_scheduler[key]

    def get_feedback_loop(
        self,
        data_dir: str = None,
        channel_type: str = "horror"
    ):
        """
        FeedbackLoop 인스턴스 가져오기

        v54.7.2: 순환 참조 방지
        - FeedbackLoop → AutoOptimizer 의존성 있음 (trigger_auto_improvement에서)
        - 초기화 중에는 AutoOptimizer 접근 차단

        v54.7.3: None 반환 시 호출자 주의사항
        - 초기화 중 순환 참조 감지 시 None 반환
        - 호출자는 반드시 None 체크 필요
        - None 반환 시 해당 기능 스킵 또는 로깅

        Returns:
            FeedbackLoop | None: 순환 참조 감지 시 None
        """
        key = self._get_cache_key(channel_type)
        init_key = f"feedback_loop:{key}"

        with self._lock:
            # v54.7.3: 순환 참조 감지 - 상세 로깅
            if self._initializing.get(init_key):
                logger.warning(
                    f"순환 참조 감지: FeedbackLoop ({key}) - "
                    f"호출자는 None 반환을 처리해야 함"
                )
                return None

            if key not in self._feedback_loop:
                self._initializing[init_key] = True
                try:
                    from utils.feedback_loop import FeedbackLoop
                    self._feedback_loop[key] = FeedbackLoop(
                        self._get_data_dir(data_dir),
                        channel_type
                    )
                finally:
                    self._initializing[init_key] = False

            return self._feedback_loop[key]

    def get_utopia_engine(
        self,
        data_dir: str = None,
        channel_type: str = "horror",
        channel_id: str = None,
        media_factory_getter: Callable[[], Any] = None  # v57.6.8: 의존성 주입
    ):
        """
        UtopiaEngine 인스턴스 가져오기

        v54.8.0: channel_id 지원 (멀티채널)
        - channel_id가 있으면: 채널별 독립 인스턴스
        - channel_id가 없으면: 레거시 모드 (타입별 인스턴스)

        v57.6.8: media_factory_getter 의존성 주입 (레이어 분리)

        Args:
            data_dir: 기본 데이터 디렉토리
            channel_type: 채널 타입
            channel_id: 채널 고유 ID (v54.8.0)
            media_factory_getter: MediaFactory 인스턴스 반환 콜백 (v57.6.8)

        Returns:
            UtopiaEngine: 인스턴스
        """
        # v54.8.0: channel_id가 있으면 채널별 키, 없으면 타입별 키
        key = self._get_cache_key(channel_type, channel_id)

        with self._lock:
            if key not in self._utopia_engine:
                from utils.utopia_engine import UtopiaEngine
                self._utopia_engine[key] = UtopiaEngine(
                    self._get_data_dir(data_dir),
                    channel_type,
                    channel_id,  # v54.8.0: 멀티채널 지원
                    media_factory_getter  # v57.6.8: 의존성 주입
                )
            return self._utopia_engine[key]

    def clear_instances(self, channel_type: str = None):
        """인스턴스 캐시 정리"""
        with self._lock:
            if channel_type:
                # 특정 채널 타입만 정리
                for cache in [
                    self._auto_optimizer,
                    self._prompt_optimizer,
                    self._upload_scheduler,
                    self._feedback_loop,
                    self._utopia_engine
                ]:
                    keys_to_remove = [k for k in cache if k.startswith(channel_type)]
                    for k in keys_to_remove:
                        del cache[k]
            else:
                # 전체 정리
                self._auto_optimizer.clear()
                self._prompt_optimizer.clear()
                self._upload_scheduler.clear()
                self._feedback_loop.clear()
                self._utopia_engine.clear()

    def get_all_instances(self, channel_type: str) -> Dict[str, Any]:
        """특정 채널 타입의 모든 인스턴스 가져오기"""
        return {
            "auto_optimizer": self._auto_optimizer.get(channel_type),
            "prompt_optimizer": self._prompt_optimizer.get(channel_type),
            "upload_scheduler": self._upload_scheduler.get(channel_type),
            "feedback_loop": self._feedback_loop.get(channel_type),
            "utopia_engine": self._utopia_engine.get(channel_type),
        }


# 전역 싱글톤 인스턴스
_instance_manager: Optional[InstanceManager] = None
_manager_lock = threading.Lock()


def get_instance_manager() -> InstanceManager:
    """InstanceManager 싱글톤 가져오기"""
    global _instance_manager

    if _instance_manager is None:
        with _manager_lock:
            if _instance_manager is None:
                _instance_manager = InstanceManager()

    return _instance_manager
