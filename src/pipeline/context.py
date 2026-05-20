# src/pipeline/context.py
"""
v60.1.0: 파이프라인 공유 컨텍스트 및 표준 결과 타입

media_factory.py의 self.xxx 변수 41개를 4개 계층으로 분류:
- PipelineContext: 모든 모듈이 공유하는 불변 설정
- TTSState: TTSManager 전용 (tts_manager.py에서 정의)
- ImageState: ImagePipeline 전용 (image_pipeline.py에서 정의)
- RunState: 실행 중 동적 생성 (Orchestrator 소유)
"""
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum

# video_models에서 공유 타입 가져오기
from modules_pro.video_models import (
    QualityPreset,
    RenderSettings,
    RenderEngine,
    CancellationToken,
)

try:
    from utils.logger import get_logger
    logger = get_logger("pipeline.context")
except ImportError:
    logger = logging.getLogger("pipeline.context")


# ============================================================
# 파이프라인 취소 예외
# ============================================================

class PipelineCancelled(Exception):
    """사용자에 의한 파이프라인 취소"""
    pass


# ============================================================
# PipelineStepResult: 모든 파이프라인 단계의 표준 반환값
# ============================================================

@dataclass
class PipelineStepResult:
    """
    모든 파이프라인 단계의 표준 반환값.

    각 모듈은 자체 에러를 처리하고, Orchestrator에 이 결과를 반환.
    Orchestrator는 success/fallback_used/warnings를 보고 다음 단계 진행 여부 결정.

    사용 예시:
        # 성공
        return PipelineStepResult(success=True, data=(audio_path, subtitles))

        # 실패
        return PipelineStepResult(success=False, error=TTSError("timeout"))

        # 부분 성공 (fallback 사용)
        return PipelineStepResult(
            success=True, data=image_paths,
            fallback_used=True, warnings=["3장 fallback 이미지 사용"]
        )
    """
    success: bool = False
    data: Any = None                       # 성공 시 결과 데이터
    warnings: List[str] = field(default_factory=list)   # 부분 성공 시 경고
    fallback_used: bool = False            # fallback 사용 여부
    retry_count: int = 0                   # 재시도 횟수
    error: Optional[Exception] = None      # 실패 시 예외
    stage: str = ""                        # 어느 단계에서 발생했는지

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


# ============================================================
# PipelineCheckpoint: 체크포인트 (중단/재개 지원)
# ============================================================

@dataclass
class PipelineCheckpoint:
    """파이프라인 체크포인트 — 중단 시 재개 지점"""

    # 완료된 단계
    stage: str = "init"                    # "init", "thumbnail", "tts", "images", "render"
    timestamp: Optional[str] = None

    # 각 단계 결과 (완료된 것만 저장)
    thumbnail_result: Optional[PipelineStepResult] = None
    tts_result: Optional[PipelineStepResult] = None
    image_results: Optional[List[PipelineStepResult]] = None

    # 재개에 필요한 중간 데이터
    audio_path: Optional[str] = None
    subtitle_data: Optional[List] = None
    image_paths: Optional[List[str]] = None

    STAGE_ORDER = ["init", "thumbnail", "tts", "images", "render", "done"]

    def can_resume_from(self, stage: str) -> bool:
        """주어진 단계부터 재개 가능한지 확인"""
        if stage not in self.STAGE_ORDER or self.stage not in self.STAGE_ORDER:
            return False
        return self.STAGE_ORDER.index(self.stage) >= self.STAGE_ORDER.index(stage)


# ============================================================
# PipelineContext: 모든 파이프라인 모듈이 공유하는 설정
# ============================================================

@dataclass
class PipelineContext:
    """
    모든 파이프라인 모듈이 공유하는 불변 설정.

    Orchestrator.__init__에서 생성하고 각 하위 모듈에 주입.
    하위 모듈은 ctx.xxx로 읽기만 함 (write는 Orchestrator만).

    계층 1 변수:
        channel, mode, quality, render_settings, target_language,
        cancellation_token, checkpoint, styles, branding
    """
    # === 핵심 설정 (모든 모듈이 READ) ===
    channel: str = ""
    mode: str = ""
    quality: QualityPreset = QualityPreset.STANDARD
    render_settings: RenderSettings = field(default_factory=lambda: RenderSettings.from_quality(QualityPreset.STANDARD))
    target_language: str = "ko"

    # === 제어 토큰 ===
    cancellation_token: Optional[CancellationToken] = None
    checkpoint: Optional[PipelineCheckpoint] = None

    # === 설정 데이터 (read-only) ===
    styles: Dict[str, Any] = field(default_factory=dict)
    branding: Dict[str, Any] = field(default_factory=dict)

    # === 런타임 상태 (Orchestrator만 write) ===
    channel_id: Optional[str] = None
    current_script_list: Optional[List] = None
    project_name: Optional[str] = None

    # === 콜백 ===
    progress_callback: Optional[Any] = None  # Callable[[str, float], None]
    thumbnail_callback: Optional[Any] = None
    log_callback: Optional[Any] = None

    def check_cancelled(self):
        """파이프라인 중단 체크 — 취소 시 PipelineCancelled 발생"""
        if self.cancellation_token and self.cancellation_token.is_cancelled:
            raise PipelineCancelled("사용자에 의해 파이프라인이 취소되었습니다")

    def check_paused(self, timeout: float = 0.5):
        """일시정지 대기 — 재개될 때까지 블로킹"""
        if not self.cancellation_token:
            return
        while self.cancellation_token.is_paused:
            self.check_cancelled()
            import time
            time.sleep(timeout)

    def update_progress(self, stage: str, progress: float, message: str = ""):
        """진행률 업데이트 (콜백이 있으면 GUI에 전달)"""
        if self.progress_callback:
            try:
                self.progress_callback(stage, progress, message)
            except Exception as e:
                # GUI 콜백 실패는 파이프라인을 중단시키면 안 됨
                logging.getLogger(__name__).debug(f"progress_callback 실패 (무시): {e}")
