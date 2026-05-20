# src/config/settings_v2.py
# ============================================================
# v56.1: Pydantic BaseSettings 기반 설정 관리
# 기존 Config 클래스와 100% 호환 유지
# ============================================================
import os
import sys
from typing import Dict, List, Optional, Tuple
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from config.path_utils import normalize_runtime_base_dir, project_path


def _get_source_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_base_dir() -> str:
    """실행 환경에 따른 루트 경로 자동 감지
    v62.37: REVERIE_BASE_DIR 환경변수 최우선 지원 (배포 경로 강제 지정용)
    """
    # v62.37: 환경변수 최우선 — 배포 시 assets/ 위치 강제 지정 가능
    env_base = os.environ.get("REVERIE_BASE_DIR", "").strip()
    source_root = _get_source_root()
    if env_base and os.path.isdir(env_base):
        return normalize_runtime_base_dir(env_base, source_root=source_root, is_binary_runtime=False)

    is_exe = sys.executable.lower().endswith('.exe') and not sys.executable.lower().endswith('python.exe')
    is_frozen = getattr(sys, 'frozen', False)

    if is_exe or is_frozen:
        return normalize_runtime_base_dir(
            os.path.dirname(sys.executable),
            source_root=source_root,
            is_binary_runtime=True,
        )

    return normalize_runtime_base_dir(source_root, source_root=source_root, is_binary_runtime=False)


class AnimateDiffConfig(BaseSettings):
    """AnimateDiff 설정"""
    checkpoint: str = "dreamshaper_8.safetensors"
    motion_model: str = "animatediff_lightning_8step_diffusers.safetensors"
    width: int = 512
    height: int = 512
    frames: int = 16
    fps: int = 8
    steps: int = 6
    cfg: float = 1.5


class ReverieSettings(BaseSettings):
    """
    Reverie Studio 통합 설정 (Pydantic v2)

    v56.1: BaseSettings 기반으로 재구현
    - 타입 검증 자동화
    - .env 자동 로드
    - 기존 Config 클래스와 호환
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 알 수 없는 환경변수 무시
        case_sensitive=False,
    )

    # ============================================================
    # 기본 경로 (환경변수가 아닌 계산값)
    # ============================================================
    BASE_DIR: str = Field(default_factory=_get_base_dir)
    PROJECT_ROOT: str = ""

    # ============================================================
    # API 설정 (환경변수에서 로드)
    # ============================================================
    GEMINI_API_KEY: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    STORY_LLM_PROVIDER: str = Field(default="claude_cli", alias="STORY_LLM_PROVIDER")
    STORY_LLM_MODEL: str = Field(default="", alias="STORY_LLM_MODEL")
    STORY_LLM_TIMEOUT_SEC: int = Field(default=600, alias="STORY_LLM_TIMEOUT_SEC")
    CLAUDE_CLI_PATH: str = Field(default="claude", alias="CLAUDE_CLI_PATH")
    CLAUDE_CLI_MODEL: str = Field(default="sonnet", alias="CLAUDE_CLI_MODEL")
    CLAUDE_CLI_EXTRA_ARGS: str = Field(default="", alias="CLAUDE_CLI_EXTRA_ARGS")
    CLAUDE_CLI_SETTING_SOURCES: str = Field(default="project,local", alias="CLAUDE_CLI_SETTING_SOURCES")
    CLAUDE_CLI_NO_SESSION_PERSISTENCE: bool = Field(default=True, alias="CLAUDE_CLI_NO_SESSION_PERSISTENCE")
    SD_URL: str = Field(default="http://127.0.0.1:7860", alias="SD_URL")
    SOVITS_URL: str = Field(default="http://127.0.0.1:9880", alias="SOVITS_URL")
    GS_ROOT: str = Field(default="", alias="GS_ROOT")  # v60.1.0: .env에서 설정 필수

    # AI 서버 경로
    # v57.0.2: 실제 설치 경로로 수정 (C:\AI\stable-diffusion-webui → C:\AI\webui)
    SD_WEBUI_ROOT: str = Field(default="", alias="SD_WEBUI_ROOT")  # v60.1.0: .env에서 설정 필수
    SD_WEBUI_SCRIPT: str = Field(default="webui-user.bat", alias="SD_WEBUI_SCRIPT")
    SOVITS_ROOT: str = Field(default="", alias="SOVITS_ROOT")  # v60.1.0: .env에서 설정 필수
    SOVITS_SCRIPT: str = Field(default="start_api_with_ffmpeg.bat", alias="SOVITS_SCRIPT")
    COMFYUI_SCRIPT: str = Field(default="run_nvidia_gpu.bat", alias="COMFYUI_SCRIPT")

    # 서버 자동 시작
    AUTO_START_SERVERS: bool = Field(default=False, alias="AUTO_START_SERVERS")
    AUTO_START_LIST: str = Field(default="SD WebUI,GPT-SoVITS", alias="AUTO_START_LIST")

    # ============================================================
    # 테스트/개발 모드
    # ============================================================
    TEST_MODE: bool = Field(default=False, alias="TEST_MODE")
    REVERIE_DEV_MODE: bool = Field(default=False, alias="REVERIE_DEV_MODE")

    # 테스트 모드 설정값
    TEST_TURNS_PER_PART: int = 5
    TEST_IMAGE_COUNT: int = 5
    TEST_DURATION: int = 60
    VISUAL_STORYTELLING_OVERRIDE: Optional[bool] = Field(default=None, alias="VISUAL_STORYTELLING_OVERRIDE")
    MOTIONTOON_RENDER_MODE_OVERRIDE: Optional[str] = Field(default=None, alias="MOTIONTOON_RENDER_MODE_OVERRIDE")

    # ============================================================
    # SD 모델 설정
    # ============================================================
    SD_MODEL_HORROR: str = "meinamix_v12Final.safetensors"  # v61: MeinaMix V12 통일
    SD_MODEL_SENIOR: str = "meinamix_v12Final.safetensors"  # v61: MeinaMix V12 통일
    SD_WEBUI_MODELS: str = Field(default="", alias="SD_WEBUI_MODELS")

    # ============================================================
    # ComfyUI / v50 설정
    # ============================================================
    COMFYUI_URL: str = Field(default="http://127.0.0.1:8188", alias="COMFYUI_URL")
    COMFYUI_ROOT: str = Field(default="", alias="COMFYUI_ROOT")  # v60.1.0: .env에서 설정 (선택)
    V50_MODE: str = Field(default="speed", alias="V50_MODE")
    V50_ENABLED: bool = Field(default=False, alias="V50_ENABLED")

    # VideoToon local stack settings. These are intentionally separate from
    # the existing v50 AnimateDiff flags so the completed pipeline can stay
    # stable while the new layered video-toon direction is integrated.
    VIDEOTOON_LOCAL_MODE_OVERRIDE: bool = Field(default=True, alias="VIDEOTOON_LOCAL_MODE_OVERRIDE")
    VIDEOTOON_WORKSPACE_ROOT: str = Field(default="", alias="VIDEOTOON_WORKSPACE_ROOT")
    VIDEOTOON_IMAGE_BACKEND: str = Field(default="comfyui", alias="VIDEOTOON_IMAGE_BACKEND")
    VIDEOTOON_GENERATION_WIDTH: int = Field(default=1024, alias="VIDEOTOON_GENERATION_WIDTH")
    VIDEOTOON_GENERATION_HEIGHT: int = Field(default=576, alias="VIDEOTOON_GENERATION_HEIGHT")
    VIDEOTOON_MAX_PARALLEL_IMAGE_JOBS: int = Field(default=1, alias="VIDEOTOON_MAX_PARALLEL_IMAGE_JOBS")
    VIDEOTOON_LAYER_TOOL_PYTHON: str = Field(
        default="",
        alias="VIDEOTOON_LAYER_TOOL_PYTHON",
    )

    # ============================================================
    # TTS 엔진 설정
    # ============================================================
    # v57.3.0: Qwen3 비활성화 - 8GB VRAM에서 실용성 부족
    # SoVITS 전용 모드로 롤백
    TTS_ENGINE: str = Field(default="sovits", alias="TTS_ENGINE")  # "sovits" 또는 "supertonic"
    TTS_FALLBACK_ENABLED: bool = Field(default=True, alias="TTS_FALLBACK_ENABLED")

    # Supertonic 3 local TTS settings.
    # Use TTS_ENGINE=supertonic to enable this reference-free local voice pool.
    SUPERTONIC_AUTO_DOWNLOAD: bool = Field(default=True, alias="SUPERTONIC_AUTO_DOWNLOAD")
    SUPERTONIC_DEFAULT_VOICE: str = Field(default="M1", alias="SUPERTONIC_DEFAULT_VOICE")
    SUPERTONIC_VOICE_MAP: str = Field(default="", alias="SUPERTONIC_VOICE_MAP")
    SUPERTONIC_TOTAL_STEPS: int = Field(default=5, alias="SUPERTONIC_TOTAL_STEPS")
    SUPERTONIC_SPEED: float = Field(default=1.05, alias="SUPERTONIC_SPEED")
    SUPERTONIC_MAX_CHUNK_LENGTH: int = Field(default=120, alias="SUPERTONIC_MAX_CHUNK_LENGTH")
    SUPERTONIC_SILENCE_DURATION: float = Field(default=0.25, alias="SUPERTONIC_SILENCE_DURATION")
    SUPERTONIC_INTRA_OP_THREADS: int = Field(default=0, alias="SUPERTONIC_INTRA_OP_THREADS")
    SUPERTONIC_INTER_OP_THREADS: int = Field(default=0, alias="SUPERTONIC_INTER_OP_THREADS")

    # Qwen3-TTS 설정 (v57.3.0: 비활성화, 미래 GPU 업그레이드 대비 보존)
    # 모델 옵션:
    # - Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign: 감정 표현 지원 (무거움)
    # - Qwen/Qwen3-TTS-12Hz-1.7B-Base: 보이스 클로닝 지원
    # - Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice: instruct 지원 + 경량
    # - Qwen/Qwen3-TTS-12Hz-0.6B-Base: 경량 모델 (ref_audio 필수)
    QWEN3_MODEL: str = Field(default="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice", alias="QWEN3_MODEL")
    QWEN3_DEVICE: str = Field(default="cuda", alias="QWEN3_DEVICE")

    # ============================================================
    # 하이브리드 TTS 설정 (v57.2 → v57.3.0 비활성화)
    # ============================================================
    # v57.3.0: 하이브리드 TTS 비활성화 - SoVITS 전용 모드
    # 미래 GPU 업그레이드 시 다시 활성화 가능
    TTS_HYBRID_ENABLED: bool = Field(default=False, alias="TTS_HYBRID_ENABLED")  # v57.3.0: 비활성화
    # SoVITS로 처리할 역할 목록 (하이브리드 모드에서만 사용)
    TTS_SOVITS_ROLES: str = Field(default="narrator,grandpa", alias="TTS_SOVITS_ROLES")

    # ============================================================
    # 이미지 생성 설정 (v57.0.2)
    # ============================================================
    GPU_VRAM_GB: int = Field(default=8, alias="GPU_VRAM_GB")
    LOW_VRAM_MODE: bool = Field(default=False, alias="LOW_VRAM_MODE")
    LOW_VRAM_IMAGE_MAX_WIDTH: int = Field(default=768, alias="LOW_VRAM_IMAGE_MAX_WIDTH")
    LOW_VRAM_IMAGE_MAX_HEIGHT: int = Field(default=432, alias="LOW_VRAM_IMAGE_MAX_HEIGHT")
    LOW_VRAM_THUMB_MAX_WIDTH: int = Field(default=1280, alias="LOW_VRAM_THUMB_MAX_WIDTH")
    LOW_VRAM_THUMB_MAX_HEIGHT: int = Field(default=720, alias="LOW_VRAM_THUMB_MAX_HEIGHT")
    LOW_VRAM_SD_STEPS_CAP: int = Field(default=18, alias="LOW_VRAM_SD_STEPS_CAP")
    LOW_VRAM_THUMB_STEPS_CAP: int = Field(default=20, alias="LOW_VRAM_THUMB_STEPS_CAP")
    LOW_VRAM_REMOTION_CONCURRENCY: int = Field(default=2, alias="LOW_VRAM_REMOTION_CONCURRENCY")

    # 병렬 처리 워커 수 (8GB VRAM: 1 권장, 24GB VRAM: 3~4 가능)
    IMAGE_MAX_WORKERS: int = Field(default=1, alias="IMAGE_MAX_WORKERS")

    # ============================================================
    # 렌더링 엔진 설정 (v57.1 → v57.4 Remotion 추가)
    # ============================================================
    # 렌더링 엔진: auto(권장), gpu(NVENC), cpu(libx264), remotion(React)
    # - auto: GPU 가용성 자동 체크, RTX 시리즈면 NVENC 사용
    # - gpu: NVENC 강제 (RTX 20/30/40 시리즈 필요)
    # - cpu: libx264 사용 (호환성 최고, 느림)
    # - remotion: React 기반 렌더링 (Ken Burns 효과, 빠른 렌더링)
    RENDER_ENGINE: str = Field(default="auto", alias="RENDER_ENGINE")

    # Remotion 설정 (v57.4)
    REMOTION_CONCURRENCY: int = Field(default=6, alias="REMOTION_CONCURRENCY")  # 병렬 렌더링 스레드

    # 외부 FFmpeg 경로 (GPT-SoVITS 포함 버전이 구버전인 경우)
    # RTX 40 시리즈는 FFmpeg 6.0+ 필요
    # 예: C:\ffmpeg\bin\ffmpeg.exe
    FFMPEG_PATH: str = Field(default="", alias="FFMPEG_PATH")

    # ============================================================
    # 영상 기본 설정
    # ============================================================
    VIDEO_WIDTH: int = 1280
    VIDEO_HEIGHT: int = 720
    FPS: int = 24

    # ============================================================
    # 자막 색상
    # ============================================================
    SENIOR_COLORS: Dict[str, str] = Field(default_factory=lambda: {
        "grandma": "#FFD700",
        "grandpa": "#00BFFF",
        "man": "#90EE90",
        "woman": "#FFB6C1",
        "narrator": "#FFFFFF",
        "ghost": "#FF0000",
        "male_actor": "#ADFF2F",
        "female_actor": "#FF69B4",
        "default": "#FFFFFF",
    })

    # ============================================================
    # 파생 경로 (model_validator에서 계산)
    # ============================================================
    DATA_DIR: str = ""
    ASSETS_DIR: str = ""
    OUTPUT_DIR: str = ""
    EXPORTS_DIR: str = ""
    LOGS_DIR: str = ""
    SCRIPTS_DIR: str = ""
    THUMBNAILS_DIR: str = ""
    TEMP_AUDIO_DIR: str = ""
    TEMP_IMAGES_DIR: str = ""
    FONT_PATH: str = ""
    HORROR_NARRATOR_DIR: str = ""
    SENIOR_MODEL_ROOT: str = ""
    V50_CLIPS_DIR: str = ""
    V50_TEMP_DIR: str = ""
    SD_MODEL_CHECKPOINT: str = ""
    SD_MODEL_FULL_PATH: str = ""
    DEV_MODE: bool = False

    # PROFILES는 별도 메서드에서 생성
    PROFILES: Dict = Field(default_factory=dict)
    ANIMATEDIFF_CONFIG: Dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def compute_derived_paths(self) -> 'ReverieSettings':
        """파생 경로 및 설정 계산"""
        base = normalize_runtime_base_dir(
            self.BASE_DIR,
            source_root=_get_source_root(),
            is_binary_runtime=getattr(sys, 'frozen', False),
        )
        self.BASE_DIR = base
        self.PROJECT_ROOT = base

        # 기본 경로
        self.DATA_DIR = project_path(base, "data")
        self.ASSETS_DIR = project_path(base, "assets")
        self.OUTPUT_DIR = project_path(base, "output")
        self.EXPORTS_DIR = project_path(self.DATA_DIR, "exports")
        self.LOGS_DIR = project_path(self.DATA_DIR, "logs")
        self.SCRIPTS_DIR = project_path(self.DATA_DIR, "scripts")
        self.THUMBNAILS_DIR = project_path(self.DATA_DIR, "thumbnails")
        self.TEMP_AUDIO_DIR = project_path(self.DATA_DIR, "temp_audio")
        self.TEMP_IMAGES_DIR = project_path(self.DATA_DIR, "temp_images")
        self.FONT_PATH = project_path(self.ASSETS_DIR, "fonts", "font.ttf")

        # 모델 경로
        self.HORROR_NARRATOR_DIR = project_path(self.ASSETS_DIR, "models", "horror", "narrator")
        self.SENIOR_MODEL_ROOT = project_path(self.ASSETS_DIR, "models", "senior")

        # v50 경로
        self.V50_CLIPS_DIR = project_path(self.OUTPUT_DIR, "clips")
        self.V50_TEMP_DIR = project_path(self.OUTPUT_DIR, "temp")

        # SD 모델
        self.SD_MODEL_CHECKPOINT = self.SD_MODEL_HORROR
        if self.SD_WEBUI_MODELS:
            self.SD_MODEL_FULL_PATH = os.path.join(self.SD_WEBUI_MODELS, self.SD_MODEL_HORROR)
        else:
            self.SD_MODEL_FULL_PATH = self.SD_MODEL_HORROR

        # DEV_MODE (환경변수 또는 dev_mode.txt)
        self.DEV_MODE = self.REVERIE_DEV_MODE
        if not self.DEV_MODE:
            dev_mode_file = project_path(base, "dev_mode.txt")
            self.DEV_MODE = os.path.exists(dev_mode_file)

        # AnimateDiff 설정
        self.ANIMATEDIFF_CONFIG = {
            "quality": {
                "checkpoint": "revAnimated_v2Rebirth.safetensors",
                "motion_model": "animatediff_lightning_8step_diffusers.safetensors",
                "width": 512,
                "height": 512,
                "frames": 24,
                "fps": 8,
                "steps": 8,
                "cfg": 1.5,
            },
            "speed": {
                "checkpoint": "dreamshaper_8.safetensors",
                "motion_model": "animatediff_lightning_8step_diffusers.safetensors",
                "width": 512,
                "height": 512,
                "frames": 16,
                "fps": 8,
                "steps": 6,
                "cfg": 1.5,
            }
        }

        # PROFILES 생성
        self.PROFILES = {
            "daily_life_toon": {
                "channel_name": "",
                "model_root": self.SENIOR_MODEL_ROOT,
                "sd_positive": "premium Korean webtoon video-toon, layered background, character foreground, clean line art, expressive face, daily-life lighting",
                "sd_negative": "photorealistic, 3d render, chibi, cropped head, cut off hair, deformed face, text, watermark, UI overlay, nsfw",
                "bgm_folder": os.path.join(self.ASSETS_DIR, "bgm", "daily"),
                "intro_file": "",
                "outro_file": "",
            },
            "mystery_toon": {
                "channel_name": "",
                "model_root": self.SENIOR_MODEL_ROOT,
                "sd_positive": "premium Korean mystery webtoon video-toon, layered background, character foreground, restrained shadows, clean line art, expressive eyes",
                "sd_negative": "photorealistic, 3d render, gore, monster, chibi, cropped head, cut off hair, deformed face, text, watermark, UI overlay, nsfw",
                "bgm_folder": os.path.join(self.ASSETS_DIR, "bgm", "mystery"),
                "intro_file": "",
                "outro_file": "",
            },
            "horror": {
                "channel_name": "",
                "voice_model_gpt": os.path.join(self.HORROR_NARRATOR_DIR, "gpt_weights.ckpt"),
                "voice_model_sovits": os.path.join(self.HORROR_NARRATOR_DIR, "sovits_weights.pth"),
                "ref_audio": os.path.join(self.HORROR_NARRATOR_DIR, "calm.mp3"),
                "ref_text": "가장큰 위험은, 아무 위험도 감지하지 않는것이다.",
                "sd_positive": "eerie high-contrast horror comic style, dark atmosphere, cinematic shadows, detailed linework, 8k",
                "sd_negative": "bright, sunny, cute, colorful, photo",
                "bgm_folder": os.path.join(self.ASSETS_DIR, "bgm", "horror", "BGM_Horror"),
                "intro_file": os.path.join(self.ASSETS_DIR, "intro", "intro_horror.mp4"),
                "outro_file": os.path.join(self.ASSETS_DIR, "outro", "outro_horror.mp4"),
            },
            "senior_touching": {
                "channel_name": "",
                "model_root": self.SENIOR_MODEL_ROOT,
                "sd_positive": "warm watercolor painting, soft sunlight, nostalgic, bright and peaceful colors, 2d, masterpiece",
                "sd_negative": "dark, scary, horror, intense, messy, photo, realistic",
                "bgm_folder": os.path.join(self.ASSETS_DIR, "bgm", "senior", "touching"),
                "intro_file": os.path.join(self.ASSETS_DIR, "intro", "intro_senior_touching.mp4"),
                "outro_file": os.path.join(self.ASSETS_DIR, "outro", "outro_senior.mp4"),
            },
            "senior_makjang": {
                "channel_name": "",
                "model_root": self.SENIOR_MODEL_ROOT,
                "sd_positive": "dramatic webtoon style, intense cinematic lighting, sharp shadows, tense atmosphere",
                "sd_negative": "peaceful, calm, monochrome, cute",
                "bgm_folder": os.path.join(self.ASSETS_DIR, "bgm", "senior", "makjang"),
                "intro_file": os.path.join(self.ASSETS_DIR, "intro", "intro_senior_makjang.mp4"),
                "outro_file": os.path.join(self.ASSETS_DIR, "outro", "outro_senior.mp4"),
            },
            "senior": {
                "channel_name": "",
                "model_root": self.SENIOR_MODEL_ROOT,
                "sd_style_touching": {
                    "positive": "warm watercolor painting, soft sunlight, nostalgic, bright and peaceful colors, 2d, masterpiece",
                    "negative": "dark, scary, horror, intense, messy, photo, realistic",
                },
                "sd_style_makjang": {
                    "positive": "dramatic webtoon style, intense cinematic lighting, sharp shadows, tense atmosphere",
                    "negative": "peaceful, calm, monochrome, cute",
                },
                "bgm_touching": os.path.join(self.ASSETS_DIR, "bgm", "senior", "touching"),
                "bgm_makjang": os.path.join(self.ASSETS_DIR, "bgm", "senior", "makjang"),
                "intro_file": os.path.join(self.ASSETS_DIR, "intro", "intro_senior.mp4"),
                "outro_file": os.path.join(self.ASSETS_DIR, "outro", "outro_senior.mp4"),
            },
        }

        if self.is_low_vram():
            self.IMAGE_MAX_WORKERS = min(self.IMAGE_MAX_WORKERS, 1)
            self.REMOTION_CONCURRENCY = min(
                self.REMOTION_CONCURRENCY,
                self.LOW_VRAM_REMOTION_CONCURRENCY,
            )

        return self

    # ============================================================
    # 기존 Config 클래스와 호환되는 메서드
    # ============================================================
    def get_profile(self, channel_name: str) -> dict:
        """채널별 프로필 반환"""
        return self.PROFILES.get(channel_name, self.PROFILES["daily_life_toon"])

    def get_v50_config(self, mode: str = None) -> dict:
        """v50 AnimateDiff 설정 반환"""
        if mode is None:
            mode = self.V50_MODE
        return self.ANIMATEDIFF_CONFIG.get(mode, self.ANIMATEDIFF_CONFIG["speed"])

    def get_comfyui_host_port(self) -> Tuple[str, int]:
        """ComfyUI 호스트/포트 반환"""
        url = self.COMFYUI_URL.replace("http://", "").replace("https://", "")
        if ":" in url:
            host, port = url.split(":")
            return host, int(port)
        return url, 8188

    def get_videotoon_config(self) -> dict:
        """Return local layered video-toon stack settings."""
        workspace_root = self.VIDEOTOON_WORKSPACE_ROOT or project_path(self.DATA_DIR, "videotoon_workspace")
        return {
            "local_mode_enabled": bool(self.VIDEOTOON_LOCAL_MODE_OVERRIDE),
            "workspace_root": workspace_root,
            "image_backend": self.VIDEOTOON_IMAGE_BACKEND,
            "generation_width": self.VIDEOTOON_GENERATION_WIDTH,
            "generation_height": self.VIDEOTOON_GENERATION_HEIGHT,
            "max_parallel_image_jobs": max(1, int(self.VIDEOTOON_MAX_PARALLEL_IMAGE_JOBS or 1)),
            "layer_tool_python": self.VIDEOTOON_LAYER_TOOL_PYTHON,
            "comfyui_url": self.COMFYUI_URL,
            "comfyui_root": self.COMFYUI_ROOT,
        }

    def get_auto_start_list(self) -> List[str]:
        """자동 시작 서버 목록"""
        return [s.strip() for s in self.AUTO_START_LIST.split(",")]

    def is_low_vram(self) -> bool:
        """8GB급 GPU 환경 보호용 보수 모드를 판단한다."""
        return bool(self.LOW_VRAM_MODE or self.GPU_VRAM_GB <= 8)

    @staticmethod
    def _round_down_to_multiple(value: int, multiple: int = 8) -> int:
        if value <= multiple:
            return multiple
        return max(multiple, (value // multiple) * multiple)

    def clamp_sd_dimensions(self, width: int, height: int, purpose: str = "image") -> Tuple[int, int]:
        """저VRAM 환경에서 SD 입력 해상도를 안전 범위로 제한한다."""
        if width <= 0 or height <= 0:
            return width, height

        if not self.is_low_vram():
            return width, height

        if purpose == "thumbnail":
            max_width = self.LOW_VRAM_THUMB_MAX_WIDTH
            max_height = self.LOW_VRAM_THUMB_MAX_HEIGHT
        else:
            max_width = self.LOW_VRAM_IMAGE_MAX_WIDTH
            max_height = self.LOW_VRAM_IMAGE_MAX_HEIGHT

        if width <= max_width and height <= max_height:
            return width, height

        scale = min(max_width / width, max_height / height)
        new_width = self._round_down_to_multiple(int(width * scale), 8)
        new_height = self._round_down_to_multiple(int(height * scale), 8)
        return new_width, new_height

    def clamp_sd_steps(self, steps: int, purpose: str = "image") -> int:
        """저VRAM 환경에서 SD step 수를 안전 범위로 제한한다."""
        if steps <= 0:
            return steps

        if not self.is_low_vram():
            return steps

        cap = self.LOW_VRAM_THUMB_STEPS_CAP if purpose == "thumbnail" else self.LOW_VRAM_SD_STEPS_CAP
        return min(steps, cap)

    def get_safe_remotion_concurrency(self, requested: int) -> int:
        """저VRAM 환경에서 Remotion 동시성을 안전값으로 제한한다."""
        if requested <= 0:
            requested = 1

        if not self.is_low_vram():
            return requested

        return max(1, min(requested, self.LOW_VRAM_REMOTION_CONCURRENCY))


# ============================================================
# 싱글톤 인스턴스 (기존 config와 동일한 인터페이스)
# ============================================================
def _create_settings() -> ReverieSettings:
    """설정 인스턴스 생성 (BASE_DIR 기준 .env 로드)"""
    base_dir = _get_base_dir()
    env_file = os.path.join(base_dir, ".env")

    if os.path.exists(env_file):
        return ReverieSettings(_env_file=env_file)
    else:
        return ReverieSettings()


# 전역 설정 인스턴스
settings = _create_settings()


# ============================================================
# 하위 호환성: 기존 'config' 변수명 유지
# from config.settings import config  → 그대로 동작
# ============================================================
config = settings
