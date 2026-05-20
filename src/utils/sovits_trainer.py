# src/utils/sovits_trainer.py
"""
v35 - SoVITS 학습 통합 백엔드

외부 프로세스 호출 방식:
- Reverie 환경에 학습 라이브러리 설치 X (버전 꼬임 방지)
- GPT-SoVITS의 파이썬 실행파일과 스크립트를 subprocess로 호출
- Reverie는 'GUI 껍데기', 실제 학습은 SoVITS 원본 엔진이 수행

실시간 로그 파싱:
- stdout을 실시간으로 읽어 진행률 업데이트
- Epoch, Loss 등 파싱하여 GUI에 전달
- 비동기 처리로 GUI 블로킹 방지
"""

import os
import sys
import re
import json
import time
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional, Dict, List, Callable, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from datetime import datetime

# 로깅
try:
    from utils.logger import get_logger
    logger = get_logger(__name__)
except Exception:
    import logging
    logger = logging.getLogger(__name__)

# Config
try:
    from config.settings import config
except Exception:
    config = None


class TrainingStage(Enum):
    """학습 단계"""
    IDLE = auto()           # 대기
    VALIDATING = auto()     # 음성 파일 검증
    SLICING = auto()        # 음성 슬라이싱
    ASR = auto()            # 음성→텍스트 변환
    TEXT_PROCESS = auto()   # 텍스트 처리 (1-get-text)
    HUBERT = auto()         # 오디오 피처 추출 (2-get-hubert)
    SEMANTIC = auto()       # 시멘틱 토큰 추출 (3-get-semantic)
    GPT_TRAIN = auto()      # GPT 모델 학습
    SOVITS_TRAIN = auto()   # SoVITS 모델 학습
    EXTRACTING = auto()     # 모델 추출/저장
    COMPLETED = auto()      # 완료
    FAILED = auto()         # 실패
    CANCELLED = auto()      # 취소


@dataclass
class TrainingProgress:
    """학습 진행 상태"""
    stage: TrainingStage = TrainingStage.IDLE
    stage_progress: float = 0.0       # 현재 단계 진행률 (0~100)
    overall_progress: float = 0.0     # 전체 진행률 (0~100)
    current_epoch: int = 0
    total_epochs: int = 0
    current_loss: float = 0.0
    elapsed_seconds: int = 0
    eta_seconds: int = 0              # 예상 남은 시간
    message: str = ""
    error: Optional[str] = None


@dataclass
class TrainingConfig:
    """학습 설정"""
    # 기본 정보
    model_name: str = ""
    model_description: str = ""

    # 입력 경로
    audio_folder: str = ""            # 원본 음성 폴더

    # 출력 경로 (자동 설정)
    output_folder: str = ""           # 학습 결과 저장 폴더

    # 슬라이싱 설정
    slice_threshold: int = -40        # 무음 감지 임계값 (dB)
    slice_min_length: int = 5000      # 최소 클립 길이 (ms)
    slice_min_interval: int = 300     # 최소 무음 간격 (ms)
    slice_hop_size: int = 20          # 분석 호프 크기 (ms)
    slice_max_sil_kept: int = 500     # 최대 무음 유지 (ms)

    # ASR 설정
    asr_model: str = "faster-whisper"
    asr_model_size: str = "large-v3"
    asr_language: str = "ko"
    asr_precision: str = "float16"

    # 학습 설정 (8GB VRAM 기준 최적화)
    gpt_epochs: int = 20              # batch_size 줄이면 epochs 늘려야 함
    sovits_epochs: int = 12
    batch_size: int = 2               # 8GB VRAM 안전 기본값
    learning_rate: float = 0.0002     # batch_size 줄이면 LR 살짝 올려도 됨
    save_every_n_epoch: int = 4

    # 학습 품질 프리셋 (8GB VRAM 최적화)
    quality_preset: str = "normal"    # quick, normal, high

    # GPU 설정
    gpu_id: str = "0"

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'TrainingConfig':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_preset(cls, preset: str, model_name: str, audio_folder: str) -> 'TrainingConfig':
        """프리셋으로 설정 생성"""
        # 8GB VRAM 최적화 프리셋
        presets = {
            "quick": {"gpt_epochs": 10, "sovits_epochs": 6, "batch_size": 2, "learning_rate": 0.0003},
            "normal": {"gpt_epochs": 20, "sovits_epochs": 12, "batch_size": 2, "learning_rate": 0.0002},
            "high": {"gpt_epochs": 40, "sovits_epochs": 24, "batch_size": 1, "learning_rate": 0.0001},
        }
        cfg = cls(
            model_name=model_name,
            audio_folder=audio_folder,
            quality_preset=preset,
            **presets.get(preset, presets["normal"])
        )
        return cfg


class SoVITSTrainer:
    """
    GPT-SoVITS 학습 관리자

    subprocess로 GPT-SoVITS 스크립트를 호출하여 학습 수행
    실시간 로그 파싱으로 진행률 추적
    """

    # 단계별 가중치 (전체 진행률 계산용)
    STAGE_WEIGHTS = {
        TrainingStage.VALIDATING: 2,
        TrainingStage.SLICING: 5,
        TrainingStage.ASR: 15,
        TrainingStage.TEXT_PROCESS: 5,
        TrainingStage.HUBERT: 10,
        TrainingStage.SEMANTIC: 8,
        TrainingStage.GPT_TRAIN: 30,
        TrainingStage.SOVITS_TRAIN: 20,
        TrainingStage.EXTRACTING: 5,
    }

    def __init__(self, gs_root: Optional[str] = None):
        """
        Args:
            gs_root: GPT-SoVITS 설치 경로 (None이면 config에서 가져옴)
        """
        self.gs_root = gs_root or (config.GS_ROOT if config else None)
        if not self.gs_root:
            raise ValueError("GPT-SoVITS 경로가 설정되지 않았습니다.")

        self.gs_root = Path(self.gs_root)
        self._validate_gs_root()

        # Python 실행 경로 (GPT-SoVITS의 runtime 사용)
        self.python_exec = self._find_python_exec()

        # 상태
        self.config: Optional[TrainingConfig] = None
        self.progress = TrainingProgress()
        self._process: Optional[subprocess.Popen] = None
        self._is_running = False
        self._is_cancelled = False
        self._start_time: Optional[float] = None

        # 콜백
        self._progress_callback: Optional[Callable[[TrainingProgress], None]] = None
        self._log_callback: Optional[Callable[[str], None]] = None

        # 스레드
        self._training_thread: Optional[threading.Thread] = None

        logger.info(f"[SoVITSTrainer] 초기화 완료: {self.gs_root}")

    def _validate_gs_root(self):
        """GPT-SoVITS 경로 검증"""
        required_paths = [
            self.gs_root / "tools",
            self.gs_root / "GPT_SoVITS",
            self.gs_root / "GPT_SoVITS" / "s1_train.py",
            self.gs_root / "GPT_SoVITS" / "s2_train.py",
        ]
        for p in required_paths:
            if not p.exists():
                raise ValueError(f"GPT-SoVITS 경로가 올바르지 않습니다. 없음: {p}")

    def _find_python_exec(self) -> str:
        """GPT-SoVITS용 Python 실행 경로 찾기"""
        # 플랫폼별 runtime 폴더의 python 우선
        import sys as _sys
        is_windows = _sys.platform == 'win32'

        if is_windows:
            runtime_python = self.gs_root / "runtime" / "python.exe"
        else:
            runtime_python = self.gs_root / "runtime" / "bin" / "python"

        if runtime_python.exists():
            return str(runtime_python)

        # 시스템 Python 사용 (경고)
        logger.warning("[SoVITSTrainer] runtime Python 없음, 시스템 Python 사용")
        return sys.executable

    def set_progress_callback(self, callback: Callable[[TrainingProgress], None]):
        """진행률 콜백 설정"""
        self._progress_callback = callback

    def set_log_callback(self, callback: Callable[[str], None]):
        """로그 콜백 설정"""
        self._log_callback = callback

    def _emit_progress(self):
        """진행률 콜백 호출"""
        if self._progress_callback:
            try:
                self._progress_callback(self.progress)
            except Exception as e:
                logger.error(f"[SoVITSTrainer] 진행률 콜백 오류: {e}")

    def _emit_log(self, message: str):
        """로그 콜백 호출"""
        if self._log_callback:
            try:
                self._log_callback(message)
            except Exception as e:
                logger.debug(f"[SoVITSTrainer] 로그 콜백 오류: {e}")
        logger.debug(f"[Train] {message}")

    def _update_progress(self, stage: TrainingStage, stage_progress: float = 0, message: str = ""):
        """진행률 업데이트"""
        self.progress.stage = stage
        self.progress.stage_progress = min(100, max(0, stage_progress))
        self.progress.message = message

        # 전체 진행률 계산
        completed_weight = sum(
            self.STAGE_WEIGHTS.get(s, 0)
            for s in TrainingStage
            if s.value < stage.value and s in self.STAGE_WEIGHTS
        )
        current_weight = self.STAGE_WEIGHTS.get(stage, 0) * (stage_progress / 100)
        total_weight = sum(self.STAGE_WEIGHTS.values())
        self.progress.overall_progress = ((completed_weight + current_weight) / total_weight) * 100

        # 경과 시간
        if self._start_time:
            self.progress.elapsed_seconds = int(time.time() - self._start_time)
            # ETA 계산
            if self.progress.overall_progress > 0:
                total_estimated = self.progress.elapsed_seconds / (self.progress.overall_progress / 100)
                self.progress.eta_seconds = max(0, int(total_estimated - self.progress.elapsed_seconds))

        self._emit_progress()

    def validate_audio_folder(self, folder_path: str) -> Tuple[bool, Dict[str, Any]]:
        """
        음성 폴더 검증

        Returns:
            (성공여부, {file_count, total_duration, files: [...], warnings: [...]})
        """
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            return False, {"error": "폴더가 존재하지 않습니다."}

        # 지원 포맷
        audio_extensions = {'.wav', '.mp3', '.flac', '.ogg', '.m4a'}

        files = []
        total_duration = 0
        warnings = []

        for f in folder.iterdir():
            if f.suffix.lower() in audio_extensions:
                # 파일 정보 수집 (실제 길이는 librosa 등이 필요하므로 간략화)
                size_mb = f.stat().st_size / (1024 * 1024)
                # 대략적인 길이 추정 (WAV 16bit 32kHz 기준)
                estimated_duration = (f.stat().st_size / (32000 * 2)) if f.suffix.lower() == '.wav' else size_mb * 60

                files.append({
                    "name": f.name,
                    "size_mb": round(size_mb, 2),
                    "estimated_duration": round(estimated_duration, 1)
                })
                total_duration += estimated_duration

        if len(files) == 0:
            return False, {"error": "폴더에 음성 파일이 없습니다."}

        if total_duration < 60:
            warnings.append("총 길이가 1분 미만입니다. 최소 10분 이상 권장됩니다.")
        elif total_duration < 600:
            warnings.append("총 길이가 10분 미만입니다. 품질 향상을 위해 더 많은 데이터를 권장합니다.")

        if len(files) < 5:
            warnings.append("파일 수가 적습니다. 더 많은 음성 파일을 권장합니다.")

        return True, {
            "file_count": len(files),
            "total_duration": round(total_duration, 1),
            "total_duration_str": f"{int(total_duration//60)}분 {int(total_duration%60)}초",
            "files": files,
            "warnings": warnings
        }

    def start_training(self, config: TrainingConfig) -> bool:
        """
        학습 시작 (비동기)

        Args:
            config: 학습 설정

        Returns:
            시작 성공 여부
        """
        if self._is_running:
            logger.warning("[SoVITSTrainer] 이미 학습 중입니다.")
            return False

        self.config = config
        self._is_running = True
        self._is_cancelled = False
        self._start_time = time.time()
        self.progress = TrainingProgress()

        # 출력 폴더 설정
        if not config.output_folder:
            config.output_folder = str(
                Path(config.audio_folder).parent / f"{config.model_name}_training"
            )

        # v35 지뢰 해제 #2: VRAM 메모리 해제 (학습 전 필수!)
        self._release_gpu_memory()

        # 비동기 학습 스레드 시작
        self._training_thread = threading.Thread(target=self._training_loop, daemon=True)
        self._training_thread.start()

        logger.info(f"[SoVITSTrainer] 학습 시작: {config.model_name}")
        return True

    def _release_gpu_memory(self):
        """
        v35 지뢰 해제 #2: GPU 메모리 해제

        학습은 VRAM을 끝까지 쥐어짜는 작업이므로,
        기존에 로드된 TTS 모델 등을 모두 언로드하고 캐시를 비워야 함
        """
        logger.info("[SoVITSTrainer] GPU 메모리 해제 중...")

        # v57.6.8: MediaFactory 직접 참조 제거 (레이어 분리)
        # MediaFactory 언로드가 필요하면 gpu_cleanup_callback 콜백으로 처리

        # 2. PyTorch CUDA 캐시 비우기
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                logger.info("[SoVITSTrainer] torch.cuda.empty_cache() 완료")

                # 현재 VRAM 사용량 로깅
                allocated = torch.cuda.memory_allocated() / (1024**3)
                reserved = torch.cuda.memory_reserved() / (1024**3)
                logger.info(f"[SoVITSTrainer] VRAM 상태: 할당={allocated:.2f}GB, 예약={reserved:.2f}GB")
        except ImportError:
            logger.debug("[SoVITSTrainer] PyTorch not available, skipping CUDA cleanup")
        except Exception as e:
            logger.warning(f"[SoVITSTrainer] CUDA 캐시 정리 실패: {e}")

        # 3. 가비지 컬렉션
        import gc
        gc.collect()
        logger.info("[SoVITSTrainer] 가비지 컬렉션 완료")

    def stop_training(self):
        """학습 중지"""
        if not self._is_running:
            return

        self._is_cancelled = True

        # 현재 프로세스 종료
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except OSError as e:
                    logger.debug(f"[SoVITSTrainer] 프로세스 kill 실패: {e}")

        self._is_running = False
        self._update_progress(TrainingStage.CANCELLED, 0, "사용자에 의해 취소됨")
        logger.info("[SoVITSTrainer] 학습 취소됨")

    def _training_loop(self):
        """학습 메인 루프 (스레드에서 실행)"""
        try:
            # 1. 검증
            self._update_progress(TrainingStage.VALIDATING, 0, "음성 파일 검증 중...")
            valid, info = self.validate_audio_folder(self.config.audio_folder)
            if not valid:
                raise Exception(f"음성 폴더 검증 실패: {info.get('error', '알 수 없는 오류')}")
            self._update_progress(TrainingStage.VALIDATING, 100, f"{info['file_count']}개 파일 검증 완료")

            if self._is_cancelled:
                return

            # 2. 슬라이싱
            self._run_slicing()

            if self._is_cancelled:
                return

            # 3. ASR
            self._run_asr()

            if self._is_cancelled:
                return

            # 4. 텍스트 처리
            self._run_text_process()

            if self._is_cancelled:
                return

            # 4.5 v59.5.11: 전처리 결과 파일명 통일 (i_part 접미사 제거)
            # 1-get-text는 2-name2text-{i_part}.txt로 생성하지만
            # s2_train의 data_utils.py는 2-name2text.txt를 기대함
            self._unify_preprocessing_filenames()

            # 5. Hubert 추출
            self._run_hubert()

            if self._is_cancelled:
                return

            # 6. Semantic 추출
            self._run_semantic()

            if self._is_cancelled:
                return

            # 6.5 v59.5.11: semantic 결과 파일명도 통일
            # 3-get-semantic은 6-name2semantic-{i_part}.tsv로 생성
            # s1_train config와 s2_train data_utils가 접미사 없는 버전 기대
            self._unify_preprocessing_filenames()

            # 7. GPT 학습
            self._run_gpt_training()

            if self._is_cancelled:
                return

            # 8. SoVITS 학습
            self._run_sovits_training()

            if self._is_cancelled:
                return

            # 9. 모델 추출 및 저장
            self._run_extraction()

            # 완료
            self._update_progress(TrainingStage.COMPLETED, 100, "학습 완료!")
            self._is_running = False
            logger.info("[SoVITSTrainer] 학습 완료")

        except Exception as e:
            self.progress.error = str(e)
            self._update_progress(TrainingStage.FAILED, 0, f"오류: {str(e)}")
            self._is_running = False
            logger.error(f"[SoVITSTrainer] 학습 실패: {e}")

    def _build_subprocess_env(self) -> Dict[str, str]:
        """
        v35 지뢰 해제 #1: 서브프로세스용 환경 변수 구성

        GPT-SoVITS 스크립트들은 내부적으로 서로 import 하므로,
        PYTHONPATH에 GS_ROOT 관련 경로들을 추가해야 모듈을 찾을 수 있음
        """
        env = os.environ.copy()

        # PYTHONPATH에 GPT-SoVITS 경로들 추가
        gs_paths = [
            str(self.gs_root),
            str(self.gs_root / "GPT_SoVITS"),
            str(self.gs_root / "GPT_SoVITS" / "BigVGAN"),
            str(self.gs_root / "tools"),
            str(self.gs_root / "tools" / "asr"),
            str(self.gs_root / "tools" / "uvr5"),
        ]

        existing_pythonpath = env.get('PYTHONPATH', '')
        new_pythonpath = os.pathsep.join(gs_paths)
        if existing_pythonpath:
            new_pythonpath = new_pythonpath + os.pathsep + existing_pythonpath

        env['PYTHONPATH'] = new_pythonpath
        env['PYTHONIOENCODING'] = 'utf-8'

        logger.debug(f"[SoVITSTrainer] PYTHONPATH 설정: {new_pythonpath[:200]}...")
        return env

    def _run_subprocess(self, cmd: List[str], stage: TrainingStage,
                        progress_parser: Optional[Callable[[str], Optional[float]]] = None,
                        env: Optional[Dict[str, str]] = None) -> bool:
        """
        서브프로세스 실행 및 로그 실시간 파싱

        Args:
            cmd: 실행 명령어
            stage: 현재 단계
            progress_parser: 로그 라인 → 진행률 파서 (None 반환 시 무시)
            env: 환경 변수 dict (None이면 기본 env 생성)  # v59.5.10

        Returns:
            성공 여부
        """
        self._emit_log(f"[{stage.name}] 실행: {' '.join(cmd[:3])}...")

        # v59.5.10: 외부에서 env를 넘기면 그대로 사용, 아니면 기본 생성
        if env is None:
            env = self._build_subprocess_env()

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=str(self.gs_root),
                env=env
            )

            # 실시간 로그 읽기
            while True:
                if self._is_cancelled:
                    self._process.terminate()
                    return False

                line = self._process.stdout.readline()
                if not line:
                    if self._process.poll() is not None:
                        break
                    continue

                line = line.strip()
                if line:
                    self._emit_log(line)

                    # 진행률 파싱
                    if progress_parser:
                        progress = progress_parser(line)
                        if progress is not None:
                            self._update_progress(stage, progress)

            return_code = self._process.wait()
            self._process = None

            if return_code != 0:
                logger.warning(f"[{stage.name}] 프로세스 종료 코드: {return_code}")
                # v59.5.10: 전처리/학습 단계에서 비정상 종료는 실패로 처리
                critical_stages = {
                    TrainingStage.TEXT_PROCESS,
                    TrainingStage.HUBERT,
                    TrainingStage.SEMANTIC,
                    TrainingStage.GPT_TRAIN,
                    TrainingStage.SOVITS_TRAIN,
                }
                if stage in critical_stages:
                    logger.error(f"[{stage.name}] 필수 단계 실패 (exit code {return_code})")
                    return False

            return True

        except Exception as e:
            logger.error(f"[{stage.name}] 프로세스 오류: {e}")
            self._process = None
            return False

    def _run_slicing(self):
        """음성 슬라이싱 실행"""
        self._update_progress(TrainingStage.SLICING, 0, "음성 파일 슬라이싱 중...")

        slice_output = Path(self.config.output_folder) / "sliced_audio"
        slice_output.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.python_exec,
            str(self.gs_root / "tools" / "slice_audio.py"),
            self.config.audio_folder,
            str(slice_output),
            str(self.config.slice_threshold),
            str(self.config.slice_min_length),
            str(self.config.slice_min_interval),
            str(self.config.slice_hop_size),
            str(self.config.slice_max_sil_kept),
            "0.9",  # max
            "0.25", # alpha
            "0",    # i_part
            "1",    # all_part
        ]

        # 슬라이싱은 진행률 파싱이 어려우므로 단순 완료 처리
        success = self._run_subprocess(cmd, TrainingStage.SLICING)
        if success:
            self._update_progress(TrainingStage.SLICING, 100, "슬라이싱 완료")
        else:
            raise Exception("슬라이싱 실패")

    def _run_asr(self):
        """ASR (음성→텍스트) 실행"""
        self._update_progress(TrainingStage.ASR, 0, "음성을 텍스트로 변환 중...")

        slice_output = Path(self.config.output_folder) / "sliced_audio"
        asr_output = Path(self.config.output_folder) / "asr_output"
        asr_output.mkdir(parents=True, exist_ok=True)

        # faster-whisper ASR 사용
        cmd = [
            self.python_exec,
            str(self.gs_root / "tools" / "asr" / "fasterwhisper_asr.py"),
            "-i", str(slice_output),
            "-o", str(asr_output),
            "-s", self.config.asr_model_size,
            "-l", self.config.asr_language,
            "-p", self.config.asr_precision,
        ]

        def parse_asr_progress(line: str) -> Optional[float]:
            # tqdm 형식: 50%|████████  | 50/100
            match = re.search(r'(\d+)%\|', line)
            if match:
                return float(match.group(1))
            return None

        success = self._run_subprocess(cmd, TrainingStage.ASR, parse_asr_progress)
        if success:
            self._update_progress(TrainingStage.ASR, 100, "ASR 완료")
        else:
            raise Exception("ASR 실패")

    def _get_exp_name(self) -> str:
        """실험 이름 (GPT-SoVITS 내부용)"""
        # 특수문자 제거하고 안전한 이름 생성
        safe_name = re.sub(r'[^\w\-]', '_', self.config.model_name)
        return f"reverie_{safe_name}"

    def _get_asr_list_path(self) -> Path:
        """ASR 결과 list 파일 경로"""
        asr_output = Path(self.config.output_folder) / "asr_output"
        # ASR 결과는 {폴더명}.list 형식으로 저장됨
        slice_folder_name = "sliced_audio"
        return asr_output / f"{slice_folder_name}.list"

    def _unify_preprocessing_filenames(self):
        """
        v59.5.11: 전처리 결과 파일명 통일

        GPT-SoVITS 전처리 스크립트는 멀티프로세싱 지원을 위해
        파일명에 i_part 접미사를 붙임:
          2-name2text-0.txt, 6-name2semantic-0.tsv
        하지만 s2_train의 data_utils.py는 접미사 없는 파일을 기대:
          2-name2text.txt, 6-name2semantic.tsv
        """
        import shutil
        exp_name = self._get_exp_name()
        log_dir = self.gs_root / "logs" / exp_name

        renames = [
            ("2-name2text-0.txt", "2-name2text.txt"),
            ("6-name2semantic-0.tsv", "6-name2semantic.tsv"),
        ]

        for src_name, dst_name in renames:
            src = log_dir / src_name
            dst = log_dir / dst_name
            if src.exists() and not dst.exists():
                shutil.copy(str(src), str(dst))
                logger.info(f"[Preprocessing] 파일명 통일: {src_name} → {dst_name}")

    def _run_text_process(self):
        """텍스트 처리 (1-get-text.py)"""
        self._update_progress(TrainingStage.TEXT_PROCESS, 0, "텍스트 처리 중...")

        exp_name = self._get_exp_name()
        asr_list = self._get_asr_list_path()
        slice_output = Path(self.config.output_folder) / "sliced_audio"
        log_dir = self.gs_root / "logs" / exp_name
        log_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.python_exec,
            str(self.gs_root / "GPT_SoVITS" / "prepare_datasets" / "1-get-text.py"),
        ]

        # v59.5.11: 1-get-text.py가 읽는 모든 환경변수 설정
        env = self._build_subprocess_env()
        env["inp_text"] = str(asr_list)
        env["inp_wav_dir"] = str(slice_output)
        env["exp_name"] = exp_name
        env["opt_dir"] = str(log_dir)
        env["bert_pretrained_dir"] = str(self.gs_root / "GPT_SoVITS" / "pretrained_models" / "chinese-roberta-wwm-ext-large")
        env["is_half"] = "True"
        env["i_part"] = "0"
        env["all_parts"] = "1"
        env["_CUDA_VISIBLE_DEVICES"] = self.config.gpu_id
        env["version"] = self.config.asr_language  # v59.5.11: ko/zh/ja/en

        success = self._run_subprocess(cmd, TrainingStage.TEXT_PROCESS, env=env)
        if success:
            self._update_progress(TrainingStage.TEXT_PROCESS, 100, "텍스트 처리 완료")
        else:
            raise Exception("텍스트 처리 실패")

    def _run_hubert(self):
        """Hubert 피처 추출 (2-get-hubert-wav32k.py)"""
        self._update_progress(TrainingStage.HUBERT, 0, "오디오 피처 추출 중...")

        exp_name = self._get_exp_name()
        asr_list = self._get_asr_list_path()
        slice_output = Path(self.config.output_folder) / "sliced_audio"
        log_dir = self.gs_root / "logs" / exp_name

        cmd = [
            self.python_exec,
            str(self.gs_root / "GPT_SoVITS" / "prepare_datasets" / "2-get-hubert-wav32k.py"),
        ]

        # v59.5.11: 2-get-hubert-wav32k.py가 읽는 모든 환경변수 설정
        env = self._build_subprocess_env()
        env["inp_text"] = str(asr_list)                   # v59.5.11: 필수!
        env["inp_wav_dir"] = str(slice_output)
        env["exp_name"] = exp_name
        env["opt_dir"] = str(log_dir)
        env["i_part"] = "0"
        env["all_parts"] = "1"
        env["_CUDA_VISIBLE_DEVICES"] = self.config.gpu_id
        # v59.5.11: 이전에 누락되어 TypeError: stat: path should be string, bytes... 발생
        env["cnhubert_base_dir"] = str(self.gs_root / "GPT_SoVITS" / "pretrained_models" / "chinese-hubert-base")
        env["is_half"] = "True"

        def parse_hubert_progress(line: str) -> Optional[float]:
            match = re.search(r'(\d+)%\|', line)
            if match:
                return float(match.group(1))
            return None

        success = self._run_subprocess(cmd, TrainingStage.HUBERT, parse_hubert_progress, env=env)
        if success:
            self._update_progress(TrainingStage.HUBERT, 100, "피처 추출 완료")
        else:
            raise Exception("Hubert 추출 실패")

    def _run_semantic(self):
        """시멘틱 토큰 추출 (3-get-semantic.py)"""
        self._update_progress(TrainingStage.SEMANTIC, 0, "시멘틱 토큰 추출 중...")

        exp_name = self._get_exp_name()
        asr_list = self._get_asr_list_path()
        log_dir = self.gs_root / "logs" / exp_name

        cmd = [
            self.python_exec,
            str(self.gs_root / "GPT_SoVITS" / "prepare_datasets" / "3-get-semantic.py"),
        ]

        # v59.5.11: 3-get-semantic.py가 읽는 모든 환경변수 설정
        env = self._build_subprocess_env()
        env["inp_text"] = str(asr_list)                   # v59.5.11: 필수!
        env["exp_name"] = exp_name
        env["opt_dir"] = str(log_dir)
        env["i_part"] = "0"
        env["all_parts"] = "1"
        env["_CUDA_VISIBLE_DEVICES"] = self.config.gpu_id
        # v59.5.11: pretrained S2 Generator 경로 (semantic 추출용)
        env["pretrained_s2G"] = str(self.gs_root / "GPT_SoVITS" / "pretrained_models" / "s2Gv3.pth")
        env["s2config_path"] = str(self.gs_root / "GPT_SoVITS" / "configs" / "s2.json")
        env["is_half"] = "True"

        def parse_semantic_progress(line: str) -> Optional[float]:
            match = re.search(r'(\d+)%\|', line)
            if match:
                return float(match.group(1))
            return None

        success = self._run_subprocess(cmd, TrainingStage.SEMANTIC, parse_semantic_progress, env=env)
        if success:
            self._update_progress(TrainingStage.SEMANTIC, 100, "시멘틱 추출 완료")
        else:
            raise Exception("시멘틱 추출 실패")

    def _create_s1_config(self) -> Path:
        """GPT 학습용 config yaml 생성"""
        exp_name = self._get_exp_name()
        log_dir = self.gs_root / "logs" / exp_name

        config = {
            "train": {
                "seed": 1234,
                "epochs": self.config.gpt_epochs,
                "batch_size": self.config.batch_size,
                "save_every_n_epoch": self.config.save_every_n_epoch,
                "precision": "16-mixed",
                "gradient_clip": 1.0,
                "if_save_latest": True,
                "if_save_every_weights": True,
                "half_weights_save_dir": str(self.gs_root / "GPT_weights_v2"),
                "exp_name": exp_name,
            },
            "optimizer": {
                "lr": self.config.learning_rate * 100,  # GPT는 LR이 더 높음
                "lr_init": 0.00001,
                "lr_end": self.config.learning_rate,
                "warmup_steps": 2000,
                "decay_steps": 40000,
            },
            "data": {
                "max_eval_sample": 8,
                "max_sec": 54,
                "num_workers": 4,
                "pad_val": 1024,
            },
            "model": {
                "vocab_size": 1025,
                "phoneme_vocab_size": 512,
                "embedding_dim": 512,
                "hidden_dim": 512,
                "head": 16,
                "linear_units": 2048,
                "n_layer": 24,
                "dropout": 0,
                "EOS": 1024,
                "random_bert": 0,
            },
            "inference": {"top_k": 5},
            "output_dir": str(log_dir),
            # v59.5.11: _unify_preprocessing_filenames()에서 접미사 제거됨
            "train_semantic_path": str(log_dir / "6-name2semantic.tsv"),
            "train_phoneme_path": str(log_dir / "2-name2text.txt"),
        }

        config_path = Path(self.config.output_folder) / "s1_config.yaml"
        import yaml
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        return config_path

    def _run_gpt_training(self):
        """GPT 모델 학습 (s1_train.py)"""
        self._update_progress(TrainingStage.GPT_TRAIN, 0, "GPT 모델 학습 중...")

        # Config 생성
        try:
            config_path = self._create_s1_config()
        except ImportError:
            # yaml 모듈 없으면 기본 config 사용
            config_path = self.gs_root / "GPT_SoVITS" / "configs" / "s1longer.yaml"
            logger.warning("[GPT Train] PyYAML 없음, 기본 config 사용")

        exp_name = self._get_exp_name()

        cmd = [
            self.python_exec,
            str(self.gs_root / "GPT_SoVITS" / "s1_train.py"),
            "-c", str(config_path),
        ]

        env = self._build_subprocess_env()
        env["_CUDA_VISIBLE_DEVICES"] = self.config.gpu_id
        env["exp_name"] = exp_name

        total_epochs = self.config.gpt_epochs

        def parse_gpt_progress(line: str) -> Optional[float]:
            # Epoch 10/20 형식
            match = re.search(r'Epoch\s+(\d+)/(\d+)', line, re.IGNORECASE)
            if match:
                current = int(match.group(1))
                total = int(match.group(2))
                self.progress.current_epoch = current
                self.progress.total_epochs = total
                return (current / total) * 100

            # epoch=10 형식
            match2 = re.search(r'epoch[=:\s]+(\d+)', line, re.IGNORECASE)
            if match2:
                current = int(match2.group(1))
                self.progress.current_epoch = current
                self.progress.total_epochs = total_epochs
                return min(100, (current / total_epochs) * 100)

            return None

        success = self._run_subprocess(cmd, TrainingStage.GPT_TRAIN, parse_gpt_progress, env=env)  # v59.5.10: env 전달
        if success:
            self._update_progress(TrainingStage.GPT_TRAIN, 100, "GPT 학습 완료")
        else:
            raise Exception("GPT 학습 실패")

    def _create_s2_config(self) -> Path:
        """
        v59.5.11: SoVITS 학습용 s2.json config 생성

        s2_train.py는 get_hparams(stage=2)로 -c 인자를 읽어 config를 로드.
        원본 s2.json을 베이스로 하되, 학습 파라미터를 오버라이드.
        """
        exp_name = self._get_exp_name()
        log_dir = self.gs_root / "logs" / exp_name

        # 원본 s2.json 읽기
        base_config_path = self.gs_root / "GPT_SoVITS" / "configs" / "s2.json"
        with open(base_config_path, 'r', encoding='utf-8') as f:
            s2_config = json.load(f)

        # 학습 파라미터 오버라이드
        s2_config["s2_ckpt_dir"] = str(log_dir)
        s2_config["s1_ckpt_dir"] = str(log_dir)

        if "data" not in s2_config:
            s2_config["data"] = {}
        s2_config["data"]["exp_dir"] = str(log_dir)

        if "train" not in s2_config:
            s2_config["train"] = {}
        s2_config["train"]["epochs"] = self.config.sovits_epochs
        s2_config["train"]["batch_size"] = self.config.batch_size
        s2_config["train"]["save_every_epoch"] = self.config.save_every_n_epoch
        s2_config["train"]["gpu_numbers"] = self.config.gpu_id
        # v59.5.11: v2 final pretrained 사용 (기존 모든 모델이 이걸로 학습됨)
        # s2G488k/s2D488k = 초기 중국어 전용 (text_embedding=322)
        # s2G2333k/s2D2333k = v2 final 다국어 (text_embedding=732) ← 정답
        s2_config["train"]["pretrained_s2G"] = str(self.gs_root / "GPT_SoVITS" / "pretrained_models" / "gsv-v2final-pretrained" / "s2G2333k.pth")
        s2_config["train"]["pretrained_s2D"] = str(self.gs_root / "GPT_SoVITS" / "pretrained_models" / "gsv-v2final-pretrained" / "s2D2333k.pth")
        s2_config["train"]["if_save_latest"] = True
        s2_config["train"]["if_save_every_weights"] = True
        s2_config["train"]["text_low_lr_rate"] = 0.4
        s2_config["train"]["half_weights_save_dir"] = str(self.gs_root / "SoVITS_weights_v2")

        # v59.5.11: model.version 필수! s2_train이 checkpoint 경로에 사용
        if "model" not in s2_config:
            s2_config["model"] = {}
        s2_config["model"]["version"] = "v2"  # 기존 모든 모델이 v2로 학습됨

        # v59.5.11: top-level 필수 필드 (s2_train.py가 hps.name, hps.version 등으로 접근)
        exp_name = self._get_exp_name()
        s2_config["name"] = exp_name
        s2_config["version"] = "v2"
        s2_config["save_weight_dir"] = str(self.gs_root / "SoVITS_weights_v2")

        # v59.5.11: logs_s2_v2 디렉토리 미리 생성 (s2_train이 여기에 ckpt 저장)
        s2_log_subdir = log_dir / "logs_s2_v2"
        s2_log_subdir.mkdir(parents=True, exist_ok=True)

        # config 저장
        config_path = Path(self.config.output_folder) / "s2_config.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(s2_config, f, ensure_ascii=False, indent=2)

        return config_path

    def _run_sovits_training(self):
        """SoVITS 모델 학습 (s2_train.py)"""
        self._update_progress(TrainingStage.SOVITS_TRAIN, 0, "SoVITS 모델 학습 중...")

        exp_name = self._get_exp_name()

        # v59.5.11: s2.json config 생성 후 -c 인자로 전달
        s2_config_path = self._create_s2_config()

        cmd = [
            self.python_exec,
            str(self.gs_root / "GPT_SoVITS" / "s2_train.py"),
            "-c", str(s2_config_path),  # v59.5.11: config 경로 전달 (get_hparams가 읽음)
        ]

        env = self._build_subprocess_env()
        env["_CUDA_VISIBLE_DEVICES"] = self.config.gpu_id

        total_epochs = self.config.sovits_epochs

        def parse_sovits_progress(line: str) -> Optional[float]:
            # Epoch: 10/20 형식
            match = re.search(r'Epoch[:\s]+(\d+)/(\d+)', line, re.IGNORECASE)
            if match:
                current = int(match.group(1))
                total = int(match.group(2))
                self.progress.current_epoch = current
                self.progress.total_epochs = total
                return (current / total) * 100 if total > 0 else 0  # v60.1.0: div-by-zero 방어

            # global_step 기반 진행률 (대략적)
            match2 = re.search(r'global_step[=:\s]+(\d+)', line, re.IGNORECASE)
            if match2:
                step = int(match2.group(1))
                # 대략 1epoch = 100steps 가정
                estimated_epoch = step // 100
                self.progress.current_epoch = min(estimated_epoch, total_epochs)
                self.progress.total_epochs = total_epochs
                return min(100, (estimated_epoch / total_epochs) * 100)

            return None

        success = self._run_subprocess(cmd, TrainingStage.SOVITS_TRAIN, parse_sovits_progress, env=env)
        if success:
            self._update_progress(TrainingStage.SOVITS_TRAIN, 100, "SoVITS 학습 완료")
        else:
            raise Exception("SoVITS 학습 실패")

    def _run_extraction(self):
        """모델 추출 및 저장 → assets/models/custom/{model_name}/"""
        self._update_progress(TrainingStage.EXTRACTING, 0, "모델 파일 추출 중...")

        exp_name = self._get_exp_name()

        # 소스 경로 (GPT-SoVITS 학습 결과)
        gpt_weights_dir = self.gs_root / "GPT_weights_v2"
        sovits_weights_dir = self.gs_root / "SoVITS_weights_v2"

        # 대상 경로 (Reverie custom models)
        try:
            from config.settings import config as app_config
            custom_dir = Path(app_config.ASSETS_DIR) / "models" / "custom" / self.config.model_name
        except Exception:
            custom_dir = Path(self.config.output_folder) / "model_output"

        custom_dir.mkdir(parents=True, exist_ok=True)

        self._update_progress(TrainingStage.EXTRACTING, 20, "GPT 가중치 찾는 중...")

        # GPT 가중치 찾기 (가장 최신 또는 마지막 epoch)
        gpt_files = list(gpt_weights_dir.glob(f"{exp_name}*.ckpt"))
        if not gpt_files:
            # 일반적인 패턴으로 재시도
            gpt_files = list(gpt_weights_dir.glob("*.ckpt"))
            gpt_files = [f for f in gpt_files if exp_name.lower() in f.name.lower()]

        gpt_ckpt = None
        if gpt_files:
            # 가장 최신 파일 선택
            gpt_ckpt = max(gpt_files, key=lambda f: f.stat().st_mtime)
            shutil.copy(gpt_ckpt, custom_dir / "gpt_weights.ckpt")
            logger.info(f"[Extraction] GPT 가중치 복사: {gpt_ckpt.name}")
        else:
            logger.warning("[Extraction] GPT 가중치를 찾을 수 없습니다.")

        self._update_progress(TrainingStage.EXTRACTING, 50, "SoVITS 가중치 찾는 중...")

        # SoVITS 가중치 찾기
        sovits_files = list(sovits_weights_dir.glob(f"{exp_name}*.pth"))
        if not sovits_files:
            sovits_files = list(sovits_weights_dir.glob("*.pth"))
            sovits_files = [f for f in sovits_files if exp_name.lower() in f.name.lower()]

        sovits_pth = None
        if sovits_files:
            sovits_pth = max(sovits_files, key=lambda f: f.stat().st_mtime)
            shutil.copy(sovits_pth, custom_dir / "sovits_weights.pth")
            logger.info(f"[Extraction] SoVITS 가중치 복사: {sovits_pth.name}")
        else:
            logger.warning("[Extraction] SoVITS 가중치를 찾을 수 없습니다.")

        self._update_progress(TrainingStage.EXTRACTING, 70, "model_info.json 생성 중...")

        # model_info.json 생성
        model_info = {
            "model_id": self.config.model_name,
            "display_name": self.config.model_name,
            "description": self.config.model_description or f"Reverie에서 학습된 모델",
            "gpt_weights": "gpt_weights.ckpt",
            "sovits_weights": "sovits_weights.pth",
            "default_emotion": "calm",
            "emotions": {
                "calm": {
                    "reference_audio": "",
                    "reference_text": "안녕하세요.",
                    "description": "차분한 감정"
                }
            },
            "training_config": {
                "gpt_epochs": self.config.gpt_epochs,
                "sovits_epochs": self.config.sovits_epochs,
                "batch_size": self.config.batch_size,
                "learning_rate": self.config.learning_rate,
                "quality_preset": self.config.quality_preset,
            },
            "created_at": datetime.now().isoformat(),
        }

        with open(custom_dir / "model_info.json", 'w', encoding='utf-8') as f:
            json.dump(model_info, f, ensure_ascii=False, indent=2)

        self._update_progress(TrainingStage.EXTRACTING, 90, "참조 음성 폴더 생성 중...")

        # 기본 감정 폴더 생성
        (custom_dir / "calm").mkdir(exist_ok=True)

        # 슬라이스된 음성 중 하나를 참조 음성으로 복사
        slice_output = Path(self.config.output_folder) / "sliced_audio"
        if slice_output.exists():
            wav_files = list(slice_output.glob("*.wav"))
            if wav_files:
                # 적당한 크기의 파일 선택 (너무 짧지 않은)
                for wav in sorted(wav_files, key=lambda f: f.stat().st_size, reverse=True):
                    if wav.stat().st_size > 50000:  # 50KB 이상
                        shutil.copy(wav, custom_dir / "calm" / "ref.wav")
                        logger.info(f"[Extraction] 참조 음성 복사: {wav.name}")
                        break

        self._update_progress(TrainingStage.EXTRACTING, 100, "모델 추출 완료!")

        # 결과 요약 로깅
        logger.info(f"[Extraction] 모델 저장 완료: {custom_dir}")
        logger.info(f"[Extraction] - GPT: {'O' if gpt_ckpt else 'X'}")
        logger.info(f"[Extraction] - SoVITS: {'O' if sovits_pth else 'X'}")

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def current_stage(self) -> TrainingStage:
        return self.progress.stage


# 전역 인스턴스 (싱글톤)
_trainer_instance: Optional[SoVITSTrainer] = None

def get_trainer() -> SoVITSTrainer:
    """SoVITSTrainer 싱글톤 인스턴스 반환"""
    global _trainer_instance
    if _trainer_instance is None:
        _trainer_instance = SoVITSTrainer()
    return _trainer_instance


# 테스트
if __name__ == "__main__":
    def on_progress(p: TrainingProgress):
        print(f"[{p.stage.name}] {p.stage_progress:.1f}% | 전체: {p.overall_progress:.1f}% | {p.message}")

    def on_log(msg: str):
        print(f"  LOG: {msg}")

    trainer = SoVITSTrainer(r"C:\GPT-SoVITS\GPT-SoVITS-v3lora-20250228")
    trainer.set_progress_callback(on_progress)
    trainer.set_log_callback(on_log)

    # 테스트 설정
    cfg = TrainingConfig(
        model_name="test_model",
        audio_folder=r"C:\test_audio",
        gpt_epochs=3,
        sovits_epochs=2
    )

    print("학습 시작...")
    trainer.start_training(cfg)

    # 완료 대기
    while trainer.is_running:
        time.sleep(1)

    print("완료!")
