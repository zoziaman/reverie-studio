# src/modules_pro/video_models.py
# ============================================================
# v56.1: 영상 제작 관련 모델/유틸리티 클래스
# media_factory.py에서 분리
# ============================================================
import os
import json
import time
import random
import logging
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable

# 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("video_models")
except ImportError:
    logger = logging.getLogger("video_models")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)


# ============================================================
# 품질 프리셋 Enum
# ============================================================
class QualityPreset(Enum):
    FAST = "fast"           # 빠른 미리보기
    STANDARD = "standard"   # 표준 (기본)
    HIGH = "high"           # 고품질


# ============================================================
# v57.1: 렌더링 엔진 Enum (v57.4: Remotion 추가)
# ============================================================
class RenderEngine(Enum):
    """
    렌더링 엔진 선택

    - AUTO: GPU 가용성 체크 후 자동 선택 (권장)
    - GPU: NVENC 강제 사용 (RTX 시리즈 필요)
    - CPU: libx264 사용 (호환성 최고)
    - REMOTION: React 기반 렌더링 (Ken Burns 효과, 병렬 처리)
    """
    AUTO = "auto"       # 자동 선택 (GPU 가능하면 GPU)
    GPU = "gpu"         # NVENC 강제 (h264_nvenc)
    CPU = "cpu"         # libx264 (호환성 최고)
    REMOTION = "remotion"  # v57.4: React/Remotion 기반 렌더링


# ============================================================
# 렌더링 설정 DataClass
# ============================================================
@dataclass
class RenderSettings:
    """
    렌더링 설정

    v57.1: engine 필드 추가 (AUTO/GPU/CPU)
    - 기존 use_gpu, codec 필드는 하위 호환성을 위해 유지
    - engine 필드가 우선 적용됨
    """
    preset: str = "medium"          # ffmpeg preset (CPU: medium, GPU: p4)
    bitrate: str = "5000k"          # 비트레이트
    threads: int = 4                # 스레드 수
    use_gpu: bool = False           # GPU 인코딩 사용 (레거시, engine 우선)
    codec: str = "libx264"          # 코덱 (레거시, engine 우선)
    engine: RenderEngine = field(default=RenderEngine.AUTO)  # v57.1: 렌더링 엔진

    @classmethod
    def from_quality(cls, quality: QualityPreset) -> 'RenderSettings':
        """품질 프리셋에서 설정 생성"""
        import multiprocessing
        cpu_count = multiprocessing.cpu_count()

        if quality == QualityPreset.FAST:
            return cls(
                preset="ultrafast",
                bitrate="2500k",
                threads=max(4, cpu_count - 1),
                use_gpu=False,
                codec="libx264",
                engine=RenderEngine.AUTO
            )
        elif quality == QualityPreset.HIGH:
            return cls(
                preset="slow",
                bitrate="8000k",
                threads=max(4, min(cpu_count - 1, 8)),
                use_gpu=False,
                codec="libx264",
                engine=RenderEngine.AUTO
            )
        else:  # STANDARD
            return cls(
                preset="medium",
                bitrate="5000k",
                threads=max(4, min(cpu_count - 1, 8)),
                use_gpu=False,
                codec="libx264",
                engine=RenderEngine.AUTO
            )

    @classmethod
    def from_engine(cls, engine: RenderEngine, quality: QualityPreset = QualityPreset.STANDARD) -> 'RenderSettings':
        """
        v57.1: 엔진 선택에 맞는 설정 생성 (v57.4: Remotion 추가)

        Args:
            engine: RenderEngine.AUTO, GPU, CPU, 또는 REMOTION
            quality: 품질 프리셋

        Returns:
            RenderSettings: 엔진에 최적화된 설정
        """
        import multiprocessing
        cpu_count = multiprocessing.cpu_count()

        # 품질별 비트레이트
        bitrate_map = {
            QualityPreset.FAST: "2500k",
            QualityPreset.STANDARD: "5000k",
            QualityPreset.HIGH: "8000k",
        }

        # v57.4: Remotion 엔진 설정
        if engine == RenderEngine.REMOTION:
            # Remotion은 자체 h264 인코딩 사용, 최종 결합만 MoviePy
            return cls(
                preset="medium",
                bitrate=bitrate_map.get(quality, "5000k"),
                threads=max(4, min(cpu_count - 1, 8)),
                use_gpu=False,
                codec="libx264",
                engine=RenderEngine.REMOTION
            )
        elif engine == RenderEngine.GPU:
            # NVENC 설정 (RTX 시리즈)
            # p1(fastest) ~ p7(slowest), 권장: p4(balanced)
            preset_map = {
                QualityPreset.FAST: "p1",
                QualityPreset.STANDARD: "p4",
                QualityPreset.HIGH: "p6",
            }
            return cls(
                preset=preset_map.get(quality, "p4"),
                bitrate=bitrate_map.get(quality, "5000k"),
                threads=1,  # GPU는 스레드 불필요
                use_gpu=True,
                codec="h264_nvenc",
                engine=RenderEngine.GPU
            )
        elif engine == RenderEngine.CPU:
            # libx264 설정
            preset_map = {
                QualityPreset.FAST: "ultrafast",
                QualityPreset.STANDARD: "medium",
                QualityPreset.HIGH: "slow",
            }
            return cls(
                preset=preset_map.get(quality, "medium"),
                bitrate=bitrate_map.get(quality, "5000k"),
                threads=max(4, min(cpu_count - 1, 8)),
                use_gpu=False,
                codec="libx264",
                engine=RenderEngine.CPU
            )
        else:  # AUTO
            # AUTO는 실제 렌더링 시 GPU 가용성 체크 후 결정
            return cls(
                preset="medium",  # CPU 기본값 (GPU 시 p4로 변경됨)
                bitrate=bitrate_map.get(quality, "5000k"),
                threads=max(4, min(cpu_count - 1, 8)),
                use_gpu=False,  # 런타임에 결정
                codec="libx264",  # 런타임에 결정
                engine=RenderEngine.AUTO
            )

    def get_effective_settings(self) -> tuple:
        """
        v57.1: 실제 사용될 코덱과 프리셋 반환 (GPU 가용성 체크 포함)

        Returns:
            tuple: (codec, preset, use_gpu)
        """
        if self.engine == RenderEngine.GPU:
            return ("h264_nvenc", self.preset if self.preset.startswith("p") else "p4", True)
        elif self.engine == RenderEngine.CPU:
            return ("libx264", self.preset if not self.preset.startswith("p") else "medium", False)
        else:  # AUTO
            # GPU 가용성 체크
            if self._check_nvenc_available():
                logger.info("[렌더링] AUTO 모드: NVENC GPU 인코딩 사용")
                return ("h264_nvenc", "p4", True)
            else:
                logger.info("[렌더링] AUTO 모드: libx264 CPU 인코딩 사용")
                return ("libx264", self.preset, False)

    @staticmethod
    def _check_nvenc_available() -> bool:
        """
        NVENC 사용 가능 여부 확인

        Returns:
            bool: NVENC 사용 가능하면 True
        """
        import subprocess
        import shutil
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        _si = None
        if sys.platform == 'win32':
            _si = subprocess.STARTUPINFO()
            _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            _si.wShowWindow = subprocess.SW_HIDE

        # v57.2.4: FFmpeg 경로 우선순위 수정
        # 1. 환경변수 IMAGEIO_FFMPEG_EXE
        # 2. .env의 FFMPEG_PATH (RTX 40 시리즈용 FFmpeg 6.0+)
        # 3. PATH에서 검색
        ffmpeg_path = os.environ.get("IMAGEIO_FFMPEG_EXE")

        if not ffmpeg_path:
            # .env에서 FFMPEG_PATH 확인
            try:
                from config.settings_v2 import config  # v61.1: 인스턴스 import
                if hasattr(config, 'FFMPEG_PATH') and config.FFMPEG_PATH:
                    if os.path.exists(config.FFMPEG_PATH):
                        ffmpeg_path = config.FFMPEG_PATH
                        logger.info(f"[렌더링] .env FFMPEG_PATH 사용: {ffmpeg_path}")
            except ImportError:
                pass  # config 모듈 미설치 — 시스템 PATH 사용
            except Exception as e:
                logger.debug(f"[렌더링] .env FFMPEG_PATH 조회 실패: {e}")

        if not ffmpeg_path:
            ffmpeg_path = shutil.which("ffmpeg")

        if not ffmpeg_path or not os.path.exists(ffmpeg_path):
            logger.warning("[렌더링] FFmpeg를 찾을 수 없음")
            return False

        try:
            # NVENC 인코더 존재 확인
            result = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=_no_window,
                startupinfo=_si,
            )
            if "h264_nvenc" in result.stdout:
                # 실제 인코딩 테스트 (NVENC 최소 해상도: 146x50, 안전하게 256x256 사용)
                test_result = subprocess.run(
                    [
                        ffmpeg_path, "-y",
                        "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                        "-c:v", "h264_nvenc", "-preset", "p4",
                        "-f", "null", "-"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=_no_window,
                    startupinfo=_si,
                )
                if test_result.returncode == 0:
                    logger.info("[렌더링] NVENC 테스트 성공")
                    return True
                else:
                    logger.warning(f"[렌더링] NVENC 테스트 실패: {test_result.stderr[:200]}")
            return False
        except subprocess.TimeoutExpired:
            logger.warning("[렌더링] NVENC 테스트 타임아웃")
            return False
        except Exception as e:
            logger.warning(f"[렌더링] NVENC 확인 실패: {e}")
            return False


# ============================================================
# v33: 체크포인트 시스템
# ============================================================
@dataclass
class ProductionCheckpoint:
    """제작 체크포인트"""
    project_name: str
    stage: str = "init"             # init, thumbnail, tts, images, assembly, render
    tts_completed: int = 0          # 완료된 TTS 개수
    images_completed: int = 0       # 완료된 이미지 개수
    plan_json_path: str = ""        # reusable plan json path
    script_turns: int = 0           # saved script turn count
    audio_path: str = ""            # 생성된 오디오 경로
    subtitle_data: List[Dict] = field(default_factory=list)
    image_paths: List[str] = field(default_factory=list)

    def save(self, path: str):
        """체크포인트 저장"""
        data = {
            "project_name": self.project_name,
            "stage": self.stage,
            "tts_completed": self.tts_completed,
            "images_completed": self.images_completed,
            "plan_json_path": self.plan_json_path,
            "script_turns": self.script_turns,
            "audio_path": self.audio_path,
            "subtitle_data": self.subtitle_data,
            "image_paths": self.image_paths,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[체크포인트] 저장됨: {path} (stage={self.stage})")

    @classmethod
    def load(cls, path: str) -> Optional['ProductionCheckpoint']:
        """체크포인트 로드"""
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("checkpoint payload must be a JSON object")

            project_name = (data.get("project_name") or "").strip()
            if not project_name:
                project_name = os.path.splitext(os.path.basename(path))[0].replace("_checkpoint", "") or "unknown_project"
                logger.warning(f"[체크포인트] project_name 누락 → 파일명으로 보정: {project_name}")

            subtitle_data = data.get("subtitle_data", [])
            if not isinstance(subtitle_data, list):
                subtitle_data = []

            image_paths = data.get("image_paths", [])
            if not isinstance(image_paths, list):
                image_paths = []

            cp = cls(
                project_name=project_name,
                stage=data.get("stage", "init"),
                tts_completed=data.get("tts_completed", 0),
                images_completed=data.get("images_completed", 0),
                plan_json_path=data.get("plan_json_path", "") or "",
                script_turns=int(data.get("script_turns", 0) or 0),
                audio_path=data.get("audio_path", ""),
                subtitle_data=subtitle_data,
                image_paths=image_paths,
            )
            logger.info(f"[체크포인트] 로드됨: {path} (stage={cp.stage})")
            return cp
        except Exception as e:
            logger.error(f"[체크포인트] 로드 실패: {e}")
            return None


# ============================================================
# v33: 작업 취소 플래그
# ============================================================
class CancellationToken:
    """작업 취소 토큰"""
    def __init__(self):
        self._cancelled = False
        self._paused = False
        self._lock = threading.Lock()

    def cancel(self):
        """작업 취소"""
        with self._lock:
            self._cancelled = True
        logger.warning("[취소] 작업 취소 요청됨")

    def pause(self):
        """작업 일시정지"""
        with self._lock:
            self._paused = True
        logger.info("[일시정지] 작업 일시정지됨")

    def resume(self):
        """작업 재개"""
        with self._lock:
            self._paused = False
        logger.info("[재개] 작업 재개됨")

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def wait_if_paused(self):
        """일시정지 상태면 대기"""
        while self.is_paused and not self.is_cancelled:
            time.sleep(0.5)

    def check(self) -> bool:
        """취소/일시정지 체크, 취소되면 True 반환"""
        self.wait_if_paused()
        return self.is_cancelled


# ============================================================
# v33: 지수 백오프 API 재시도 헬퍼
# ============================================================
def retry_with_backoff(
    func: Callable,
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    on_retry: Callable[[int, Exception], None] = None,
    cancellation_token: CancellationToken = None
) -> Any:
    """
    지수 백오프로 API 호출 재시도

    Args:
        func: 호출할 함수
        max_retries: 최대 재시도 횟수
        base_delay: 기본 대기 시간
        max_delay: 최대 대기 시간
        on_retry: 재시도 시 콜백
        cancellation_token: 취소 토큰

    Returns:
        함수 반환값
    """
    last_exception = None

    for attempt in range(max_retries):
        # 취소 체크
        if cancellation_token and cancellation_token.check():
            raise InterruptedError("작업이 취소되었습니다.")

        try:
            return func()
        except Exception as e:
            last_exception = e

            if attempt == max_retries - 1:
                logger.error(f"API 호출 최종 실패 (재시도 {max_retries}회): {type(e).__name__}: {str(e)[:100]}")
                raise

            # 지수 백오프 계산 (지터 추가)
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay = delay * (0.5 + random.random())

            logger.warning(f"API 재시도 {attempt+1}/{max_retries}, {delay:.1f}초 대기. 에러: {type(e).__name__}")

            if on_retry:
                on_retry(attempt + 1, e)

            time.sleep(delay)

    raise last_exception
