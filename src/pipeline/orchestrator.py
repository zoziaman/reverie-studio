# src/pipeline/orchestrator.py
# v60.1.0 Phase 11: media_factory.py에서 이동
# ============================================================
# [제작팀 v33 - Enhanced Media Factory]
# ✅ v32 수정사항:
# - produce_video_with_gui() 신규 추가
# - 썸네일을 맨 앞에서 생성 (1단계)
# - GUI 콜백으로 사용자 확인 대기
# - 확정 후 본편 제작 (2단계)
# ✅ v33 수정사항:
# - 로거 연동 및 에러 추적 개선
# - API 재시도에 지수 백오프 적용 (TTS, SD, 모델 스위칭)
# - 진행률 콜백 세분화
# - 메모리 최적화 (gc.collect, 클립 해제)
# - 영상 렌더링 옵션 확장 (preset, GPU 인코딩)
# - 취소/일시정지 기능
# - 체크포인트 (작업 중단/재개)
# - 품질 프리셋 (빠른/표준/고품질)
# - 아웃트로 자동 추가
# - 배치 처리 (연속 제작)
# ============================================================
import os
import json
import time
import random
import re
import gc
import logging
from typing import Dict, List, Tuple, Optional, Any, Callable

from PIL import Image

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS


from config.settings import config
from modules_pro.visual_director import visual_director

# v60.1.0 Phase 2: 텍스트 처리 모듈 분리
from pipeline.text_processor import TextProcessor

# v60.1.0 Phase 3: SD WebUI 클라이언트 분리
from pipeline.sd_client import SDClientWrapper, create_sd_client

# v60.1.0 Phase 4: 이미지 일관성 관리 분리
from pipeline.consistency_manager import ConsistencyManager

# v60.1.0 Phase 5: VRAM 관리 분리
from pipeline.vram_manager import VRAMManager

# v60.1.0 Phase 6: SFX 통합 분리
from pipeline.sfx_integrator import SFXIntegrator

# v60.1.0 Phase 7: 썸네일 생성 분리
from pipeline.thumbnail_maker import ThumbnailMaker

# v60.1.0 Phase 8: TTS 관리 분리
from pipeline.tts_manager import TTSManager

# v60.1.0 Phase 9: 이미지 파이프라인 분리
from pipeline.image_pipeline import ImagePipeline

# v60.1.0 Phase 10: 영상 렌더링 분리
from pipeline.video_renderer import VideoRenderer
from pipeline.performance_profiler import ProductionPerformanceProfiler

# v57.7.0: 팩 기반 프롬프트 시스템
# v58: hook_style, sd, video 설정도 팩에서 로드
try:
    from config.pack_config import (
        ACTIVE_PACK, get_prompt,
        get_hook_style, get_sd_settings, get_video_settings  # v58 추가
    )
    PACK_CONFIG_AVAILABLE = True
except ImportError:
    PACK_CONFIG_AVAILABLE = False

# ============================================================
# v33: 로거 설정
# ============================================================
try:
    from utils.logger import get_logger
    logger = get_logger("media_factory")
except ImportError:
    logger = logging.getLogger("media_factory")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)

# v60.1.0: 폰트는 ThumbnailMaker에서 직접 로딩 (orchestrator 미사용)

# v50: NSFW 검수 시스템 (Gemini Vision 기반)
try:
    from utils.nsfw_detector import content_reviewer
    NSFW_DETECTOR_AVAILABLE = True
except ImportError:
    content_reviewer = None
    NSFW_DETECTOR_AVAILABLE = False
    logger.warning("[MediaFactory] NSFW 검수 시스템 로드 실패 - 검수 없이 진행")

# v54.3: 개인화된 프롬프트 최적화 시스템
try:
    from utils.prompt_optimizer import get_prompt_optimizer
    PROMPT_OPTIMIZER_AVAILABLE = True
except ImportError:
    get_prompt_optimizer = None
    PROMPT_OPTIMIZER_AVAILABLE = False
    logger.warning("[MediaFactory] 프롬프트 최적화 시스템 로드 실패 - 기본값 사용")

# v53: 표정 오버레이 완전 비활성화 (v60.1.0: 죽은 코드 제거)

# ============================================================
# v60.1.0: safe_print, set_gui_log_callback, _sanitize_for_path를
# pipeline_utils 정식 버전으로 통합 (중복 제거)
# ============================================================
from pipeline.pipeline_utils import (
    safe_print,
    set_gui_log_callback,
    sanitize_for_path as _sanitize_for_path,
)
# orchestrator 내부에서 _gui_log_callback 직접 참조하는 곳은 없으므로 import 불필요


# ============================================================
# v59.1.7: VSD용 SD WebUI API 클라이언트 래퍼
# VSD의 _call_sd_api()는 sd_client.txt2img(**params) 형태를 기대
# media_factory의 기존 requests.post 패턴과 동일하게 config.SD_URL 사용
# ============================================================

# v60.1.0 Phase 3: SD 클라이언트 → pipeline/sd_client.py로 이동
# 호환성을 위한 별칭 (기존 코드가 _SDClientWrapper 참조하는 곳 대응)


# ============================================================
# v56.1: 영상 모델 클래스 외부 모듈에서 import
# ============================================================
from modules_pro.video_models import (
    QualityPreset,
    RenderSettings,
    RenderEngine,  # v57.1: 렌더링 엔진 enum
    ProductionCheckpoint,
    CancellationToken,
    retry_with_backoff,
)
from core.script_quality_gate import assert_script_quality, ScriptQualityError


# ============================================================
# v56.1: (레거시) 내부 클래스 정의 제거됨
# QualityPreset, RenderSettings, ProductionCheckpoint,
# CancellationToken, retry_with_backoff
# → modules_pro/video_models.py
# ============================================================


# ============================================================
# v56.1: ImageGenerator, AudioSynthesizer 외부 모듈에서 import
# Phase 1 리팩토링 완료 - 별도 파일로 분리됨
# v56.5: TTS 엔진 추상화 레이어 추가
# v57.4: Remotion Assembler 추가
# ============================================================
from modules_pro.image_generator import ImageGenerator


# v56.5: TTS 엔진 추상화 (GPT-SoVITS ↔ Qwen3-TTS 전환 지원)
from modules_pro.tts_engine import (
    TTSEngine,
)


# ============================================================
# v56.1: VideoAssembler 유틸리티 외부 모듈에서 import
# Phase 6 리팩토링 완료 - 별도 파일로 분리됨
# ============================================================


# ============================================================
# v56.1: TTS 서버 관리 유틸리티 외부 모듈에서 import
# Phase 7 리팩토링 완료 - 별도 파일로 분리됨
# ============================================================

# ============================================================
# v57.6.5: Auto-SFX 효과음 자동 삽입
# ============================================================


# ============================================================
# v56.1: (레거시) 내부 클래스 정의 제거됨
# ImageGenerator → modules_pro/image_generator.py
# AudioSynthesizer → modules_pro/audio_synthesizer.py
# video_assembler utilities → v60.1.0: 삭제됨 (estimate_silence_duration만 tts_manager.py로 인라인)
# tts_server_manager → modules_pro/tts_server_manager.py
# ============================================================


class MediaFactory:
    """
    [제작팀 v33 - Enhanced Media Factory]

    주요 기능:
    - 썸네일 선생성 + GUI 연동
    - 지수 백오프 API 재시도
    - 체크포인트 (중단/재개)
    - 품질 프리셋
    - 취소/일시정지
    - 배치 처리
    - v55: 이미지 일관성 (IP-Adapter 연동)
    """

    def __init__(
        self,
        channel: str = "daily_life_toon",
        quality: QualityPreset = QualityPreset.STANDARD,
        target_language: str = "ko",
        style_getter: Callable[[str], dict] = None,  # v57.6.8: 의존성 주입
    ):
        """
        MediaFactory 초기화

        Args:
            channel: 채널 타입 (horror, senior 등)
            quality: 품질 프리셋
            target_language: 타겟 언어 (v57.0.0) - ko, en, ja, zh
            style_getter: GUI에서 주입한 스타일 가져오기 콜백 (v57.6.8)
                         (channel) -> dict {bgm_volume, subtitle_size, speaker_size}
        """
        self.channel = channel
        self._style_getter = style_getter  # v57.6.8: 의존성 주입
        self.cfg = config.get_profile(channel)
        self.quality = quality

        # v57.4: 설정에서 렌더링 엔진 로드
        render_engine = self._get_configured_render_engine()
        if render_engine:
            self.render_settings = RenderSettings.from_engine(render_engine, quality)
        else:
            self.render_settings = RenderSettings.from_quality(quality)

        # v57.0.0: 다국어 설정
        self.target_language = target_language

        # v50: 모드 초기화 (senior 채널의 touching/makjang 구분용)
        self.mode: Optional[str] = None

        # v33: 취소 토큰
        self.cancellation_token: Optional[CancellationToken] = None

        # v33: 현재 체크포인트
        self.checkpoint: Optional[ProductionCheckpoint] = None

        # v55 → v60.1.0 Phase 4: 이미지 일관성 관리 위임
        self._consistency = ConsistencyManager()

        # v60.1.0 Phase 5: VRAM 관리 위임
        self._vram = VRAMManager(config.SD_URL)

        # v60.1.0 Phase 6: SFX 통합 위임
        self._sfx = SFXIntegrator(
            assets_dir=config.ASSETS_DIR,
            gemini_api_key=config.GEMINI_API_KEY
        )

        # v60.1.0 Phase 7: 썸네일 생성 위임
        self._thumb = ThumbnailMaker(
            sd_url=config.SD_URL,
            data_dir=config.DATA_DIR,
            assets_dir=config.ASSETS_DIR,
            font_path=getattr(config, 'FONT_PATH', ''),
            video_width=config.VIDEO_WIDTH,
            video_height=config.VIDEO_HEIGHT
        )

        # v56.1: ImageGenerator 인스턴스 (SD WebUI 담당)
        self._image_generator = ImageGenerator(channel=channel, sd_url=config.SD_URL)

        # v60.1.0 Phase 2: 텍스트 처리 위임
        self._text = TextProcessor()

        # v60.1.0 Phase 8: TTS 관리 위임
        tts_engine_type = getattr(config, 'TTS_ENGINE', 'sovits').lower()
        self._tts = TTSManager(
            channel=channel, target_language=target_language,
            sovits_url=config.SOVITS_URL, sovits_root=config.GS_ROOT,
            assets_dir=config.ASSETS_DIR, data_dir=config.DATA_DIR,
            ffmpeg_path=config.FFMPEG_PATH,
            video_width=config.VIDEO_WIDTH, video_height=config.VIDEO_HEIGHT,
        )
        self._tts.set_callbacks(
            clean_text=self._text.clean_text,
            clean_text_for_tts=self._text.clean_text_for_tts,
            clean_text_for_retry=self._text.clean_text_for_retry,
            role_key_normalize=self._text.role_key_normalize,
            split_into_sentences=self._text.split_into_sentences,
            normalize_path=self._normalize_path,
            release_vram=self._vram.release_tts_vram,
            register_characters=self._register_characters_from_script,
        )
        self._tts.initialize(
            tts_engine_type=tts_engine_type,
            hybrid_enabled=getattr(config, 'TTS_HYBRID_ENABLED', False),
            sovits_roles_str=getattr(config, 'TTS_SOVITS_ROLES', 'narrator,grandpa'),
            test_mode=getattr(config, 'TEST_MODE', False),
            test_duration=getattr(config, 'TEST_DURATION', 0),
        )
        # 하위 호환: 기존 속성 접근자 유지
        self._tts_engine = self._tts.tts_engine
        self._using_sovits = self._tts.using_sovits
        self._hybrid_tts_enabled = self._tts.hybrid_enabled
        self._sovits_roles = self._tts._sovits_roles
        self._sovits_engine = self._tts._sovits_engine
        self._qwen3_engine = self._tts._qwen3_engine
        self._audio_synthesizer = self._tts._audio_synthesizer
        self._tts_server_manager = self._tts._tts_server_manager
        self.current_gpt = self._tts.current_gpt
        self.current_sovits = self._tts.current_sovits
        self.voice_metadata = self._tts.voice_metadata

        logger.info(f"[MediaFactory] 초기화 완료 (채널: {channel}, 품질: {quality.value}, 언어: {target_language})")
        logger.info(f"[MediaFactory] 렌더링 엔진: {self.render_settings.engine.value}")

        # v51: v50_style_guide 기반 고품질 스타일 적용
        self._init_v50_styles()

        # v60.1.0 Phase 9: 이미지 파이프라인 위임
        self._img = ImagePipeline(
            channel=channel,
            mode=self.mode if hasattr(self, 'mode') else "",
            sd_url=config.SD_URL,
            sd_webui_root=config.SD_WEBUI_ROOT,
            data_dir=config.DATA_DIR,
            assets_dir=config.ASSETS_DIR,
            video_width=config.VIDEO_WIDTH,
            video_height=config.VIDEO_HEIGHT,
            styles=getattr(self, 'styles', {}),
        )
        self._img.set_callbacks(
            apply_consistency=self._apply_consistency_to_payload,
            cancellation_token=self.cancellation_token,
            quality=self.quality,
        )
        # v61.1: _set_sd_model()을 _img 초기화 이후로 이동 (기존 line 319에서 _img 미생성 크래시)
        self._set_sd_model()

        # v60.1.0 Phase 10: 영상 렌더링 위임
        self._video = VideoRenderer(
            channel=channel,
            video_width=config.VIDEO_WIDTH,
            video_height=config.VIDEO_HEIGHT,
            fps=config.FPS,
            concurrency=config.get_safe_remotion_concurrency(
                getattr(config, 'REMOTION_CONCURRENCY', 6)
            ),
        )
        self._video.set_callbacks(
            style_getter=self._style_getter,
            get_bgm_folder=self._get_bgm_folder,
            prepare_sfx_for_remotion=self._prepare_sfx_for_remotion,
        )
        if getattr(config, "is_low_vram", None) and config.is_low_vram():
            logger.info(
                "[MediaFactory] Low VRAM 보호 모드 활성화 "
                f"(GPU {getattr(config, 'GPU_VRAM_GB', 'unknown')}GB, "
                f"image_workers={getattr(config, 'IMAGE_MAX_WORKERS', 1)}, "
                f"remotion_concurrency={self._video.concurrency})"
            )

        # v59.7.0: 인물 허용, NSFW/폭력/품질만 차단 (인체 키워드 제거)
        self.SENIOR_ULTRA_NEGATIVE = (
            "nude, nudity, naked, bare skin, exposed, revealing, "
            "bikini, swimsuit, underwear, lingerie, bra, panties, thong, "
            "cleavage, nipple, nipples, areola, genital, genitals, penis, vagina, "
            "nsfw, explicit, sexual, erotic, sexy, seductive, provocative, "
            "porn, pornography, hentai, ecchi, r18, adult content, "
            "blood, bloody, gore, gory, wound, injury, cut, bruise, scar, "
            "corpse, dead body, skeleton, skull, bones, organs, viscera, "
            "violence, violent, murder, kill, weapon, knife, gun, sword, "
            "extra limbs, extra arms, extra legs, extra heads, extra fingers, "
            "multiple heads, two heads, three heads, fused heads, conjoined, "
            "deformed, disfigured, mutated, mutation, malformed, distorted, "
            "bad anatomy, incorrect anatomy, anatomical error, "
            "realistic photo, photorealistic, photo-realistic, photography, photograph, "
            "3d render, 3d model, CGI, real person, real human, "
            "portrait photography, fashion photography, glamour shot"
        )

    def _get_configured_render_engine(self) -> RenderEngine:
        """
        v57.5: 렌더링 엔진 반환 (Remotion 전용 모드)

        v57.5 변경:
        - 기본값이 Remotion으로 변경됨
        - GPU/CPU/AUTO 선택 제거
        - MoviePy는 Remotion 실패 시 자동 폴백으로만 사용

        Returns:
            RenderEngine.REMOTION (기본)
        """
        # v57.5: Remotion 전용 모드 - 항상 Remotion 반환
        logger.debug("[MediaFactory] v57.5 Remotion 전용 모드")
        return RenderEngine.REMOTION

    def _is_videotoon_local_enabled(self) -> bool:
        """Return whether the GUI/runtime opted into local VideoToon artifacts."""
        return bool(getattr(config, "VIDEOTOON_LOCAL_MODE_OVERRIDE", False))

    def _write_videotoon_production_bundle(
        self,
        *,
        project_name: str,
        script_list: List[Dict[str, Any]],
        image_prompts: List[Any],
        scene_analysis_cache: Optional[Any],
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Materialize the current production plan into the local VideoToon bundle contract."""
        try:
            from config.pack_config import get_motiontoon_config
            from modules_pro.videotoon_local import (
                VideoToonLocalWorkspace,
                build_scene_specs_from_production,
            )
            from utils.videotoon_contract import role_casting_from_motiontoon_slots

            workspace = VideoToonLocalWorkspace.from_settings(config)
            motiontoon = get_motiontoon_config()
            actor_pool = dict(getattr(motiontoon, "actor_pool", {}) or {})
            role_casting = role_casting_from_motiontoon_slots(getattr(motiontoon, "cast_slots", {}) or {})
            scenes = build_scene_specs_from_production(
                script_list=script_list,
                image_prompts=image_prompts,
                scene_analysis_cache=scene_analysis_cache,
                role_casting=role_casting,
            )
            if not scenes:
                safe_print("[VideoToon] storyboard bundle skipped: no scenes")
                return None

            manifest = workspace.write_production_bundle(
                project_name,
                scenes,
                actor_pool=actor_pool,
                role_casting=role_casting,
            )
            message = (
                f"[VideoToon] storyboard bundle saved: {manifest['manifest_path']} "
                f"({manifest['scene_count']} scenes), progress: {manifest.get('progress_path')}"
            )
            safe_print(message)
            if log_callback:
                log_callback(message)
            return manifest
        except Exception as e:
            logger.warning(f"[VideoToon] storyboard bundle 생성 실패: {e}", exc_info=True)
            if log_callback:
                log_callback(f"[VideoToon][WARN] storyboard bundle 생성 실패: {e}")
            return None

    def _init_v50_styles(self):
        """v51: v50_style_guide 기반 고품질 스타일 초기화"""
        try:
            from modules_pro.v50_style_guide import (
                get_style_for_channel,
                HORROR_STYLE,
                SENIOR_TOUCHING_STYLE,
                SENIOR_MAKJANG_STYLE
            )

            # v53: 채널별 스타일 설정 - human_style 제거 (장면별로 필요시에만 추가)
            # 인물이 모든 장면에 나오는 문제 해결
            self.styles = {
                "horror": {
                    "positive": f"{HORROR_STYLE.style_positive}, {HORROR_STYLE.background_quality}",
                    "negative": f"{HORROR_STYLE.style_negative}, {', '.join(HORROR_STYLE.avoid_general)}",
                    "human_style": HORROR_STYLE.human_style,  # 필요시에만 사용
                    "avoid_human": ', '.join(HORROR_STYLE.avoid_human),
                },
                "touching": {
                    "positive": f"{SENIOR_TOUCHING_STYLE.style_positive}, {SENIOR_TOUCHING_STYLE.background_quality}",
                    "negative": f"{SENIOR_TOUCHING_STYLE.style_negative}, {', '.join(SENIOR_TOUCHING_STYLE.avoid_general)}",
                    "human_style": SENIOR_TOUCHING_STYLE.human_style,
                    "avoid_human": ', '.join(SENIOR_TOUCHING_STYLE.avoid_human),
                },
                "makjang": {
                    "positive": f"{SENIOR_MAKJANG_STYLE.style_positive}, {SENIOR_MAKJANG_STYLE.background_quality}",
                    "negative": f"{SENIOR_MAKJANG_STYLE.style_negative}, {', '.join(SENIOR_MAKJANG_STYLE.avoid_general)}",
                    "human_style": SENIOR_MAKJANG_STYLE.human_style,
                    "avoid_human": ', '.join(SENIOR_MAKJANG_STYLE.avoid_human),
                },
            }
            logger.info("[MediaFactory] v53 스타일 가이드 적용 완료 (인물 스타일 분리)")

            # Override legacy style-guide defaults with the current VideoToon
            # production defaults. Legacy imports remain only for compatibility.
            self.styles = {
                "daily_life_toon": {
                    "positive": "premium Korean daily-life webtoon, clean line art, layered-safe background, warm natural lighting",
                    "negative": "photorealistic, 3d render, chibi, cropped head, cut off hair, UI overlay, watermark, nsfw",
                    "human_style": "consistent Korean webtoon character foreground, fully clothed",
                    "avoid_human": "extra limbs, deformed face, duplicate person",
                },
                "mystery_toon": {
                    "positive": "premium Korean mystery webtoon, restrained shadows, clean line art, layered-safe background",
                    "negative": "photorealistic, 3d render, gore, monster, cropped head, cut off hair, UI overlay, watermark, nsfw",
                    "human_style": "consistent Korean mystery webtoon character foreground, fully clothed",
                    "avoid_human": "extra limbs, deformed face, duplicate person",
                },
                "videotoon": {
                    "positive": "premium Korean webtoon video-toon, layered background, character foreground, expressive acting",
                    "negative": "photorealistic, 3d render, cropped head, cut off hair, UI overlay, watermark, nsfw",
                    "human_style": "consistent Korean webtoon character foreground, fully clothed",
                    "avoid_human": "extra limbs, deformed face, duplicate person",
                },
            }
            logger.info("[MediaFactory] VideoToon fallback styles initialized")

        except ImportError as e:
            logger.warning(f"[MediaFactory] v50_style_guide 로드 실패, 팩 설정 사용")
            # v59.1.5: 하드코딩 폴백 제거 - 팩 JSON에서 읽도록 변경
            # 팩이 없으면 빈 dict 사용 (VisualDirector가 처리)
            self.styles = {}

        # 브랜딩 설정 로드
        self.branding = self._load_branding_config()

        # 채널별 인트로 멘트 (3개 독립 채널 구조)
        self.INTRO_DAILY_LIFE_TOON = self.branding.get('daily_life_toon', {}).get('openings', [])
        self.INTRO_MYSTERY_TOON = self.branding.get('mystery_toon', {}).get('openings', [])
        # Legacy public attributes remain mapped to supported VideoToon packs.
        self.INTRO_HORROR = self.INTRO_MYSTERY_TOON
        self.INTRO_TOUCHING = self.INTRO_DAILY_LIFE_TOON
        self.INTRO_MAKJANG = self.INTRO_DAILY_LIFE_TOON
        self.INTRO_NORMAL = self.INTRO_DAILY_LIFE_TOON

    def _init_tts_engine(self) -> TTSEngine:
        """TTS 엔진 초기화 — v60.1.0 Phase 8: TTSManager 위임"""
        return self._tts._init_tts_engine(getattr(config, 'TTS_ENGINE', 'sovits'))

    def _load_branding_config(self) -> Dict:
        """branding.json 로드하고 없으면 기본값 생성 (3개 독립 채널 구조)"""
        path = os.path.join(config.DATA_DIR, "branding.json")
        # 기본값은 빈 값으로 설정 (사용자가 직접 입력하도록)
        default_branding = {
            "daily_life_toon": {
                "channel_name": "",
                "intro_file": "",
                "openings": []
            },
            "mystery_toon": {
                "channel_name": "",
                "intro_file": "",
                "openings": []
            }
        }

        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                safe_print(f"[WARN] 브랜딩 설정 로드 실패: {e}")

        # 파일이 없거나 오류 발생 시 기본값 저장 및 반환
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default_branding, f, indent=2, ensure_ascii=False)
        except Exception as e:
            safe_print(f"[WARN] 기본 브랜딩 설정 저장 실패: {e}")

        return default_branding

    # ============================================================
    # v55 → v60.1.0 Phase 4: 이미지 일관성 (ConsistencyManager 위임)
    # ============================================================
    def enable_consistency(self, character_id=None, data_dir=None, fixed_seed=None, ip_weight=0.7) -> bool:
        """이미지 일관성 모드 활성화 — ConsistencyManager 위임"""
        return self._consistency.enable(
            character_id=character_id, data_dir=data_dir,
            channel=self.channel, fixed_seed=fixed_seed, ip_weight=ip_weight
        )

    def disable_consistency(self):
        """이미지 일관성 모드 비활성화 — ConsistencyManager 위임"""
        self._consistency.disable()

    def _apply_consistency_to_payload(self, payload: Dict) -> Dict:
        """payload에 일관성 설정 적용 — ConsistencyManager 위임"""
        return self._consistency.apply_to_payload(payload)

    @property
    def consistency_enabled(self) -> bool:
        """일관성 모드 활성화 여부"""
        return self._consistency.enabled

    @property
    def fixed_seed(self) -> Optional[int]:
        """현재 고정 시드"""
        return self._consistency.fixed_seed

    # ============================================================
    # v50: 표정 추출 헬퍼
    # ============================================================
    # ============================================================
    # 부팅/설정 (기존 코드 유지)
    # ============================================================
    def _get_bgm_folder(self, mode: str = "touching") -> str:
        """
        v57.7.3: BGM 폴더 경로 결정
        v57.7.4: 유효성 검증 강화 + 유효한 채널명 검사

        우선순위:
        1. 팩의 use_channel_bgm 설정 (기존 채널 BGM 재사용)
        2. 기존 채널 설정 (self.cfg)

        Args:
            mode: "touching" 또는 "makjang" (시니어 채널용)

        Returns:
            BGM 폴더 경로
        """
        # v57.7.4: 유효한 채널 목록
        VALID_CHANNELS = ("daily_life_toon", "mystery_toon", "videotoon")

        # v57.7.3: 팩 설정 확인
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            pack_bgm_folder = str(getattr(ACTIVE_PACK.assets, "bgm_folder", "") or "").strip()
            if pack_bgm_folder:
                normalized_folder = pack_bgm_folder.replace("\\", os.sep).replace("/", os.sep)
                candidates = []
                if os.path.isabs(normalized_folder):
                    candidates.append(normalized_folder)
                candidates.append(os.path.join(config.ASSETS_DIR, "bgm", normalized_folder))
                for candidate in candidates:
                    if os.path.isdir(candidate):
                        logger.info(f"[BGM] 팩 bgm_folder 적용: {pack_bgm_folder} → {candidate}")
                        return candidate

            use_channel = ACTIVE_PACK.assets.use_channel_bgm
            if use_channel is True:
                use_channel = self.channel
            if use_channel:
                # v57.7.4: 유효하지 않은 채널명 경고
                if use_channel not in VALID_CHANNELS:
                    logger.warning(
                        f"[BGM] 유효하지 않은 use_channel_bgm 값: '{use_channel}'\n"
                        f"  - 지원 채널: {VALID_CHANNELS}\n"
                        f"  - 기본값으로 폴백합니다."
                    )
                else:
                    # 기존 채널의 BGM 사용
                    if use_channel == "daily_life_toon":
                        bgm_folder = os.path.join(config.ASSETS_DIR, "bgm", "daily")
                    elif use_channel == "mystery_toon":
                        bgm_folder = os.path.join(config.ASSETS_DIR, "bgm", "mystery")
                    elif use_channel == "videotoon":
                        bgm_folder = os.path.join(config.ASSETS_DIR, "bgm", "daily")
                    elif use_channel == "horror":
                        bgm_folder = os.path.join(config.ASSETS_DIR, "bgm", "horror", "BGM_Horror")
                    elif use_channel == "senior":
                        # 시니어는 모드에 따라 다름
                        if mode == "touching":
                            bgm_folder = os.path.join(config.ASSETS_DIR, "bgm", "senior", "touching")
                        else:
                            bgm_folder = os.path.join(config.ASSETS_DIR, "bgm", "senior", "makjang")
                    else:
                        # 일반적인 채널 경로 시도
                        bgm_folder = os.path.join(config.ASSETS_DIR, "bgm", use_channel)

                    if os.path.isdir(bgm_folder):
                        logger.info(f"[BGM] 팩 설정 적용: use_channel_bgm={use_channel} → {bgm_folder}")
                        return bgm_folder
                    else:
                        logger.warning(
                            f"[BGM] 팩 설정 경로 없음: {bgm_folder}\n"
                            f"  - BGM 파일이 없거나 경로가 잘못되었습니다.\n"
                            f"  - 기본 채널 BGM으로 폴백합니다."
                        )
                        if use_channel in {"daily_life_toon", "videotoon"}:
                            daily_fallback = os.path.join(config.ASSETS_DIR, "bgm", "senior", "touching")
                            if os.path.isdir(daily_fallback):
                                logger.info(f"[BGM] daily 계열 폴백 적용: {daily_fallback}")
                                return daily_fallback

        # 기존 로직: 채널 설정에서 가져오기
        if self.channel == "daily_life_toon":
            return self.cfg.get("bgm_folder", "") or os.path.join(config.ASSETS_DIR, "bgm", "daily")
        if self.channel == "mystery_toon":
            return self.cfg.get("bgm_folder", "") or os.path.join(config.ASSETS_DIR, "bgm", "mystery")
        if self.channel == "videotoon":
            return self.cfg.get("bgm_folder", "") or os.path.join(config.ASSETS_DIR, "bgm", "daily")
        if self.channel == "horror":
            return self.cfg.get("bgm_folder", "")
        else:
            if mode == "touching":
                return self.cfg.get("bgm_touching", "")
            else:
                return self.cfg.get("bgm_makjang", "")
    def _set_sd_model(self):
        """SD 모델 + VAE 설정 — v60.1.0 Phase 9: ImagePipeline 위임"""
        self._img.set_sd_model()
        # v62.21 H-12: SD 모델 로딩 후 연결 상태 확인
        try:
            import requests
            opt = requests.get(f"{self._img.sd_url}/sdapi/v1/options", timeout=5).json()
            loaded = opt.get("sd_model_checkpoint", "")
            if not loaded:
                logger.error("[SD] 모델 로딩 실패 — SD WebUI에 체크포인트 없음")
            else:
                logger.info(f"[SD] 모델 확인: {loaded}")
        except Exception as e:
            logger.error(f"[SD] 모델 확인 실패 (SD WebUI 연결 불가): {e}")

    def _normalize_path(self, path: str) -> str:
        """경로 정규화 - 공백이 있는 경로는 8.3 짧은 경로로 변환"""
        if not path:
            return ""

        # Windows에서 공백이 있는 경로 처리
        if " " in path and os.path.exists(path):
            try:
                import ctypes
                from ctypes import wintypes

                GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
                GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
                GetShortPathNameW.restype = wintypes.DWORD

                buffer = ctypes.create_unicode_buffer(500)
                result = GetShortPathNameW(path, buffer, 500)
                if result > 0:
                    short_path = buffer.value
                    logger.debug(f"[Path] 짧은 경로 변환: {path} -> {short_path}")
                    return short_path.replace("\\", "/")
            except Exception as e:
                logger.debug(f"[Path] 짧은 경로 변환 실패: {e}")

        return path.replace("\\", "/")

    # v60.1.0 Phase 2: 텍스트 처리 → TextProcessor (pipeline/text_processor.py)
    # 레거시 shim 제거 완료 — self._text.clean_text() 등으로 직접 호출

    # v60.1.0 Phase 8: TTS 위임 shim 제거 완료
    # _find_ref_audio, _resolve_tts_assets, _ensure_weights_loaded,
    # _check_tts_server, _restart_tts_server, _tts_post_request
    # → 호출처 0건 확인 후 삭제 (TTSManager 직접 접근: self._tts.*)

    # ============================================================
    # v33: 취소 토큰 설정
    # ============================================================
    def set_cancellation_token(self, token: CancellationToken):
        """취소 토큰 설정"""
        self.cancellation_token = token

    def cancel(self):
        """현재 작업 취소"""
        if self.cancellation_token:
            self.cancellation_token.cancel()
        logger.info("[MediaFactory] 작업 취소됨")

    def pause(self):
        """현재 작업 일시정지"""
        if self.cancellation_token:
            self.cancellation_token.pause()
        logger.info("[MediaFactory] 작업 일시정지됨")

    def resume(self):
        """일시정지된 작업 재개"""
        if self.cancellation_token:
            self.cancellation_token.resume()
        logger.info("[MediaFactory] 작업 재개됨")

    # ============================================================
    # v33: 체크포인트 경로 생성
    # ============================================================
    def _get_checkpoint_path(self, project_name: str) -> str:
        """체크포인트 파일 경로 (v57.7.6: 방어적 sanitize)"""
        safe_name = _sanitize_for_path(project_name)
        return os.path.join(config.DATA_DIR, "checkpoints", f"{safe_name}_checkpoint.json")

    def _load_plan_payload(self, json_path: str) -> Dict[str, Any]:
        """생산 입력 JSON을 로드하고 최소 필수 필드를 정규화한다."""
        if not json_path:
            raise ValueError("기획안 JSON 경로가 비어 있습니다.")
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"기획안 JSON을 찾을 수 없습니다: {json_path}")

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"기획안 JSON이 손상되었거나 형식이 잘못되었습니다: {json_path}") from e

        if not isinstance(data, dict):
            raise ValueError(f"기획안 JSON 최상위 구조가 객체(dict)가 아닙니다: {json_path}")

        project_name = (data.get("project_name") or "").strip()
        if not project_name:
            project_name = os.path.splitext(os.path.basename(json_path))[0].strip() or "untitled_project"
            data["project_name"] = project_name
            logger.warning(f"[기획안] project_name 누락 → 파일명으로 보정: {project_name}")

        if not isinstance(data.get("title"), str) or not data.get("title", "").strip():
            data["title"] = project_name

        script_list = data.get("script_list", [])
        if script_list is None:
            data["script_list"] = []
        elif not isinstance(script_list, list):
            raise ValueError("기획안의 script_list가 리스트 형식이 아닙니다.")

        return data

    def _load_or_create_checkpoint(
        self,
        project_name: str,
        checkpoint_path: str,
        resume_from_checkpoint: bool,
    ) -> ProductionCheckpoint:
        """재개 요청 시 로드하고, 없거나 손상되면 새 체크포인트로 폴백한다."""
        os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)

        if resume_from_checkpoint:
            checkpoint = ProductionCheckpoint.load(checkpoint_path)
            if checkpoint is not None:
                logger.info(f"[체크포인트] 재개 (stage={checkpoint.stage})")
                return checkpoint
            logger.warning(f"[체크포인트] 재개 요청이지만 로드 실패/없음 → 새로 시작: {checkpoint_path}")

        return ProductionCheckpoint(project_name=project_name)

    def _sanitize_checkpoint_state(
        self,
        checkpoint: ProductionCheckpoint,
        checkpoint_path: str,
    ) -> ProductionCheckpoint:
        """깨진 체크포인트를 현재 파이프라인이 재개 가능한 상태로 보정한다."""
        valid_stages = {"init", "thumbnail", "tts", "images", "assembly", "render"}
        changed = False

        if checkpoint.stage not in valid_stages:
            logger.warning(f"[체크포인트] 알 수 없는 stage '{checkpoint.stage}' → init으로 재설정")
            checkpoint.stage = "init"
            changed = True

        if not isinstance(checkpoint.subtitle_data, list):
            logger.warning("[체크포인트] subtitle_data 형식 오류 → 초기화")
            checkpoint.subtitle_data = []
            changed = True

        if not isinstance(checkpoint.image_paths, list):
            logger.warning("[체크포인트] image_paths 형식 오류 → 초기화")
            checkpoint.image_paths = []
            changed = True

        audio_exists = bool(checkpoint.audio_path and os.path.exists(checkpoint.audio_path))
        image_paths = [p for p in checkpoint.image_paths if isinstance(p, str) and p and os.path.exists(p)]
        images_valid = len(image_paths) == len(checkpoint.image_paths) and bool(image_paths)

        if checkpoint.audio_path and not audio_exists:
            logger.warning(f"[체크포인트] 오디오 파일 누락 → TTS 재생성: {checkpoint.audio_path}")
            checkpoint.audio_path = ""
            checkpoint.subtitle_data = []
            changed = True

        if checkpoint.image_paths and not images_valid:
            logger.warning("[체크포인트] 이미지 경로 일부/전체 누락 → 이미지 재생성")
            checkpoint.image_paths = []
            changed = True

        if checkpoint.image_paths != image_paths and images_valid:
            checkpoint.image_paths = image_paths
            changed = True

        if checkpoint.audio_path:
            target_stage = "images" if checkpoint.image_paths else "tts"
        elif checkpoint.stage != "init":
            target_stage = "thumbnail"
        else:
            target_stage = "init"

        if checkpoint.stage in {"assembly", "render"} and checkpoint.audio_path and checkpoint.image_paths:
            target_stage = "images"

        if checkpoint.stage != target_stage:
            logger.warning(f"[체크포인트] stage 보정: {checkpoint.stage} -> {target_stage}")
            checkpoint.stage = target_stage
            changed = True

        if changed:
            checkpoint.save(checkpoint_path)

        return checkpoint

    def _persist_image_checkpoint_progress(
        self,
        checkpoint_path: str,
        partial_image_paths: List[str],
        subtitle_data: List[Dict[str, Any]],
        image_path: Optional[str] = None,
        total_images: int = 0,
    ) -> None:
        if not self.checkpoint:
            return

        if image_path and os.path.exists(image_path):
            partial_image_paths.append(image_path)

        self.checkpoint.stage = "images"
        self.checkpoint.image_paths = list(partial_image_paths)
        self.checkpoint.images_completed = len(partial_image_paths)
        if subtitle_data:
            self.checkpoint.tts_completed = len(subtitle_data)
        elif self.checkpoint.audio_path:
            self.checkpoint.tts_completed = max(self.checkpoint.tts_completed, 1)

        try:
            self.checkpoint.save(checkpoint_path)
        except Exception as e:
            logger.debug(f"[체크포인트] 이미지 진행 저장 실패 ({len(partial_image_paths)}/{total_images}): {e}")

    # ============================================================
    # v60.1.0: 일일 생성 제한 가드
    # ============================================================
    def _create_performance_profiler(
        self,
        project_name: str,
        json_path: str,
        checkpoint_path: str,
        resume_from_checkpoint: bool,
    ) -> ProductionPerformanceProfiler:
        profiler = ProductionPerformanceProfiler(
            project_name=project_name,
            data_dir=config.DATA_DIR,
            logger=logger,
        )
        profiler.update_overview(
            channel=self.channel,
            quality=self.quality.value,
            json_path=json_path,
            checkpoint_path=checkpoint_path,
            resume_from_checkpoint=resume_from_checkpoint,
        )
        return profiler

    def _emit_profile_log(
        self,
        message: str,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        logger.info(message)
        safe_print(message)
        if log_callback:
            log_callback(message)

    def _profile_stage_start(
        self,
        profiler: Optional[ProductionPerformanceProfiler],
        key: str,
        label: str,
        log_callback: Optional[Callable[[str], None]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if profiler is None:
            return
        profiler.start_stage(key, label, metadata=metadata)
        self._emit_profile_log(f"[PROFILE] {label} 시작", log_callback)

    def _profile_stage_complete(
        self,
        profiler: Optional[ProductionPerformanceProfiler],
        key: str,
        label: str,
        log_callback: Optional[Callable[[str], None]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if profiler is None:
            return
        profiler.complete_stage(key, metadata=metadata)
        elapsed = profiler.stage_elapsed(key) or 0.0
        self._emit_profile_log(f"[PROFILE] {label} 완료 ({elapsed:.2f}초)", log_callback)

    def _profile_stage_skip(
        self,
        profiler: Optional[ProductionPerformanceProfiler],
        key: str,
        label: str,
        reason: str,
        log_callback: Optional[Callable[[str], None]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if profiler is None:
            return
        profiler.skip_stage(key, label, reason=reason, metadata=metadata)
        self._emit_profile_log(f"[PROFILE] {label} 재사용 ({reason})", log_callback)

    def _profile_stage_fail(
        self,
        profiler: Optional[ProductionPerformanceProfiler],
        key: str,
        label: str,
        error: str,
        log_callback: Optional[Callable[[str], None]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if profiler is None:
            return
        profiler.fail_stage(key, error=error, metadata=metadata)
        self._emit_profile_log(f"[PROFILE] {label} 실패: {error}", log_callback)

    def _check_daily_limit(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        일일 영상 생성 한도 체크

        ChannelRegistry에 등록된 채널이면 daily_video_limit을 확인.
        미등록 채널(DEFAULT_CHANNELS 등)은 제한 없이 통과.

        Args:
            log_callback: GUI 로그 콜백

        Returns:
            True면 생성 가능, False면 한도 초과
        """
        try:
            from utils.channel_registry import get_channel_registry
            registry = get_channel_registry()

            channel_id = getattr(self, '_channel_id', None) or self.channel
            if not registry.can_generate_today(channel_id):
                channel = registry.get_channel(channel_id)
                limit = channel.daily_video_limit if channel else 1
                msg = (
                    f"[LIMIT] 일일 생성 한도 초과: {channel_id} "
                    f"(한도: {limit}편/일). 내일 다시 시도하세요."
                )
                logger.warning(msg)
                if log_callback:
                    log_callback(msg)
                return False

            return True
        except ImportError:
            # ChannelRegistry 없으면 제한 없이 통과
            logger.debug("[LIMIT] ChannelRegistry 미사용 — 제한 없음")
            return True
        except Exception as e:
            # 예외 발생 시 안전하게 통과 (생산 중단보다 나음)
            logger.warning(f"[LIMIT] 일일 제한 체크 실패, 통과 처리: {e}")
            return True

    # ============================================================
    # ⭐ v33: 향상된 GUI 연동 파이프라인
    # ============================================================
    def produce_video_with_gui(
        self,
        json_path: str,
        thumbnail_callback: Optional[Callable[..., str]] = None,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        quality: QualityPreset = None,
        resume_from_checkpoint: bool = False,
        include_outro: bool = True,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        """
        v33: 향상된 GUI 연동 영상 제작 파이프라인

        Args:
            json_path: 기획안 JSON 경로
            thumbnail_callback: 썸네일 확인 콜백 (real_path, art_path, summary, channel_type, main_title)
            progress_callback: 진행상황 콜백 (message, percentage)
            quality: 품질 프리셋 (None이면 인스턴스 기본값 사용)
            resume_from_checkpoint: 체크포인트에서 재개 여부
            include_outro: 아웃트로 포함 여부
            log_callback: GUI 로그 콜백 (message)

        Returns:
            영상 파일 경로 또는 None
        """
        # GUI 로그 콜백 설정
        if log_callback:
            set_gui_log_callback(log_callback)

        # v62.21 M-13: 취소 토큰 매번 새로 생성 (이전 영상의 cancelled 상태 잔류 방지)
        self.cancellation_token = CancellationToken()

        # v62.10: _img에도 최신 cancellation_token 주입
        # __init__에서 set_callbacks(cancellation_token=None) 이었으므로 여기서 갱신 필수
        if self._img is not None:
            self._img.set_callbacks(
                apply_consistency=self._apply_consistency_to_payload,
                cancellation_token=self.cancellation_token,
                quality=self.quality,
            )

        # 품질 설정
        if quality:
            self.quality = quality
            self.render_settings = RenderSettings.from_quality(quality)

        logger.info(f"[MediaFactory] 제작 시작 (채널: {self.channel}, 품질: {self.quality.value})")
        safe_print(f"\n[START] [{self.channel}] v33 제작 공정 가동! (품질: {self.quality.value})")

        data = self._load_plan_payload(json_path)
        project_name = data["project_name"]
        # v57.0.2: TTS 캐릭터 일관성을 위해 channel_id 설정
        self._channel_id = project_name

        # v60.1.0: 일일 생성 제한 체크 (API 비용 폭탄 방지)
        # _channel_id 설정 이후에 체크해야 정확한 채널 ID 사용
        if not self._check_daily_limit(log_callback):
            return None

        title = data.get("title", "무제")
        thumb_title = data.get("thumbnail_title") or title
        sub_title = data.get("thumbnail_text", "")
        mode = data.get("mode", "touching")

        # v62.15: 팩-클라이언트 원칙 — 장르별 하드코딩 if/else 제거
        # ACTIVE_PACK.genre (manifest에서 로드)로 mode를 보정
        # horror 팩: genre="horror" → mode="horror" 자동 적용
        # senior 팩: genre="senior" → mode는 data["mode"] 그대로 (touching/makjang 보존)
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded and ACTIVE_PACK.genre:
            pack_genre = ACTIVE_PACK.genre  # e.g. "horror", "senior"
            # genre가 단일 고정 모드인 팩 (horror 등)은 genre로 override
            # senior 팩처럼 sub-mode가 있는 경우는 data["mode"] 그대로 유지
            if pack_genre not in ("senior", "touching", "makjang", "family", "romance"):
                mode = pack_genre

        # v54.3: 개인화된 프롬프트 최적화 적용
        personalization_result = self._apply_personalization(thumb_title, sub_title, mode)

        # 체크포인트 로드
        checkpoint_path = self._get_checkpoint_path(project_name)
        self.checkpoint = self._load_or_create_checkpoint(
            project_name=project_name,
            checkpoint_path=checkpoint_path,
            resume_from_checkpoint=resume_from_checkpoint,
        )
        self.checkpoint = self._sanitize_checkpoint_state(self.checkpoint, checkpoint_path)
        self.checkpoint.plan_json_path = json_path
        performance_profiler = self._create_performance_profiler(
            project_name=project_name,
            json_path=json_path,
            checkpoint_path=checkpoint_path,
            resume_from_checkpoint=resume_from_checkpoint,
        )
        performance_profiler.update_overview(
            title=title,
            mode=mode,
            checkpoint_stage=self.checkpoint.stage,
            personalization_enabled=bool(personalization_result),
        )

        try:
            script_list = data.get("script_list", [])
            performance_profiler.update_overview(script_turns=len(script_list or []))
            try:
                quality_report = assert_script_quality(
                    data.get("topic", ""),
                    script_list,
                    category=data.get("category", self.channel),
                    mode=mode,
                )
                logger.info(f"[품질 게이트] 통과 (score={quality_report.score})")
                safe_print(f"[품질 게이트] 통과 (score={quality_report.score})")
            except ScriptQualityError as e:
                quality_report = e.report
                if getattr(config, "TEST_MODE", False):
                    logger.warning(f"[품질 게이트] 테스트 모드 경고: {quality_report.summary()}")
                    safe_print(f"[품질 게이트] 테스트 모드 경고: {quality_report.summary()}")
                else:
                    raise

            # ============================================================
            # STEP 1: 썸네일 생성
            # ============================================================
            if self.checkpoint.stage in ["init", "thumbnail"]:
                if self.cancellation_token.check():
                    return None

                self._profile_stage_start(
                    performance_profiler,
                    "thumbnail",
                    "썸네일",
                    log_callback=log_callback,
                    metadata={"checkpoint_stage": self.checkpoint.stage},
                )
                safe_print("\n[Step 1/7] 썸네일 선생성 중...")
                if progress_callback:
                    progress_callback("썸네일 생성 중...", 5)

                # v57.7.6: 방어적 sanitize (project_name에 슬래시 등이 있을 경우 대비)
                safe_project_name = _sanitize_for_path(project_name)
                self._thumb.create_thumbnails(
                    project_name=safe_project_name,
                    title=thumb_title,
                    sub_title=sub_title,
                    base_p="",
                    mode=mode,
                    channel=self.channel,
                    styles=self.styles,
                    consistency_fn=self._apply_consistency_to_payload,
                    ultra_negative=self.SENIOR_ULTRA_NEGATIVE
                )

                thumb_real = os.path.join(config.DATA_DIR, "thumbnails", f"{safe_project_name}_REAL.jpg")
                thumb_art = os.path.join(config.DATA_DIR, "thumbnails", f"{safe_project_name}_ART.jpg")

                if thumbnail_callback:
                    safe_print("   [THUMB] GUI에서 썸네일 확인 대기 중...")

                    # v50: 채널 타입과 메인 제목 전달 (클릭률 높은 프리셋 적용)
                    channel_type = f"{self.channel}_{mode}" if self.channel == "senior" else self.channel
                    scenario_summary = f"제목: {title}\n카테고리: {self.channel}/{mode}"

                    user_choice = thumbnail_callback(
                        thumb_real, thumb_art, scenario_summary,
                        channel_type=channel_type, main_title=thumb_title
                    )

                    if user_choice == "regenerate":
                        safe_print("   [RETRY] 썸네일 재생성 요청됨")
                        # v62.19: 재귀 호출 → 썸네일만 재생성 루프 (스택 오버플로우 방지, max 3회)
                        if not hasattr(self, '_thumb_regen_count'):
                            self._thumb_regen_count = 0
                        self._thumb_regen_count += 1
                        if self._thumb_regen_count > 3:
                            safe_print("   [WARN] 썸네일 재생성 3회 초과 — 현재 썸네일로 진행")
                            logger.warning("[MediaFactory] 썸네일 재생성 3회 초과, 현재 상태로 진행")
                            self._thumb_regen_count = 0
                        else:
                            # 썸네일만 재생성 후 동일 함수를 non-recursive로 재호출
                            performance_profiler.finalize(status="restarted")
                            return self.produce_video_with_gui(
                                json_path, thumbnail_callback, progress_callback,
                                quality, False, include_outro, log_callback=log_callback)
                    elif user_choice == "cancel":
                        logger.info("[MediaFactory] 사용자 취소")
                        safe_print("   [CANCEL] 사용자가 제작을 취소했습니다")
                        performance_profiler.finalize(status="cancelled")
                        return None

                    safe_print("   [OK] 썸네일 확정 - 본편 제작 시작")
                else:
                    # v54: 썸네일 건너뛰기 시 자동으로 텍스트 오버레이 적용
                    safe_print("   [AUTO] 썸네일 자동 완성 (텍스트 오버레이 적용)")
                    self._thumb.apply_text_overlay(thumb_real, thumb_title, sub_title, mode)
                    self._thumb.apply_text_overlay(thumb_art, thumb_title, sub_title, mode)

                self.checkpoint.stage = "thumbnail"
                self.checkpoint.save(checkpoint_path)

                if progress_callback:
                    progress_callback("썸네일 확정 완료", 10)
                self._profile_stage_complete(
                    performance_profiler,
                    "thumbnail",
                    "썸네일",
                    log_callback=log_callback,
                    metadata={
                        "thumbnail_callback_used": bool(thumbnail_callback),
                        "thumbnail_paths": [thumb_real, thumb_art],
                    },
                )
            else:
                self._profile_stage_skip(
                    performance_profiler,
                    "thumbnail",
                    "썸네일",
                    reason="checkpoint_reused",
                    log_callback=log_callback,
                    metadata={"checkpoint_stage": self.checkpoint.stage},
                )

            # ============================================================
            # STEP 2: 데이터 준비
            # ============================================================
            # v57.6.5: 훅에 주제(topic) 전달 (TV 스타일)
            topic = data.get("topic", "알 수 없는 이야기")

            # v61.1: 콜드 오프닝 → hook 텍스트 변환
            # cold_open이 있으면 첫 번째 극적 대사를 hook 타이포그래피 텍스트로 사용
            # (향후 v62: TTS+이미지 기반 full 콜드 오프닝 렌더링)
            cold_open = data.get("cold_open", [])
            if cold_open:
                # 극적 대사 (브릿지 제외)에서 첫 번째 추출
                dramatic_turns = [t for t in cold_open if not t.get("_is_bridge")]
                if dramatic_turns:
                    first_dramatic = dramatic_turns[0]
                    char_name = first_dramatic.get("character", "")
                    hook_text = first_dramatic.get("text", "") or topic
                    safe_print(f"   [콜드 오프닝] hook 텍스트: [{char_name}] \"{hook_text[:30]}...\"")
                else:
                    # BUG-D/E 방어: 브릿지만 있고 극적 대사 없는 엣지 케이스
                    hook_text = data.get("hook", "") or topic
            else:
                hook_text = data.get("hook", "") or topic  # 빈 문자열이면 topic 폴백
            script_list = data.get("script_list", [])
            self._current_script_list = script_list  # v59.3.5: SFX Remotion 통합용
            self.checkpoint.script_turns = len(script_list or [])
            if not script_list:
                # v61.1 (#91): 스크립트 데이터만 매칭 (role/text 키 필수)
                _SCRIPT_KEYS = {"role", "text"}  # 최소 필수 키
                _SKIP_KEYS = {"hook", "topic", "visual_scenes", "scenes", "metadata", "cold_open", "plan"}
                for key, value in data.items():
                    if key in _SKIP_KEYS:
                        continue
                    if isinstance(value, list) and value and isinstance(value[0], dict):
                        if _SCRIPT_KEYS.issubset(value[0].keys()):
                            script_list = value
                            break

            self.checkpoint.script_turns = len(script_list or [])
            image_prompts = data.get("visual_scenes", []) or data.get("scenes", [])
            if not image_prompts:
                logger.warning("[MediaFactory] 이미지 프롬프트 누락 - 폴백 사용")
                safe_print("   !! [비상] 기획팀이 그림 요청을 누락했습니다.")
                backup = random.choice(visual_director.SAFE_FALLBACKS)
                # v61.1 (#92): 하드코딩 40 → 스크립트 턴 수 기반 (최소 10)
                fallback_count = max(10, len(script_list)) if script_list else 35
                image_prompts = [backup] * fallback_count
            performance_profiler.update_overview(
                topic=topic,
                script_turns=len(script_list or []),
                planned_image_prompts=len(image_prompts or []),
            )

            # ============================================================
            # STEP 3: 후킹 영상 (v58.4.0: Remotion에서 직접 렌더링)
            # ============================================================
            # v58.4.0: hook_clip 생성 제거! Remotion에서 topic을 받아 직접 처리
            # MoviePy hook 생성 → FFmpeg concat 복잡한 과정 완전 제거!
            safe_print("\n🎣 [Step 2/7] Hook은 Remotion에서 통합 렌더링됩니다...")
            if progress_callback:
                progress_callback("Remotion 통합 렌더링 준비...", 15)

            # ============================================================
            # ============================================================
            # STEP 4: TTS 합성 (체크포인트 지원)
            # v58.4.0: 인트로/아웃트로 제거됨 - Remotion이 Hook+본편 통합 렌더링
            # v59.8.1: TTS와 SceneAnalyzer 동시 실행 (Gemini=클라우드, VRAM 무관)
            # ============================================================
            if self.cancellation_token.check():
                performance_profiler.finalize(status="cancelled")
                return None

            # v59.8.1: SceneAnalyzer를 TTS와 동시에 시작 (GPU 안 씀 → VRAM 충돌 없음)
            scene_analysis_future = None
            scene_analysis_cache = None
            v59_enabled_early = self._is_v59_enabled()

            # v62.19: _scene_executor를 외부 스코프에서 관리 (예외 시에도 shutdown 보장)
            _scene_executor = None

            if v59_enabled_early and self.checkpoint.stage in ["init", "thumbnail", "tts"] and not self.checkpoint.audio_path:
                try:
                    from concurrent.futures import ThreadPoolExecutor as _SceneTP
                    from utils.gemini_compat import configure_gemini, get_gemini_model, GEMINI_AVAILABLE
                    if GEMINI_AVAILABLE and config.GEMINI_API_KEY:
                        configure_gemini(config.GEMINI_API_KEY)
                        _gemini_for_scene = get_gemini_model("auto")
                        if _gemini_for_scene:
                            safe_print(f"    [v59.8.1] SceneAnalyzer 비동기 시작 (TTS와 동시 진행)")
                            _scene_executor = _SceneTP(max_workers=1)
                            scene_analysis_future = _scene_executor.submit(
                                self._img.pre_analyze_scenes, script_list, _gemini_for_scene, None
                            )
                except Exception as e:
                    logger.warning(f"[v59.8.1] SceneAnalyzer 비동기 시작 실패: {e}")

            if self.checkpoint.stage in ["init", "thumbnail", "tts"] and not self.checkpoint.audio_path:
                # v59.3.5: SDXL VRAM 해방 — TTS가 GPU를 쓸 수 있도록
                if self._vram.unload_checkpoint():
                    safe_print("    [SD] VRAM 해방 (SD 모델 언로드) → TTS 풀스피드")
                self._profile_stage_start(
                    performance_profiler,
                    "tts",
                    "TTS",
                    log_callback=log_callback,
                    metadata={"script_turns": len(script_list or [])},
                )
                safe_print(f"\n🎙️ [Step 4/7] 음성 합성 중... (총 {len(script_list)}문장)")
                if progress_callback:
                    progress_callback("음성 합성 중...", 25)

                self._tts.cancellation_token = self.cancellation_token
                audio_path, subtitle_data = self._tts.generate_voice_and_subtitles_v33(
                    script_list, project_name, progress_callback,
                    sanitize_fn=_sanitize_for_path
                )

                if not audio_path or not subtitle_data:
                    logger.error("[MediaFactory] 오디오 생성 실패")
                    safe_print("🚨 오디오 생성 실패로 제작 중단.")
                    # v60.1.0: GUI 로그에 직접 전달 (사용자가 원인을 볼 수 있도록)
                    if log_callback:
                        log_callback("[ERROR] 음성 합성(TTS) 실패. GPT-SoVITS 서버가 실행 중인지 확인하세요.")
                    self._profile_stage_fail(
                        performance_profiler,
                        "tts",
                        "TTS",
                        error="audio_or_subtitle_missing",
                        log_callback=log_callback,
                    )
                    performance_profiler.finalize(status="failed")
                    return None

                self.checkpoint.audio_path = audio_path
                self.checkpoint.subtitle_data = subtitle_data
                self.checkpoint.stage = "tts"
                self.checkpoint.tts_completed = len(subtitle_data or [])
                self.checkpoint.save(checkpoint_path)
                performance_profiler.update_overview(subtitle_count=len(subtitle_data or []))
                self._profile_stage_complete(
                    performance_profiler,
                    "tts",
                    "TTS",
                    log_callback=log_callback,
                    metadata={
                        "subtitle_count": len(subtitle_data or []),
                        "audio_path": audio_path,
                    },
                )
            else:
                audio_path = self.checkpoint.audio_path
                subtitle_data = self.checkpoint.subtitle_data
                logger.info(f"[체크포인트] TTS 스킵 (이미 완료)")
                performance_profiler.update_overview(subtitle_count=len(subtitle_data or []))
                self._profile_stage_skip(
                    performance_profiler,
                    "tts",
                    "TTS",
                    reason="checkpoint_reused",
                    log_callback=log_callback,
                    metadata={"subtitle_count": len(subtitle_data or [])},
                )

            try:
                self._tts.release_tts_resources()
            except Exception as e:
                logger.debug(f"[TTS] 리소스 정리 실패 (무시): {e}")

            # v59.8.1: SceneAnalyzer 결과 수거 (TTS 중에 이미 완료됐거나 잠깐 대기)
            # v62.19: try/finally로 _scene_executor shutdown 보장 (예외 시에도 스레드 누수 방지)
            if scene_analysis_future:
                try:
                    safe_print(f"    [v59.8.1] SceneAnalyzer 결과 수거 중...")
                    scene_analysis_cache = scene_analysis_future.result(timeout=600)  # v62.19: 1800→600 (10분)
                    if scene_analysis_cache:
                        safe_print(f"    [v59.8.1] SceneAnalyzer 완료: {len(scene_analysis_cache)}개 씬 (TTS와 병렬)")
                except Exception as e:
                    logger.warning(f"[v59.8.1] SceneAnalyzer 결과 수거 실패: {e}")
                    scene_analysis_cache = None
                finally:
                    if _scene_executor is not None:
                        _scene_executor.shutdown(wait=False)
                        _scene_executor = None

            videotoon_bundle_manifest = None
            if self._is_videotoon_local_enabled():
                videotoon_bundle_manifest = self._write_videotoon_production_bundle(
                    project_name=project_name,
                    script_list=script_list,
                    image_prompts=image_prompts,
                    scene_analysis_cache=scene_analysis_cache,
                    log_callback=log_callback,
                )
                if videotoon_bundle_manifest:
                    performance_profiler.update_overview(
                        videotoon_bundle_path=videotoon_bundle_manifest.get("manifest_path"),
                        videotoon_progress_path=videotoon_bundle_manifest.get("progress_path"),
                        videotoon_scene_count=videotoon_bundle_manifest.get("scene_count"),
                    )

            # ============================================================
            # STEP 6: 이미지 생성 (체크포인트 지원)
            # v59: Visual Storytelling 모드 지원
            # ============================================================
            if self.cancellation_token.check():
                performance_profiler.finalize(status="cancelled")
                return None

            if self.checkpoint.stage in ["init", "thumbnail", "tts", "images"] and not self.checkpoint.image_paths:
                # v59.3.5: SD 모델 리로드 (TTS 중 언로드했으므로)
                if self._vram.reload_checkpoint():
                    safe_print("    [SD] 모델 리로드 완료 → 이미지 생성 준비")
                self._profile_stage_start(
                    performance_profiler,
                    "images",
                    "이미지 생성",
                    log_callback=log_callback,
                    metadata={"planned_image_prompts": len(image_prompts or [])},
                )
                partial_image_paths: List[str] = []
                self._persist_image_checkpoint_progress(
                    checkpoint_path=checkpoint_path,
                    partial_image_paths=partial_image_paths,
                    subtitle_data=subtitle_data,
                )

                def _image_checkpoint_callback(idx: int, image_path: str, completed_count: int, total_count: int):
                    del idx, completed_count
                    self._persist_image_checkpoint_progress(
                        checkpoint_path=checkpoint_path,
                        partial_image_paths=partial_image_paths,
                        subtitle_data=subtitle_data,
                        image_path=image_path,
                        total_images=total_count,
                    )

                # v59: Visual Storytelling 활성화 체크
                v59_enabled = self._is_v59_enabled()

                if v59_enabled:
                    # v59: 팩에서 target_images 미리 읽기 (딕셔너리 또는 객체)
                    v59_target = len(script_list)
                    if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                        vs_config = getattr(ACTIVE_PACK, 'visual_storytelling', None)
                        if vs_config:
                            if isinstance(vs_config, dict):
                                img_config = vs_config.get('image_generation', {})
                                if isinstance(img_config, dict):
                                    v59_target = img_config.get('target_images') or len(script_list)
                            else:
                                img_config = getattr(vs_config, 'image_generation', None)
                                if img_config:
                                    if isinstance(img_config, dict):
                                        v59_target = img_config.get('target_images') or len(script_list)
                                    else:
                                        v59_target = getattr(img_config, 'target_images', None) or len(script_list)

                    safe_print(f"\n[Step 5/7] v59 Visual Storytelling 모드로 이미지 생성...")
                    safe_print(f"    -> 목표: {v59_target}장 (고품질 씬 이미지)")
                    if progress_callback:
                        progress_callback(f"[v59] 이미지 생성 중 (목표: {v59_target}장)...", 50)

                    image_paths = self._img.generate_images_v59(
                        script_list=script_list,
                        project_name=project_name,
                        mode=mode,
                        progress_callback=progress_callback,
                        scene_analysis_cache=scene_analysis_cache,  # v59.8.1: TTS 중 완료된 캐시
                        checkpoint_callback=_image_checkpoint_callback,
                    )
                else:
                    safe_print(f"\n🎨 [Step 5/7] 총 {len(image_prompts)}장의 '{mode}' 스타일 삽화 생성...")
                    if progress_callback:
                        progress_callback("이미지 생성 중...", 50)

                    image_paths = self._img.generate_images_v33(image_prompts, project_name, mode, progress_callback)

                if not image_paths:
                    logger.error("[MediaFactory] 이미지 생성 실패")
                    safe_print("🚨 이미지 생성 실패로 제작 중단.")
                    # v60.1.0: GUI 로그에 직접 전달
                    if log_callback:
                        log_callback("[ERROR] 이미지 생성 실패. SD WebUI(localhost:7860)가 실행 중인지 확인하세요.")
                    self._profile_stage_fail(
                        performance_profiler,
                        "images",
                        "이미지 생성",
                        error="image_generation_failed",
                        log_callback=log_callback,
                    )
                    performance_profiler.finalize(status="failed")
                    return None

                self.checkpoint.image_paths = image_paths
                self.checkpoint.stage = "images"
                self.checkpoint.images_completed = len(image_paths or [])
                self.checkpoint.tts_completed = len(subtitle_data or [])
                self.checkpoint.save(checkpoint_path)
                performance_profiler.update_overview(image_count=len(image_paths or []))
                self._profile_stage_complete(
                    performance_profiler,
                    "images",
                    "이미지 생성",
                    log_callback=log_callback,
                    metadata={
                        "image_count": len(image_paths or []),
                        "v59_enabled": bool(v59_enabled),
                    },
                )
            else:
                image_paths = self.checkpoint.image_paths
                logger.info(f"[체크포인트] 이미지 생성 스킵 (이미 완료: {len(image_paths)}장)")
                performance_profiler.update_overview(image_count=len(image_paths or []))
                self._profile_stage_skip(
                    performance_profiler,
                    "images",
                    "이미지 생성",
                    reason="checkpoint_reused",
                    log_callback=log_callback,
                    metadata={"image_count": len(image_paths or [])},
                )

            # v59.3.5: 이미지 생성 완료 → SD 언로드 (Remotion 렌더링에 VRAM 여유 확보)
            if self._vram.unload_checkpoint():
                safe_print("    [SD] VRAM 해방 (SD 모델 언로드) → TTS 풀스피드")

            # ============================================================
            # STEP 7: 본편 조립
            # ============================================================
            if self.cancellation_token.check():
                performance_profiler.finalize(status="cancelled")
                return None

            self._profile_stage_start(
                performance_profiler,
                "assembly",
                "영상 조립",
                log_callback=log_callback,
                metadata={
                    "subtitle_count": len(subtitle_data or []),
                    "image_count": len(image_paths or []),
                },
            )
            safe_print("\n[Step 6/7] 본편 조립 및 믹싱...")
            if progress_callback:
                progress_callback("본편 조립 및 믹싱 중...", 75)

            # v58.4.0: _assemble_main이 Hook 포함 최종 영상 반환!
            # Remotion이 Hook + 본편 통합 렌더링 → 재조립 불필요!
            # v61.1: cold_open이 있으면 hook_text를 극적 대사로 전달
            hook_topic = hook_text if cold_open else topic
            # BUG-D 최종 방어: 빈 문자열이면 topic으로 폴백
            if not hook_topic:
                hook_topic = topic
            final_video_path = self._video.assemble_main(audio_path, subtitle_data, image_paths, mode, topic=hook_topic)

            # v60.1.0: None 방어 (Remotion 렌더링 실패 시)
            if not final_video_path:
                logger.error("[MediaFactory] 영상 조립 실패 — Remotion 렌더링 결과 없음")
                if log_callback:
                    log_callback("[ERROR] 영상 렌더링 실패. Remotion/Node.js 설치를 확인하세요.")
                self._profile_stage_fail(
                    performance_profiler,
                    "assembly",
                    "영상 조립",
                    error="remotion_output_missing",
                    log_callback=log_callback,
                )
                performance_profiler.finalize(status="failed")
                return None
            self._profile_stage_complete(
                performance_profiler,
                "assembly",
                "영상 조립",
                log_callback=log_callback,
                metadata={"remotion_output": final_video_path},
            )

            # ============================================================
            # STEP 8: 최종 출력 경로로 이동 (v58.4.0: 재조립 제거!)
            # ============================================================
            if self.cancellation_token.check():
                performance_profiler.finalize(status="cancelled")
                return None

            self._profile_stage_start(
                performance_profiler,
                "finalize",
                "최종 정리",
                log_callback=log_callback,
                metadata={"final_video_path": final_video_path},
            )
            safe_print("\n[Step 7/7] 최종 파일 정리...")
            if progress_callback:
                progress_callback("최종 파일 정리 중...", 85)

            # v57.7.6: 방어적 sanitize
            safe_project_name = _sanitize_for_path(project_name)
            output_path = os.path.join(config.DATA_DIR, "outputs", f"{safe_project_name}.mp4")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # v58.4.0: Remotion 결과물을 최종 경로로 복사
            import shutil
            shutil.copy2(final_video_path, output_path)
            logger.info(f"[v58.4.0] 최종 영상 복사: {final_video_path} → {output_path}")

            # v62.19: Remotion temp 디렉토리 삭제 (매 영상 100-300MB 잔류 방지)
            _remotion_temp = os.path.dirname(final_video_path)
            if _remotion_temp and os.path.basename(_remotion_temp).startswith("remotion_"):
                try:
                    shutil.rmtree(_remotion_temp, ignore_errors=True)
                    logger.debug(f"[정리] Remotion temp 삭제: {_remotion_temp}")
                except Exception as _rt_e:
                    logger.warning(f"[정리] Remotion temp 삭제 실패 (무시): {_rt_e}")

            # v62.10: v58.4.0에서 FFmpeg concat 제거 완료 → temp_dir 생성 불필요
            # 과거 _concat 디렉토리가 남아있으면 정리
            temp_dir = os.path.join(config.DATA_DIR, "temp", f"{safe_project_name}_concat")
            if os.path.isdir(temp_dir):
                try:
                    import shutil as _shutil
                    _shutil.rmtree(temp_dir, ignore_errors=True)
                    logger.debug(f"[정리] 레거시 temp_dir 삭제: {temp_dir}")
                except Exception as _e:
                    logger.warning(f"[정리] temp_dir 삭제 실패 (무시): {_e}")

            # ============================================================
            # STEP 9: Auto-SFX — v59.3.5: Remotion에서 이미 통합 완료!
            # 기존 FFmpeg 믹싱 제거 (MoviePy/FFmpeg concat 제거와 동일 패턴)
            # SFX 분석+매칭은 _assemble_main_remotion() 내에서 처리됨
            # ============================================================
            if progress_callback:
                progress_callback("정리 중...", 90)

            if progress_callback:
                progress_callback("정리 중...", 95)

            self._thumb.cleanup_temp_files(project_name, sanitize_fn=_sanitize_for_path)

            # 체크포인트 삭제 (성공 시)
            if os.path.exists(checkpoint_path):
                os.remove(checkpoint_path)
                logger.info("[체크포인트] 삭제됨 (제작 완료)")

            # v60.1.0: 일일 생성 카운트 증가 (성공 시에만)
            try:
                from utils.channel_registry import get_channel_registry
                registry = get_channel_registry()
                channel_id = getattr(self, '_channel_id', None) or self.channel
                registry.increment_daily_count(channel_id)
            except Exception as e:
                logger.debug(f"[LIMIT] 일일 카운트 증가 실패 (무시): {e}")

            if progress_callback:
                progress_callback("완료!", 100)

            self._profile_stage_complete(
                performance_profiler,
                "finalize",
                "최종 정리",
                log_callback=log_callback,
                metadata={"output_path": output_path},
            )
            performance_profiler.finalize(
                status="completed",
                metadata={"output_path": output_path, "report_json": performance_profiler.json_path},
            )
            self._emit_profile_log(f"[PROFILE] 리포트 저장: {performance_profiler.json_path}", log_callback)
            logger.info(f"[MediaFactory] 제작 완료: {output_path}")
            return output_path

        except InterruptedError:
            if performance_profiler:
                performance_profiler.finalize(status="cancelled")
            logger.warning("[MediaFactory] 작업이 취소됨")
            safe_print("\n[CANCEL] 작업이 취소되었습니다.")
            return None
        except Exception as e:
            if performance_profiler:
                current_stage = performance_profiler.current_stage
                if current_stage:
                    self._profile_stage_fail(
                        performance_profiler,
                        current_stage,
                        current_stage,
                        error=str(e),
                        log_callback=log_callback,
                    )
                performance_profiler.finalize(status="failed", metadata={"error": str(e)})
            if isinstance(e, ScriptQualityError):
                logger.error(f"[MediaFactory] 품질 게이트 실패: {e.report.summary()}")
                safe_print(f"\n[ERROR] 품질 게이트 실패: {e.report.summary()}")
            else:
                logger.error(f"[MediaFactory] 제작 중 오류: {e}")
                safe_print(f"\n[ERROR] 제작 중 오류 발생: {e}")
            # 체크포인트 저장 (오류 시)
            if self.checkpoint:
                self.checkpoint.save(checkpoint_path)
            raise

    # v60.1.0 Phase 5: VRAM shim 제거 완료 — self._vram.unload/reload_checkpoint() 직접 호출

    # ============================================================
    # v59.3.5 → v60.1.0 Phase 6: SFX 통합 (SFXIntegrator 위임)
    # ============================================================
    def _prepare_sfx_for_remotion(self, assembler, subtitle_data, mode):
        """SFX → Remotion 통합 — SFXIntegrator 위임"""
        self._sfx.prepare_for_remotion(
            assembler=assembler,
            subtitle_data=subtitle_data,
            script_list=self._current_script_list or [],
            channel=self.channel,
            data_dir=config.DATA_DIR,
            mode=mode
        )
    # ============================================================
    # v57.1: FFmpeg 경로 설정 (NVENC 지원)
    # ============================================================
    # ============================================================
    # v33: 아웃트로 클립 생성
    # ============================================================
    # ============================================================
    # v57.1: 캐릭터 등록 (TTS 목소리 일관성)
    # ============================================================
    def _register_characters_from_script(self, script_list: List[Dict], project_name: str) -> None:
        """
        v57.1: 대본에서 캐릭터 추출 후 TTS 엔진에 등록
        - 동일 캐릭터 = 동일 시드 = 동일 목소리 보장
        - channel_id + role 조합으로 고유 ID 생성
        """
        if not hasattr(self._tts_engine, 'register_character'):
            logger.debug("[TTS] register_character 미지원, 캐릭터 등록 스킵")
            return

        # 채널 ID 결정 (없으면 project_name 사용)
        channel_id = getattr(self, '_channel_id', None) or project_name

        # 대본에서 캐릭터 목록 추출
        characters: Dict[str, str] = {}  # {role: voice_type}
        for item in script_list:
            role = item.get("role", "나레이션")
            voice_type = item.get("voice_type", "").lower()

            # voice_type 없으면 기본값
            if not voice_type:
                voice_type = "narrator"

            if role not in characters:
                characters[role] = voice_type

        # 캐릭터 일괄 등록
        # v57.2.3: ref_audio 조회 추가 (Option C - Base 모델 안전망)
        registered = 0
        for role, voice_type in characters.items():
            char_id = f"{channel_id}_{role}"
            try:
                # ref_audio 조회 (voice_type에 맞는 기본 참조 음성)
                ref_audio_path = None
                if hasattr(self, '_tts_server_manager') and self._tts_server_manager:
                    # SoVITS 참조 음성 경로 활용 가능하면 사용
                    ref_audio_path = self._tts_server_manager.get_ref_audio_for_role(voice_type)

                self._tts_engine.register_character(
                    character_id=char_id,
                    character_type=voice_type,
                    ref_audio_path=ref_audio_path  # v57.2.3: Option C 적용
                )
                registered += 1
                logger.debug(f"[TTS] 캐릭터 등록: {char_id} → {voice_type}")
            except Exception as e:
                logger.warning(f"[TTS] 캐릭터 등록 실패: {char_id} - {e}")

        if registered > 0:
            logger.info(f"[TTS] 캐릭터 {registered}명 등록 완료 (채널: {channel_id})")
            safe_print(f"   🎭 캐릭터 {registered}명 등록 (일관된 목소리 적용)")

    # v60.1.0 Phase 8: _generate_voice_and_subtitles_v33 shim 제거 — self._tts 직접 호출
    def _is_v59_enabled(self) -> bool:
        """
        v59: Visual Storytelling 활성화 여부 확인

        체크 순서:
        1. GUI 설정 (settings_manager)
        2. 팩 설정 (visual_storytelling.enabled)
        """
        try:
            # 1. GUI 설정 체크 (우선)
            from gui.settings_manager import SettingsManager
            # v59: config_dir 인자 필요
            gui_settings_dir = os.path.join(config.DATA_DIR)
            sm = SettingsManager(config_dir=gui_settings_dir)
            gui_enabled = sm.get_visual_storytelling_enabled()

            if gui_enabled:
                # 2. 팩에서 v59 지원 여부 확인
                if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                    # 팩에 visual_storytelling 설정이 있는지 확인
                    vs_config = getattr(ACTIVE_PACK, 'visual_storytelling', None)
                    if vs_config:
                        # 딕셔너리 또는 객체 모두 지원
                        if isinstance(vs_config, dict):
                            pack_enabled = vs_config.get('enabled', False)
                        else:
                            pack_enabled = getattr(vs_config, 'enabled', False)

                        if pack_enabled:
                            logger.info("[v59] Visual Storytelling 활성화 (GUI + 팩 지원)")
                            return True
                    # 팩에 v59 설정이 없어도 GUI에서 켜면 기본 v59 로직 사용
                    logger.info("[v59] Visual Storytelling 활성화 (GUI, 팩 기본값 사용)")
                    return True
                else:
                    logger.info("[v59] Visual Storytelling 활성화 (GUI)")
                    return True

            return False

        except Exception as e:
            logger.warning(f"[v59] 활성화 체크 실패: {e}")
            return False

    # v60.1.0 Phase 9: _pre_analyze_scenes shim 제거 — self._img.pre_analyze_scenes() 직접 호출

    # v60.1.0 Phase 9: 이미지 생성 shim 제거 — self._img.generate_images_v59/v33() 직접 호출

    def produce_batch(
        self,
        json_paths: List[str],
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        quality: QualityPreset = None,
        log_callback: Optional[Callable[[str], None]] = None,  # v61.1 (#93)
    ) -> List[Tuple[str, Optional[str]]]:
        """
        v33: 배치 처리 (여러 기획안 연속 제작)

        Args:
            json_paths: 기획안 JSON 경로 리스트
            progress_callback: 진행상황 콜백 (project_name, current_idx, total)
            quality: 품질 프리셋

        Returns:
            List[(json_path, output_path or None)]
        """
        logger.info(f"[배치] 배치 처리 시작: {len(json_paths)}개 프로젝트")
        safe_print(f"\n🎬 배치 처리 시작: {len(json_paths)}개 프로젝트")

        results = []
        total = len(json_paths)

        for i, json_path in enumerate(json_paths):
            # 취소 체크
            if self.cancellation_token and self.cancellation_token.check():
                logger.warning("[배치] 배치 처리 취소됨")
                break

            project_name = os.path.basename(json_path).replace(".json", "")
            safe_print(f"\n{'='*60}")
            safe_print(f"📦 [{i+1}/{total}] {project_name}")
            safe_print(f"{'='*60}")

            if progress_callback:
                progress_callback(project_name, i + 1, total)

            try:
                output_path = self.produce_video_with_gui(
                    json_path,
                    thumbnail_callback=None,
                    progress_callback=None,
                    quality=quality,
                    resume_from_checkpoint=True,
                    include_outro=True,
                    log_callback=log_callback,  # v61.1 (#93): 로그 콜백 전달
                )
                results.append((json_path, output_path))

                if output_path:
                    logger.info(f"[배치] {project_name} 완료: {output_path}")
                else:
                    logger.warning(f"[배치] {project_name} 실패")

            except Exception as e:
                logger.error(f"[배치] {project_name} 오류: {e}")
                results.append((json_path, None))

            # 메모리 정리
            gc.collect()

        logger.info(f"[배치] 배치 처리 완료: {sum(1 for _, o in results if o)}/{total} 성공")
        return results

    # ============================================================
    # 기존 produce_video() 유지 (CLI 모드용)
    # ============================================================
    def produce_video(self, json_path: str) -> Optional[str]:
        """
        기존 CLI 모드 (GUI 없이 바로 제작)
        """
        return self.produce_video_with_gui(json_path, None, None)

    # ============================================================
    # 나머지 기존 메서드들 (v56.5: TTS 엔진 추상화 적용)
    # ============================================================
    # v60.1.0 Phase 10: _assemble_main shim 제거 — self._video.assemble_main() 직접 호출
    def generate_test_thumbnail(self, style_name: str, top_text: str, main_text: str, output_path: str, mode: str = None):
        """테스트용 썸네일 생성 — ThumbnailMaker 위임"""
        actual_mode = mode or self.mode
        _reviewer = content_reviewer if NSFW_DETECTOR_AVAILABLE else None
        return self._thumb.generate_test_thumbnail(
            style_name=style_name, top_text=top_text, main_text=main_text,
            output_path=output_path, mode=actual_mode, channel=self.channel,
            styles=self.styles, consistency_fn=self._apply_consistency_to_payload,
            content_reviewer=_reviewer, ultra_negative=self.SENIOR_ULTRA_NEGATIVE
        )
    
    # _create_thumbnails_v20 shim 제거 — self._thumb.create_thumbnails() 직접 호출

    # _apply_thumbnail_text_overlay shim 제거 — self._thumb.apply_text_overlay() 직접 호출

    def _apply_personalization(
        self,
        title: str,
        sub_title: str,
        mode: str,
        log_to_gui: bool = True
    ) -> dict:
        """
        v54.3: 개인화된 프롬프트 최적화 적용

        채널 데이터 기반 학습된 패턴을 현재 콘텐츠에 적용

        Args:
            title: 제목
            sub_title: 서브 제목
            mode: 카테고리 모드
            log_to_gui: GUI에 로그 출력 여부

        Returns:
            {
                'title_optimization': {...},
                'thumbnail_optimization': {...},
                'upload_recommendation': {...},
                'has_data': bool,
            }
        """
        result = {
            'title_optimization': None,
            'thumbnail_optimization': None,
            'upload_recommendation': None,
            'has_data': False,
            'overall_score': 50
        }

        if not PROMPT_OPTIMIZER_AVAILABLE:
            return result

        try:
            optimizer = get_prompt_optimizer(config.DATA_DIR, self.channel)

            # 학습 상태 확인
            status = optimizer.get_learning_status()
            if not status.get('has_enough_data'):
                if log_to_gui:
                    safe_print(f"   ℹ️ [개인화] 학습 데이터 부족 ({status.get('total_videos_analyzed', 0)}/10)")
                return result

            result['has_data'] = True

            # 제목 최적화
            title_opt = optimizer.optimize_title(title)
            result['title_optimization'] = title_opt

            if log_to_gui:
                score = title_opt.get('score', 50)
                if score >= 70:
                    safe_print(f"   ✅ [개인화] 제목 점수: {score}/100 (우수)")
                elif score >= 50:
                    safe_print(f"   📊 [개인화] 제목 점수: {score}/100 (양호)")
                else:
                    safe_print(f"   ⚠️ [개인화] 제목 점수: {score}/100 (개선 필요)")

                # 제안 출력
                for suggestion in title_opt.get('suggestions', [])[:2]:
                    safe_print(f"      💡 {suggestion}")

            # 썸네일 최적화
            thumb_opt = optimizer.optimize_thumbnail_prompt(title, sub_title, mode)
            result['thumbnail_optimization'] = thumb_opt

            if log_to_gui and thumb_opt.get('suggestions'):
                for suggestion in thumb_opt.get('suggestions', [])[:1]:
                    safe_print(f"      🖼️ {suggestion}")

            # 업로드 시간 추천
            upload_rec = optimizer.get_optimal_upload_time()
            result['upload_recommendation'] = upload_rec

            if log_to_gui and upload_rec.get('confidence', 0) > 0.5:
                day_names = ["월", "화", "수", "목", "금", "토", "일"]
                safe_print(f"      ⏰ 추천 업로드: {day_names[upload_rec.get('recommended_day', 5)]}요일 "
                          f"{upload_rec.get('recommended_hour', 18)}시")

            result['overall_score'] = title_opt.get('score', 50)

            return result

        except Exception as e:
            logger.warning(f"[개인화] 최적화 적용 실패: {e}")
            return result
    # _cleanup_temp_files shim 제거 — self._thumb.cleanup_temp_files() 직접 호출
