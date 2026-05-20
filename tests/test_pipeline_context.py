# tests/test_pipeline_context.py
"""
v60.1.0 Phase 1: PipelineContext + PipelineStepResult 단위 테스트
"""
import pytest


class TestPipelineContext:
    """PipelineContext 생성 및 기본 동작"""

    def test_context_creation(self):
        """기본 생성"""
        from pipeline.context import PipelineContext
        ctx = PipelineContext(channel="horror", mode="horror")
        assert ctx.channel == "horror"
        assert ctx.mode == "horror"
        assert ctx.target_language == "ko"

    def test_context_with_quality(self):
        """품질 프리셋 지정"""
        from pipeline.context import PipelineContext
        from modules_pro.video_models import QualityPreset
        ctx = PipelineContext(
            channel="senior",
            mode="touching",
            quality=QualityPreset.HIGH
        )
        assert ctx.quality == QualityPreset.HIGH

    def test_context_cancellation(self):
        """취소 토큰 동작"""
        from pipeline.context import PipelineContext, PipelineCancelled
        from modules_pro.video_models import CancellationToken

        token = CancellationToken()
        ctx = PipelineContext(
            channel="horror",
            mode="horror",
            cancellation_token=token
        )

        # 취소 전: 정상
        ctx.check_cancelled()  # 예외 없음

        # 취소 후: PipelineCancelled 발생
        token.cancel()
        with pytest.raises(PipelineCancelled):
            ctx.check_cancelled()

    def test_context_no_token(self):
        """취소 토큰 없을 때 check_cancelled는 무시"""
        from pipeline.context import PipelineContext
        ctx = PipelineContext(channel="test", mode="test")
        ctx.check_cancelled()  # 토큰 없으면 그냥 통과

    def test_context_progress_callback(self):
        """진행률 콜백 호출"""
        from pipeline.context import PipelineContext

        called = []
        def on_progress(stage, progress, message=""):
            called.append((stage, progress))

        ctx = PipelineContext(
            channel="test",
            mode="test",
            progress_callback=on_progress
        )
        ctx.update_progress("tts", 0.5, "TTS 진행 중")
        assert len(called) == 1
        assert called[0] == ("tts", 0.5)


class TestPipelineStepResult:
    """PipelineStepResult 표준 반환값"""

    def test_success_result(self):
        """성공 결과"""
        from pipeline.context import PipelineStepResult
        result = PipelineStepResult(
            success=True,
            data=("/path/to/audio.wav", [{"text": "hello"}]),
            stage="tts"
        )
        assert result.success is True
        assert result.error is None
        assert result.has_warnings is False

    def test_failure_result(self):
        """실패 결과"""
        from pipeline.context import PipelineStepResult
        result = PipelineStepResult(
            success=False,
            error=RuntimeError("SD API timeout"),
            stage="images"
        )
        assert result.success is False
        assert isinstance(result.error, RuntimeError)

    def test_fallback_result(self):
        """부분 성공 (fallback 사용)"""
        from pipeline.context import PipelineStepResult
        result = PipelineStepResult(
            success=True,
            data=["/img1.png", "/img2.png", "/fallback.png"],
            fallback_used=True,
            warnings=["이미지 3장 중 1장 fallback 사용"],
            retry_count=3,
            stage="images"
        )
        assert result.success is True
        assert result.fallback_used is True
        assert result.has_warnings is True
        assert result.retry_count == 3


class TestPipelineCheckpoint:
    """PipelineCheckpoint 중단/재개"""

    def test_checkpoint_resume_check(self):
        """단계별 재개 가능 여부"""
        from pipeline.context import PipelineCheckpoint
        cp = PipelineCheckpoint(stage="tts")
        assert cp.can_resume_from("init") is True
        assert cp.can_resume_from("tts") is True
        assert cp.can_resume_from("images") is False
        assert cp.can_resume_from("render") is False

    def test_checkpoint_done(self):
        """완료된 체크포인트"""
        from pipeline.context import PipelineCheckpoint
        cp = PipelineCheckpoint(stage="done")
        assert cp.can_resume_from("init") is True
        assert cp.can_resume_from("render") is True

    def test_checkpoint_invalid_stage(self):
        """잘못된 단계명"""
        from pipeline.context import PipelineCheckpoint
        cp = PipelineCheckpoint(stage="tts")
        assert cp.can_resume_from("nonexistent") is False


class TestPipelineUtils:
    """pipeline_utils 유틸리티"""

    def test_safe_print(self):
        """safe_print 호출 (에러 없이)"""
        from pipeline.pipeline_utils import safe_print
        safe_print("테스트 메시지")  # cp949 호환 확인
        safe_print("English message")

    def test_sanitize_for_path(self):
        """파일명 sanitize"""
        from pipeline.pipeline_utils import sanitize_for_path
        assert sanitize_for_path("hello/world") == "hello_world"
        assert sanitize_for_path('test:"file"') == "test_file"
        assert sanitize_for_path("") == "unknown"
        assert sanitize_for_path("normal_name") == "normal_name"

    def test_gui_log_callback(self):
        """GUI 로그 콜백 설정/해제"""
        from pipeline.pipeline_utils import set_gui_log_callback, safe_print

        logs = []
        set_gui_log_callback(lambda msg: logs.append(msg))
        safe_print("test log")
        assert len(logs) == 1
        assert logs[0] == "test log"

        # 해제
        set_gui_log_callback(None)
        safe_print("after clear")
        assert len(logs) == 1  # 추가 안 됨

    def test_ensure_dir(self, tmp_path):
        """ensure_dir 디렉토리 생성"""
        from pipeline.pipeline_utils import ensure_dir
        new_dir = str(tmp_path / "sub" / "dir")
        result = ensure_dir(new_dir)
        assert os.path.isdir(result)

    def test_get_ffmpeg_path(self):
        """FFmpeg 경로 반환 (빈 문자열 아님)"""
        from pipeline.pipeline_utils import get_ffmpeg_path
        path = get_ffmpeg_path()
        assert isinstance(path, str)
        assert len(path) > 0
