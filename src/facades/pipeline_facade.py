# src/facades/pipeline_facade.py
"""
v57.6.8: Pipeline Facade - 영상 생성 파이프라인 통합 인터페이스

modules_pro 레이어의 통합 진입점:
- MediaFactory (영상 생성)
- ScenarioPlanner (시나리오 생성)
- RemotionAssembler (렌더링)

GUI에서 직접 modules_pro를 import하지 않고 이 Facade를 통해 접근
"""

import logging
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ProductionMode(Enum):
    """생산 모드"""
    FULL = "full"           # 전체 생성
    TEST = "test"           # 테스트 모드 (빠른 생성)
    THUMBNAIL_ONLY = "thumbnail"  # 썸네일만


@dataclass
class ProductionResult:
    """생산 결과"""
    success: bool
    video_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    error: Optional[str] = None
    stats: Optional[Dict[str, Any]] = None


class PipelineFacade:
    """
    영상 생성 파이프라인 Facade

    모든 영상 생성 관련 기능을 단일 인터페이스로 제공
    GUI는 이 클래스만 사용하면 됨
    """

    _instance: Optional['PipelineFacade'] = None

    def __init__(self):
        """초기화 - 내부 모듈은 지연 로드"""
        self._media_factory = None
        self._scenario_planner = None
        self._style_getter: Optional[Callable[[str], dict]] = None

        # 콜백
        self.on_progress: Optional[Callable[[str, float], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None

    # =========================================================
    # 의존성 주입
    # =========================================================

    def set_style_getter(self, getter: Callable[[str], dict]):
        """
        GUI에서 스타일 getter 주입

        Args:
            getter: (channel) -> {bgm_volume, subtitle_size, speaker_size}
        """
        self._style_getter = getter
        logger.info("[PipelineFacade] style_getter 설정됨")

    # =========================================================
    # 지연 로드 프로퍼티
    # =========================================================

    def _get_media_factory(self, channel: str = "daily_life_toon"):
        """MediaFactory 지연 로드"""
        from modules_pro.media_factory import MediaFactory
        return MediaFactory(
            channel=channel,
            style_getter=self._style_getter
        )

    def _get_scenario_planner(self):
        """ScenarioPlanner 지연 로드"""
        if self._scenario_planner is None:
            from modules_pro.scenario_planner import ScenarioPlanner
            self._scenario_planner = ScenarioPlanner()
        return self._scenario_planner

    # =========================================================
    # 고수준 API - GUI에서 사용
    # =========================================================

    def generate_scenario(
        self,
        topic: str,
        channel: str = "daily_life_toon",
        style: str = None,
        count: int = 1
    ) -> Dict[str, Any]:
        """
        시나리오 생성

        Args:
            topic: 주제
            channel: 채널 타입
            style: 스타일 (touching, makjang 등)
            count: 생성 개수

        Returns:
            생성된 시나리오 데이터
        """
        try:
            planner = self._get_scenario_planner()
            result = planner.generate(
                topic=topic,
                channel=channel,
                style=style,
                count=count
            )
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"[PipelineFacade] 시나리오 생성 실패: {e}")
            return {"success": False, "error": str(e)}

    def generate_video(
        self,
        topic: str,
        channel: str = "daily_life_toon",
        mode: ProductionMode = ProductionMode.FULL,
        style: str = None,
        on_progress: Callable[[str, float], None] = None
    ) -> ProductionResult:
        """
        영상 생성 (통합 API)

        Args:
            topic: 주제
            channel: 채널 타입
            mode: 생산 모드
            style: 스타일
            on_progress: 진행 콜백 (message, percent)

        Returns:
            ProductionResult
        """
        try:
            self._log(f"영상 생성 시작: {topic} ({channel})")

            # 1. MediaFactory 생성
            factory = self._get_media_factory(channel)

            # 2. 모드 설정
            if mode == ProductionMode.TEST:
                factory.mode = "test"
            elif style:
                factory.mode = style

            # 3. 진행 콜백 설정
            if on_progress:
                factory.on_progress = on_progress

            # 4. 영상 생성
            result = factory.produce(topic)

            if result and result.get("success"):
                return ProductionResult(
                    success=True,
                    video_path=result.get("video_path"),
                    thumbnail_path=result.get("thumbnail_path"),
                    stats=result.get("stats")
                )
            else:
                return ProductionResult(
                    success=False,
                    error=result.get("error", "Unknown error")
                )

        except Exception as e:
            logger.error(f"[PipelineFacade] 영상 생성 실패: {e}")
            return ProductionResult(success=False, error=str(e))

    def generate_thumbnail_only(
        self,
        topic: str,
        channel: str = "daily_life_toon",
        style: str = None
    ) -> ProductionResult:
        """썸네일만 생성"""
        return self.generate_video(
            topic=topic,
            channel=channel,
            mode=ProductionMode.THUMBNAIL_ONLY,
            style=style
        )

    # =========================================================
    # v60.1.0 Phase F1: GUI 통합 API
    # =========================================================

    def produce_video_with_gui(
        self,
        channel: str,
        mode: str = "touching",
        quality=None,
        **callbacks,
    ) -> 'ProductionResult':
        """GUI의 _production_worker가 호출하는 통합 진입점

        Args:
            channel: 채널 타입
            mode: 장르 모드
            quality: QualityPreset (optional)
            **callbacks: progress_callback, log_callback, project_name 등

        Returns:
            ProductionResult
        """
        try:
            factory = self._get_media_factory(channel)
            if quality:
                factory.quality = quality
            # produce_video_with_gui는 kwargs로 전달
            result = factory.produce_video_with_gui(**callbacks)
            return ProductionResult(
                success=True,
                video_path=result if isinstance(result, str) else None,
                stats=result if isinstance(result, dict) else None,
            )
        except Exception as e:
            logger.error(f"[PipelineFacade] produce_video_with_gui 실패: {e}")
            return ProductionResult(success=False, error=str(e))

    def produce_batch(
        self,
        channel: str,
        json_paths: List[str] = None,
        **callbacks,
    ) -> List['ProductionResult']:
        """배치 생산 — GUI의 _queue_worker가 호출"""
        try:
            factory = self._get_media_factory(channel)
            results = factory.produce_batch(json_paths=json_paths, **callbacks)
            return [
                ProductionResult(success=True, video_path=r)
                if isinstance(r, str) else ProductionResult(success=False, error=str(r))
                for r in (results or [])
            ]
        except Exception as e:
            logger.error(f"[PipelineFacade] produce_batch 실패: {e}")
            return [ProductionResult(success=False, error=str(e))]

    def cancel(self):
        """생산 중단"""
        if self._media_factory:
            self._media_factory.cancel()
            self._log("생산 중단 요청")

    def pause(self):
        """생산 일시정지"""
        if self._media_factory:
            self._media_factory.pause()
            self._log("생산 일시정지")

    def resume(self):
        """생산 재개"""
        if self._media_factory:
            self._media_factory.resume()
            self._log("생산 재개")

    def set_cancellation_token(self, token):
        """CancellationToken 설정"""
        if self._media_factory:
            self._media_factory.set_cancellation_token(token)

    # =========================================================
    # 하위 모듈 직접 접근 (필요 시)
    # =========================================================

    def get_media_factory(self, channel: str = "daily_life_toon"):
        """MediaFactory 인스턴스 반환 (고급 사용)"""
        return self._get_media_factory(channel)

    def get_scenario_planner(self):
        """ScenarioPlanner 인스턴스 반환 (고급 사용)"""
        return self._get_scenario_planner()

    # =========================================================
    # 유틸리티
    # =========================================================

    def _log(self, message: str):
        """로그 출력"""
        logger.info(f"[PipelineFacade] {message}")
        if self.on_log:
            self.on_log(message)


# =========================================================
# 싱글톤 접근자
# =========================================================

_facade_instance: Optional[PipelineFacade] = None


def get_pipeline_facade() -> PipelineFacade:
    """PipelineFacade 싱글톤 인스턴스 반환"""
    global _facade_instance
    if _facade_instance is None:
        _facade_instance = PipelineFacade()
    return _facade_instance
