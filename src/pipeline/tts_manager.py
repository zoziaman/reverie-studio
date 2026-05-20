# src/pipeline/tts_manager.py
"""
v60.1.0 Phase 8: TTS 관리 모듈

media_factory.py에서 추출한 TTS 관련 22개 메서드.
5개 카테고리:
  1. Asset Resolution (5): find_ref_audio, resolve_tts_assets, ensure_weights_loaded,
     load_voice_metadata, boot_sovits_engine
  2. Server Management (4): init_tts_engine, check_tts_server, restart_tts_server,
     ensure_sovits_engine/qwen3_engine
  3. TTS Synthesis (7): tts_post_request, synthesize_with_sovits/qwen3,
     generate_single_tts, generate_tts_with_engine/legacy, amplify_tts_volume
  4. Audio Pipeline (3): generate_voice_and_subtitles_v33,
     generate_voice_and_subtitles_sequential, generate_voice_and_subtitles
  5. Clip Factory (3): tts_line_to_clip, tts_line_to_clip_legacy,
     estimate_silence_duration (v60.1.0: 인라인 이동)

원본 위치: media_factory.py L506-555, L654-668, L732-734,
          L1005-1377, L1990-2520, L3792-3961, L4166-4361
"""
import gc
import os
import random
import time
import logging
import subprocess
import sys
# v62.17: Windows 콘솔 창 깜빡임 방지 (TTS 100개 생성 시 100번 콘솔 뜨는 문제)
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
def _hidden_startupinfo():
    """Windows에서 subprocess 콘솔 창 완전 차단 (startupinfo + creationflags 이중 방어)"""
    if sys.platform == 'win32':
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return si
    return None
from glob import glob
from typing import Dict, Any, List, Optional, Tuple, Callable
_TEMP_VOICE_ALIAS_MAP = {
    "middle_man": "young_man",
    "middle_woman": "young_woman",
    "man": "young_man",
    "woman": "young_woman",
    "child": "young_woman",
}

# v62.17: get_logger 사용 — __name__("pipeline.tts_manager")은 reverie.* 로그 계층 밖이라 로그 파일에 기록 안 됨
try:
    from utils.logger import get_logger
    logger = get_logger("tts_manager")
except ImportError:
    logger = logging.getLogger("tts_manager")
    logger.setLevel(logging.INFO)


def _safe_close_resource(resource, label: str):
    """close() 가능한 리소스를 닫고 실패 시 로그만 남긴다."""
    if resource is None:
        return
    close_fn = getattr(resource, "close", None)
    if close_fn is None:
        return
    try:
        close_fn()
    except Exception as e:
        logger.debug(f"[TTS] {label} close 실패: {e}")


def _safe_remove_file(path: str, label: str):
    """임시 파일 삭제 실패를 조용히 삼키지 않고 debug 로그로 남긴다."""
    if not path or not os.path.exists(path):
        return
    try:
        os.remove(path)
    except OSError as e:
        logger.debug(f"[TTS] {label} 삭제 실패: {e}")

# v60.1.0: MoviePy 의존성 보호 — TTS 오디오 조립에 필수
try:
    from moviepy.editor import AudioClip, AudioFileClip, concatenate_audioclips
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    AudioClip = None
    AudioFileClip = None
    concatenate_audioclips = None
    logger.warning(
        "[TTS] moviepy 미설치! pip install moviepy 실행 필요. "
        "TTS 오디오 조립이 불가합니다."
    )


class TTSManager:
    """TTS 음성 합성 관리

    GPT-SoVITS / Qwen3-TTS 엔진을 통한 음성 합성,
    모델 자산 해결, 서버 관리, 볼륨 정규화를 담당.

    외부 의존성은 생성자 파라미터 또는 메서드 파라미터로 주입받습니다.
    """

    def __init__(
        self,
        channel: str,
        target_language: str,
        sovits_url: str,
        sovits_root: str,
        assets_dir: str,
        data_dir: str,
        ffmpeg_path: str = "",
        video_width: int = 1920,
        video_height: int = 1080,
    ):
        self.channel = channel
        self.target_language = target_language
        self.sovits_url = sovits_url
        self.sovits_root = sovits_root
        self.assets_dir = assets_dir
        self.data_dir = data_dir
        self.ffmpeg_path = ffmpeg_path
        self.video_width = video_width
        self.video_height = video_height

        # TTS 상태 (TTSState)
        self._tts_engine = None
        self._using_sovits = True
        self._hybrid_tts_enabled = False
        self._sovits_roles: set = set()
        self._sovits_engine = None
        self._qwen3_engine = None
        self._audio_synthesizer = None
        self._tts_server_manager = None
        self.current_gpt: Optional[str] = None
        self.current_sovits: Optional[str] = None
        self.voice_metadata: Dict = {}

        # 테스트 모드 설정
        self._test_mode = False
        self._test_duration = 0.0

        # 취소 토큰 (외부에서 주입)
        self.cancellation_token = None

        # 콜백: text 처리 (TextProcessor에서 주입)
        self._clean_text_fn: Optional[Callable] = None
        self._clean_text_for_tts_fn: Optional[Callable] = None
        self._clean_text_for_retry_fn: Optional[Callable] = None
        self._role_key_normalize_fn: Optional[Callable] = None
        self._split_into_sentences_fn: Optional[Callable] = None
        self._normalize_path_fn: Optional[Callable] = None

        # 콜백: VRAM 해제 (VRAMManager에서 주입)
        self._release_vram_fn: Optional[Callable] = None

        # 콜백: 캐릭터 등록 (이미지 파이프라인 교차 호출)
        self._register_characters_fn: Optional[Callable] = None

    def set_callbacks(
        self,
        clean_text: Optional[Callable[[str], str]] = None,
        clean_text_for_tts: Optional[Callable[[str], str]] = None,
        clean_text_for_retry: Optional[Callable[[str, int], str]] = None,
        role_key_normalize: Optional[Callable[[str], str]] = None,
        split_into_sentences: Optional[Callable[[str], List[str]]] = None,
        normalize_path: Optional[Callable[[str], str]] = None,
        release_vram: Optional[Callable[[], None]] = None,
        register_characters: Optional[Callable[[List[Dict], str], None]] = None,
    ) -> None:
        """
        외부 의존 콜백 주입

        TTSManager는 텍스트 처리, VRAM 관리 등 외부 기능을 콜백으로 주입받습니다.
        orchestrator가 파이프라인 초기화 시 이 메서드로 등록합니다.

        Args:
            clean_text: 텍스트 전처리 (특수문자/이모지 제거)
            clean_text_for_tts: TTS 전용 텍스트 전처리 (숫자/말줄임표 발음 보정)
            clean_text_for_retry: 재시도 시 텍스트 단순화 (level별)
            role_key_normalize: 역할명 정규화 (나레이션→narrator)
            split_into_sentences: 텍스트→문장 분리
            normalize_path: 경로 정규화 (8.3 짧은 경로 변환)
            release_vram: GPU VRAM 해제
            register_characters: 대본에서 캐릭터 추출→TTS 등록
        """
        if clean_text:
            self._clean_text_fn = clean_text
        if clean_text_for_tts:
            self._clean_text_for_tts_fn = clean_text_for_tts
        if clean_text_for_retry:
            self._clean_text_for_retry_fn = clean_text_for_retry
        if role_key_normalize:
            self._role_key_normalize_fn = role_key_normalize
        if split_into_sentences:
            self._split_into_sentences_fn = split_into_sentences
        if normalize_path:
            self._normalize_path_fn = normalize_path
        if release_vram:
            self._release_vram_fn = release_vram
        if register_characters:
            self._register_characters_fn = register_characters

    def _get_valid_voice_types(self, include_aliases: bool = True) -> set:
        """현재 환경에서 허용할 voice_type 집합을 반환한다."""
        if not getattr(self, "_valid_voice_types_cache", None):
            _NON_VOICE_DIRS = {"custom", "lora"}
            _TRAINING_SUFFIX = "_training"
            try:
                import json as _json

                _meta_path = os.path.join(self.assets_dir, "models", "voice_metadata.json")
                _meta_keys = set()
                if os.path.exists(_meta_path):
                    with open(_meta_path, encoding="utf-8") as _f:
                        _meta_keys = set(_json.load(_f).keys())

                _models_root = os.path.join(self.assets_dir, "models")
                _model_dirs = set()
                if os.path.isdir(_models_root):
                    _model_dirs = {
                        d for d in os.listdir(_models_root)
                        if os.path.isdir(os.path.join(_models_root, d))
                        and d not in _NON_VOICE_DIRS
                        and not d.endswith(_TRAINING_SUFFIX)
                    }

                self._valid_voice_types_cache = _meta_keys | _model_dirs | {"narrator", "child"}
            except Exception as _e:
                logger.warning(f"[TTS] valid_voice_types 동적 로딩 실패, 기본값 사용: {_e}")
                self._valid_voice_types_cache = {
                    "narrator", "narrator_male", "narrator_female",
                    "grandma", "grandpa",
                    "young_man", "young_woman", "child",
                }

        valid_voice_types = set(self._valid_voice_types_cache)
        if include_aliases:
            valid_voice_types.update(_TEMP_VOICE_ALIAS_MAP.keys())
        return valid_voice_types

    # ============================================================
    # 초기화
    # ============================================================

    def initialize(
        self,
        tts_engine_type: str = "sovits",
        hybrid_enabled: bool = False,
        sovits_roles_str: str = "narrator,grandpa",
        test_mode: bool = False,
        test_duration: float = 0,
    ):
        """
        TTS 시스템 초기화

        TTS 엔진 생성, 하이브리드 모드 설정, 서버 매니저 연결을 수행합니다.
        orchestrator.__init__에서 호출됩니다.

        Args:
            tts_engine_type: "sovits" 또는 "supertonic"
            hybrid_enabled: legacy SoVITS/Qwen3 하이브리드 모드 (Qwen3 비활성화로 자동 해제)
            sovits_roles_str: SoVITS 전용 역할 (쉼표 구분)
            test_mode: 테스트 모드 (무음 WAV 생성)
            test_duration: 테스트 WAV 길이 (초)
        """
        self._test_mode = test_mode
        self._test_duration = test_duration
        requested_tts_engine = (tts_engine_type or "sovits").strip().lower()
        if requested_tts_engine not in {"sovits", "supertonic"}:
            logger.warning(
                "[TTSManager] 지원하지 않는 TTS_ENGINE '%s', sovits로 대체",
                requested_tts_engine,
            )
            requested_tts_engine = "sovits"
        if hybrid_enabled:
            logger.warning(
                "[TTSManager] hybrid TTS는 Qwen3 비활성화 상태라 안전하게 비활성화합니다."
            )
            hybrid_enabled = False

        # TTS 엔진 생성
        self._tts_engine = self._init_tts_engine(requested_tts_engine)

        # SoVITS 모드 설정
        engine_name = (getattr(self._tts_engine, "engine_name", "") or "").lower()
        self._using_sovits = requested_tts_engine == "sovits" or "sovits" in engine_name
        self._hybrid_tts_enabled = hybrid_enabled

        # SoVITS 역할 설정
        self._sovits_roles = set(
            r.strip().lower() for r in sovits_roles_str.split(",") if r.strip()
        )
        self._sovits_roles.update({"나레이션", "할아버지", "narration"})

        # 하이브리드 모드용 엔진
        self._sovits_engine = None
        self._qwen3_engine = None

        # SoVITS 서버 초기화
        if self._using_sovits or self._hybrid_tts_enabled:
            try:
                from modules_pro.audio_synthesizer import AudioSynthesizer
                from modules_pro.tts_server_manager import TTSServerManager

                self._audio_synthesizer = AudioSynthesizer(
                    channel=self.channel, sovits_url=self.sovits_url
                )
                self._tts_server_manager = TTSServerManager(
                    sovits_url=self.sovits_url, sovits_root=self.sovits_root
                )
            except ImportError as e:
                logger.warning(f"[TTSManager] TTS 모듈 로드 실패: {e}")
                self._audio_synthesizer = None
                self._tts_server_manager = None

            self.current_gpt = None
            self.current_sovits = None
            self.voice_metadata = self.load_voice_metadata()

            if self._using_sovits:
                self.boot_sovits_engine()
        else:
            self._audio_synthesizer = None
            self._tts_server_manager = None
            self.current_gpt = None
            self.current_sovits = None
            self.voice_metadata = self.load_voice_metadata()

        logger.info(
            f"[TTSManager] 초기화 완료: engine={requested_tts_engine}, "
            f"hybrid={hybrid_enabled}"
        )

    # ============================================================
    # 1. Asset Resolution
    # ============================================================

    def load_voice_metadata(self) -> Dict:
        """v57.8: 통합 voice_metadata.json 로드"""
        result = {}
        unified_path = os.path.join(self.assets_dir, "models", "voice_metadata.json")
        if os.path.exists(unified_path):
            try:
                import json

                with open(unified_path, "r", encoding="utf-8") as f:
                    result = json.load(f)
                logger.debug(
                    f"[TTS] 통합 voice_metadata 로드 완료: {len(result)}개 역할"
                )
            except Exception as e:
                logger.warning(f"[TTS] voice_metadata 로드 실패: {e}")
        return result

    def boot_sovits_engine(self):
        """SoVITS 엔진 부팅"""
        if self._tts_server_manager:
            self._tts_server_manager.boot_engine()

    def find_ref_audio(self, char_dir: str, emotion: str) -> Optional[str]:
        """감정별 참조 오디오 파일 탐색"""
        emo = (emotion or "calm").lower().strip()
        candidates = [
            os.path.join(char_dir, f"{emo}.mp3"),
            os.path.join(char_dir, f"{emo}.wav"),
            os.path.join(char_dir, "calm.wav"),
            os.path.join(char_dir, "calm.mp3"),
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        any_files = glob(os.path.join(char_dir, "*.*"))
        return any_files[0] if any_files else None

    def resolve_tts_assets(
        self, role_key: str, emotion: str, voice_type: str = None
    ) -> Tuple[str, str, Optional[str], str]:
        """
        v57.8: TTS 자산 해결 (모델 경로 + 참조 오디오 + 참조 텍스트)

        우선순위:
        1. voice_type 직접 지정
        2. role_key에서 추론
        3. 팩 narrator 설정
        """
        from config.pack_config import ACTIVE_PACK, PACK_CONFIG_AVAILABLE

        # v62.10: valid_voice_types 동적 로딩 — 인스턴스 캐시 활용 (35턴 루프 중 파일 재읽기 방지)
        # 새 TTS 음성 추가 시 코드 수정 불필요 (voice_metadata.json + models/ 폴더만 추가)
        # narrator는 runtime에서 narrator_male/female로 분기되는 alias → 항상 포함
        if not getattr(self, '_valid_voice_types_cache', None):
            _NON_VOICE_DIRS = {"custom", "lora"}          # 비음성 폴더
            _TRAINING_SUFFIX = "_training"                 # 학습용 임시 폴더 제외
            try:
                import json as _json
                _meta_path = os.path.join(self.assets_dir, "models", "voice_metadata.json")
                if os.path.exists(_meta_path):
                    with open(_meta_path, encoding="utf-8") as _f:
                        _meta_keys = set(_json.load(_f).keys())
                    # models/ 폴더 이름도 합집합 (voice_metadata 누락된 폴더 방어)
                    # _training 폴더 및 비음성 폴더 제외
                    _model_dirs = {
                        d for d in os.listdir(os.path.join(self.assets_dir, "models"))
                        if os.path.isdir(os.path.join(self.assets_dir, "models", d))
                        and d not in _NON_VOICE_DIRS
                        and not d.endswith(_TRAINING_SUFFIX)
                    }
                    self._valid_voice_types_cache = _meta_keys | _model_dirs | {"narrator", "child"}
                else:
                    raise FileNotFoundError(_meta_path)
            except Exception as _e:
                logger.warning(f"[TTS] valid_voice_types 동적 로딩 실패, 기본값 사용: {_e}")
                # 폴백: 하드코딩 기본값
                self._valid_voice_types_cache = {
                    "narrator", "narrator_male", "narrator_female",
                    "grandma", "grandpa",
                    "young_man", "young_woman", "child",
                }
        valid_voice_types = self._get_valid_voice_types(include_aliases=True)

        if voice_type and voice_type.lower() in valid_voice_types:
            rk = voice_type.lower()
        elif self._role_key_normalize_fn:
            rk = self._role_key_normalize_fn(role_key)
        else:
            rk = role_key.lower()

        emo = (emotion or "calm").lower().strip()

        # narrator 타입 결정
        if rk == "narrator":
            narrator_type = "narrator_male"
            if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                # v62.40: narrator_voice 우선 확인 (임의 voice_type 허용 — 채널별 고유 목소리 지정)
                narrator_voice_override = getattr(ACTIVE_PACK.tts, "narrator_voice", "")
                if narrator_voice_override and narrator_voice_override in self._get_valid_voice_types(include_aliases=False):
                    narrator_type = narrator_voice_override
                    logger.info(f"[TTS] narrator_voice 오버라이드: {narrator_type}")
                else:
                    # 기존 narrator_male/female 분기
                    pack_narrator = getattr(ACTIVE_PACK.tts, "narrator", None)
                    if pack_narrator in ("narrator_male", "narrator_female"):
                        narrator_type = pack_narrator
                    else:
                        pack_narrator = getattr(ACTIVE_PACK.assets, "narrator", None)
                        if pack_narrator in ("narrator_male", "narrator_female"):
                            narrator_type = pack_narrator
                        else:
                            use_channel_tts = ACTIVE_PACK.assets.use_channel_tts
                            if use_channel_tts == "horror":
                                narrator_type = "narrator_male"
                            elif use_channel_tts == "senior":
                                narrator_type = "narrator_female"
            rk = narrator_type
            logger.info(f"[TTS] narrator 타입 결정: {narrator_type}")

        # ModelManager를 통한 동적 모델 조회
        try:
            from utils.model_manager import get_model_manager

            mm = get_model_manager()
            model_info = mm.resolve_model_for_character(self.channel, rk)

            if model_info:
                gpt_w = model_info["gpt_weights"]
                sov_w = model_info["sovits_weights"]
                char_dir = model_info["path"]

                full_model_info = mm.get_model_info(model_info["model_id"])
                original_emo = emo

                if full_model_info and emo in full_model_info.emotions:
                    emo_info = full_model_info.emotions[emo]
                    ref_audio_rel = emo_info.reference_audio
                    ref_audio = (
                        os.path.join(char_dir, ref_audio_rel) if ref_audio_rel else None
                    )
                    ref_text = emo_info.reference_text or "안녕하세요."
                    if ref_audio and os.path.exists(ref_audio):
                        return gpt_w, sov_w, ref_audio, ref_text

                # 감정 폴백
                if full_model_info and full_model_info.emotions:
                    if original_emo not in full_model_info.emotions:
                        available = list(full_model_info.emotions.keys())
                        logger.warning(
                            f"[TTS Fallback] 미등록 감정 '{original_emo}' → "
                            f"기본 감정 사용. 가능: {available}"
                        )

                    default_emo = full_model_info.default_emotion
                    if default_emo not in full_model_info.emotions:
                        default_emo = (
                            list(full_model_info.emotions.keys())[0]
                            if full_model_info.emotions
                            else "calm"
                        )

                    if default_emo in full_model_info.emotions:
                        emo_info = full_model_info.emotions[default_emo]
                        ref_audio_rel = emo_info.reference_audio
                        ref_audio = (
                            os.path.join(char_dir, ref_audio_rel)
                            if ref_audio_rel
                            else None
                        )
                        ref_text = emo_info.reference_text or "안녕하세요."
                        if ref_audio and os.path.exists(ref_audio):
                            logger.info(
                                f"[TTS Fallback] '{original_emo}' → '{default_emo}' "
                                f"폴백 성공"
                            )
                            return gpt_w, sov_w, ref_audio, ref_text

                ref_audio = self.find_ref_audio(char_dir, emo)
                ref_text = self.voice_metadata.get(rk, {}).get(emo, "안녕하세요.")
                if ref_audio:
                    return gpt_w, sov_w, ref_audio, ref_text

        except Exception as e:
            logger.warning(f"[TTS] ModelManager 조회 실패, 기본 로직 사용: {e}")

        # 폴백: 통합 폴더 기반
        # v62.9: young_man/young_woman 폴더 실존 → man/woman 폴백 제거
        # middle_man/woman 모델 없을 때 young_man/young_woman으로 폴백
        # v62.9b: man/woman 구버전 호환 폴백 (팩 설정 오류 방지)
        voice_fallback_map = dict(_TEMP_VOICE_ALIAS_MAP)
        original_rk = rk
        char_dir = os.path.join(self.assets_dir, "models", rk)
        gpt_w = os.path.join(char_dir, "gpt_weights.ckpt")
        sov_w = os.path.join(char_dir, "sovits_weights.pth")

        if not os.path.exists(gpt_w) and rk in voice_fallback_map:
            fallback_rk = voice_fallback_map[rk]
            fallback_char_dir = os.path.join(self.assets_dir, "models", fallback_rk)
            fallback_gpt_w = os.path.join(fallback_char_dir, "gpt_weights.ckpt")
            fallback_sov_w = os.path.join(fallback_char_dir, "sovits_weights.pth")
            if os.path.exists(fallback_gpt_w):
                logger.info(f"[TTS] 모델 폴백: {rk} → {fallback_rk}")
                rk = fallback_rk
                char_dir = fallback_char_dir
                gpt_w = fallback_gpt_w
                sov_w = fallback_sov_w

        ref_audio = self.find_ref_audio(char_dir, emo)
        ref_text = self.voice_metadata.get(rk, {}).get(emo, "안녕하세요.")
        logger.debug(
            f"[TTS] 통합 폴더 사용: {rk}/{emo} (원본: {original_rk})"
        )
        return gpt_w, sov_w, ref_audio, ref_text

    def ensure_weights_loaded(self, gpt_w: str, sov_w: str) -> bool:
        """TTS 모델 가중치 로드 (지수 백오프 적용)"""
        import requests

        if not self._using_sovits:
            return True
        if self.current_gpt == gpt_w:
            return True
        if not os.path.exists(gpt_w):
            logger.error(f"[TTS] GPT 가중치 파일 없음: {gpt_w}")
            return False
        if not os.path.exists(sov_w):
            logger.error(f"[TTS] SoVITS 가중치 파일 없음: {sov_w}")
            return False
        if not self.check_tts_server():
            logger.error("[TTS] 서버 사용 불가")
            return False

        normalize_path = self._normalize_path_fn or (lambda x: x)

        for attempt in range(3):
            try:
                gpt_url = (
                    f"{self.sovits_url}/set_gpt_weights?"
                    f"weights_path={normalize_path(gpt_w)}"
                )
                res1 = requests.get(gpt_url, timeout=30)
                sov_url = (
                    f"{self.sovits_url}/set_sovits_weights?"
                    f"weights_path={normalize_path(sov_w)}"
                )
                res2 = requests.get(sov_url, timeout=30)
                # v61.1-fix(#17): HTTP 상태코드 검증 — 실패 시 current 미설정
                if res1.status_code != 200 or res2.status_code != 200:
                    logger.warning(
                        f"[TTS] 가중치 로드 HTTP 실패: GPT={res1.status_code}, SoVITS={res2.status_code}"
                    )
                    raise RuntimeError(f"HTTP 상태 코드 비정상: {res1.status_code}, {res2.status_code}")
                self.current_gpt = gpt_w
                self.current_sovits = sov_w
                time.sleep(1.2)
                logger.info(f"[TTS] 가중치 로드 완료: {os.path.basename(gpt_w)}")
                return True
            except Exception as e:
                delay = 1.0 * (2 ** attempt) * (0.5 + random.random())
                logger.warning(
                    f"[TTS] 가중치 로드 실패. 재시도 {attempt+1}/3, "
                    f"{delay:.1f}초 대기. 에러: {e}"
                )
                if attempt < 2:
                    time.sleep(delay)

        logger.error(f"[TTS] 가중치 로드 최종 실패: {gpt_w}")
        return False

    # ============================================================
    # 2. Server Management
    # ============================================================

    def _load_supertonic_settings(self) -> Dict[str, Any]:
        """Load optional Supertonic settings from app config without hard dependency."""
        try:
            from config.settings import config as app_config
        except Exception:
            app_config = None

        raw_voice_map = getattr(app_config, "SUPERTONIC_VOICE_MAP", "") if app_config else ""
        voice_map: Dict[str, str] = {}
        if isinstance(raw_voice_map, dict):
            voice_map = {str(k).strip().lower(): str(v).strip().upper() for k, v in raw_voice_map.items()}
        elif isinstance(raw_voice_map, str):
            for item in raw_voice_map.split(","):
                if "=" not in item:
                    continue
                key, value = item.split("=", 1)
                key = key.strip().lower()
                value = value.strip().upper()
                if key and value:
                    voice_map[key] = value

        def cfg(name: str, default):
            return getattr(app_config, name, default) if app_config else default

        return {
            "supertonic_auto_download": cfg("SUPERTONIC_AUTO_DOWNLOAD", True),
            "supertonic_default_voice": cfg("SUPERTONIC_DEFAULT_VOICE", "M1"),
            "supertonic_voice_map": voice_map,
            "supertonic_total_steps": cfg("SUPERTONIC_TOTAL_STEPS", 5),
            "supertonic_speed": cfg("SUPERTONIC_SPEED", 1.05),
            "supertonic_max_chunk_length": cfg("SUPERTONIC_MAX_CHUNK_LENGTH", 120),
            "supertonic_silence_duration": cfg("SUPERTONIC_SILENCE_DURATION", 0.25),
            "supertonic_intra_op_threads": cfg("SUPERTONIC_INTRA_OP_THREADS", 0),
            "supertonic_inter_op_threads": cfg("SUPERTONIC_INTER_OP_THREADS", 0),
        }

    def _engine_requires_reference_audio(self) -> bool:
        engine = getattr(self, "_tts_engine", None)
        return bool(getattr(engine, "requires_reference_audio", True))

    def _synthesize_reference_free(
        self,
        text: str,
        out_path: str,
        language: str,
        emotion: str,
        role_key: str,
        voice_type: str = None,
    ) -> bool:
        """Synthesize with engines that do not use SoVITS reference assets."""
        if not (
            self._tts_engine
            and hasattr(self._tts_engine, "is_available")
            and self._tts_engine.is_available
        ):
            return False

        character = voice_type or role_key or "narrator"
        return self._tts_engine.synthesize(
            text=text,
            ref_audio="",
            ref_text="",
            output_path=out_path,
            language=language,
            emotion=emotion,
            character=character,
            voice_type=voice_type,
            role=role_key,
        )

    def _ensure_sovits_fallback_ready(self) -> bool:
        """Prepare SoVITS components only when a reference-free engine fails."""
        if self._audio_synthesizer is not None and self._tts_server_manager is not None:
            return True
        try:
            from modules_pro.audio_synthesizer import AudioSynthesizer
            from modules_pro.tts_server_manager import TTSServerManager

            self._audio_synthesizer = AudioSynthesizer(
                channel=self.channel, sovits_url=self.sovits_url
            )
            self._tts_server_manager = TTSServerManager(
                sovits_url=self.sovits_url, sovits_root=self.sovits_root
            )
            if not getattr(self, "voice_metadata", None):
                self.voice_metadata = self.load_voice_metadata()
            return True
        except Exception as exc:
            logger.error("[TTS] SoVITS fallback 준비 실패: %s", exc)
            return False

    def _fallback_reference_free_to_sovits(
        self,
        role_key: str,
        emotion: str,
        text: str,
        out_wav: str,
        line_idx: int,
        voice_type: str = None,
    ) -> bool:
        """Try legacy SoVITS when Supertonic/Qwen-style reference-free synthesis fails."""
        logger.warning("[TTS:%s] reference-free TTS 실패, SoVITS fallback 시도", line_idx)
        if not self._ensure_sovits_fallback_ready():
            return False
        try:
            self.ensure_sovits_engine()
            return self.synthesize_with_sovits(
                role_key, emotion, text, out_wav, line_idx, voice_type
            )
        except Exception as exc:
            logger.error("[TTS:%s] SoVITS fallback 실패: %s", line_idx, exc)
            return False

    def _init_tts_engine(self, engine_type_str: str = "sovits"):
        """TTS 엔진 초기화"""
        try:
            from modules_pro.tts_engine import (
                TTSConfig, TTSEngineType, TTSEngineFactory,
            )

            qwen3_model = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
            qwen3_device = "cuda"

            tts_config = TTSConfig(
                engine_type=TTSEngineType(engine_type_str),
                language=self.target_language,
                fallback_enabled=True,
                sovits_url=self.sovits_url,
                sovits_root=self.sovits_root,
                qwen3_model=qwen3_model,
                qwen3_device=qwen3_device,
                **self._load_supertonic_settings(),
            )

            engine = TTSEngineFactory.get_with_fallback(tts_config)
            logger.info(f"[TTSManager] TTS 엔진 초기화 완료: {engine.engine_name}")
            return engine
        except Exception as e:
            logger.warning(f"[TTSManager] TTS 엔진 초기화 실패, 레거시 모드: {e}")
            try:
                from modules_pro.tts_engine import TTSConfig, TTSEngineType
                from modules_pro.tts_sovits_adapter import GPTSoVITSAdapter

                return GPTSoVITSAdapter(
                    TTSConfig(
                        engine_type=TTSEngineType.SOVITS,
                        sovits_url=self.sovits_url,
                        sovits_root=self.sovits_root,
                    )
                )
            except Exception:
                return None

    def check_tts_server(self) -> bool:
        """TTS 서버 상태 확인"""
        if self._tts_server_manager is None:
            return True
        return self._tts_server_manager.check_connection()

    def restart_tts_server(self, force: bool = False) -> bool:
        """TTS 서버 재시작"""
        if self._tts_server_manager is None:
            return True
        result = self._tts_server_manager.restart_server(force)
        if result:
            self.current_gpt = None
        return result

    def ensure_sovits_engine(self):
        """SoVITS 엔진 준비 (lazy loading)"""
        if self._sovits_engine is None:
            logger.info("[Hybrid TTS] SoVITS 엔진 초기화...")
            try:
                from modules_pro.tts_engine import TTSConfig, TTSEngineType
                from modules_pro.tts_sovits_adapter import GPTSoVITSAdapter

                self._sovits_engine = GPTSoVITSAdapter(
                    TTSConfig(
                        engine_type=TTSEngineType.SOVITS,
                        sovits_url=self.sovits_url,
                        sovits_root=self.sovits_root,
                    )
                )
            except Exception as e:
                logger.error(f"[TTSManager] SoVITS 엔진 생성 실패: {e}")
                return None
            if self._tts_server_manager:
                self._tts_server_manager.boot_engine()
        return self._sovits_engine

    def ensure_qwen3_engine(self):
        """v57.3.0: Qwen3 비활성화"""
        logger.warning("[TTSManager] Qwen3 엔진 비활성화됨 (v57.3.0)")
        return None

    def release_tts_resources(self):
        """TTS 리소스 해제 및 VRAM 정리"""
        if self._sovits_engine is not None:
            try:
                self._sovits_engine.cleanup()
                logger.info("[Hybrid TTS] SoVITS 엔진 정리 완료")
            except Exception as e:
                logger.warning(f"[Hybrid TTS] SoVITS 정리 실패: {e}")
            self._sovits_engine = None

        if self._qwen3_engine is not None:
            try:
                self._qwen3_engine.cleanup()
                logger.info("[Hybrid TTS] Qwen3 엔진 정리 완료")
            except Exception as e:
                logger.warning(f"[Hybrid TTS] Qwen3 정리 실패: {e}")
            self._qwen3_engine = None

        # VRAM 캐시 정리
        if self._release_vram_fn:
            self._release_vram_fn()

    # ============================================================
    # 3. TTS Synthesis
    # ============================================================

    def tts_post_request(
        self, send_text: str, ref_audio: str, ref_text: str,
        text_language: str = "ko",
    ) -> Optional[bytes]:
        """TTS API 호출 (지수 백오프, GET/POST 지원)"""
        import urllib.parse
        import requests

        if not self.check_tts_server():
            logger.warning("[TTS] 서버 연결 안됨, 재시작 시도...")
            if not self.restart_tts_server():
                logger.error("[TTS] 서버 사용 불가")
                return None

        normalize_path = self._normalize_path_fn or (lambda x: x)
        ref_audio_path = normalize_path(ref_audio)

        post_candidates = [
            ("/tts", {
                "text": send_text, "text_lang": text_language,
                "ref_audio_path": ref_audio_path, "prompt_text": ref_text,
                "prompt_lang": text_language,
            }),
            ("/tts", {
                "text": send_text, "ref_audio": ref_audio_path,
                "prompt_text": ref_text,
            }),
            ("/infer", {
                "text": send_text, "text_lang": text_language,
                "ref_audio_path": ref_audio_path, "prompt_text": ref_text,
                "prompt_lang": text_language,
            }),
            ("/", {
                "text": send_text, "text_language": text_language,
                "refer_wav_path": ref_audio_path, "prompt_text": ref_text,
                "prompt_language": text_language,
            }),
        ]

        get_params = {
            "text": send_text, "text_lang": text_language,
            "ref_audio_path": ref_audio_path, "prompt_text": ref_text,
            "prompt_lang": text_language,
        }

        last_error = None
        last_response = None
        for attempt in range(3):
            if self.cancellation_token and self.cancellation_token.check():
                raise InterruptedError("작업이 취소되었습니다.")

            for endpoint, payload in post_candidates:
                try:
                    url = f"{self.sovits_url}{endpoint}"
                    res = requests.post(url, json=payload, timeout=60)
                    # v61.1-fix(#24): WAV 헤더 검증 (RIFF + 최소 크기)
                    if (res.status_code == 200
                            and len(res.content) > 1000
                            and res.content[:4] == b'RIFF'):
                        return res.content
                    else:
                        last_response = (
                            f"{res.status_code}: "
                            f"{res.text[:200] if res.text else 'empty'}"
                        )
                except requests.exceptions.ConnectionError as e:
                    last_error = f"연결 실패 ({self.sovits_url}): {e}"
                except Exception as e:
                    last_error = str(e)
                    continue

            try:
                query_string = urllib.parse.urlencode(get_params)
                url = f"{self.sovits_url}/tts?{query_string}"
                res = requests.get(url, timeout=60)
                # v61.1-fix(#24 검증): GET 폴백도 RIFF 헤더 검증
                if (res.status_code == 200
                        and len(res.content) > 1000
                        and res.content[:4] == b'RIFF'):
                    return res.content
            except Exception as e:
                logger.debug(f"[TTS] GET 폴백 요청 실패 (무시): {e}")

            if attempt < 2:
                if last_response and (
                    "Errno 22" in last_response
                    or "Invalid argument" in last_response
                ):
                    if attempt == 1:
                        self.restart_tts_server()
                        self.current_gpt = None
                delay = 1.0 * (2 ** attempt) * (0.5 + random.random())
                logger.warning(
                    f"[TTS] API 호출 실패. 재시도 {attempt+1}/3, "
                    f"{delay:.1f}초 대기"
                )
                time.sleep(delay)

        error_detail = last_error or last_response or "알 수 없는 오류"
        text_preview = (
            send_text[:80] + "..." if len(send_text) > 80 else send_text
        )
        logger.error(
            f"[TTS] API 호출 최종 실패: {error_detail} | text: {text_preview}"
        )
        return None

    def synthesize_with_sovits(
        self, role_key: str, emotion: str, text: str,
        out_wav: str, line_idx: int, voice_type: str,
    ) -> bool:
        """
        GPT-SoVITS로 단일 라인 음성 합성

        Args:
            role_key: 역할 키 (narrator, grandpa 등)
            emotion: 감정 키워드 (calm, scared, sad 등)
            text: 합성할 텍스트
            out_wav: 출력 WAV 파일 경로
            line_idx: 대본 라인 인덱스 (로그용)
            voice_type: 음성 타입 (narrator, character 등)

        Returns:
            합성 성공 여부
        """
        try:
            if voice_type in ("narrator", "나레이션", "narration"):
                emotion = "calm"

            gpt_w, sov_w, ref_audio, ref_text = self.resolve_tts_assets(
                role_key, emotion, voice_type
            )
            if not ref_audio or not os.path.exists(ref_audio):
                gpt_w, sov_w, ref_audio, ref_text = self.resolve_tts_assets(
                    role_key, "calm", voice_type
                )
            if not ref_audio or not os.path.exists(ref_audio):
                logger.warning(f"[SoVITS:{line_idx}] 참조 오디오 없음")
                return False

            # v62.21 H-6: 가중치 로드 실패 시 진행 차단
            if not self.ensure_weights_loaded(gpt_w, sov_w):
                logger.warning(f"[SoVITS:{line_idx}] 가중치 로드 실패 → 생성 스킵")
                return False
            engine = self.ensure_sovits_engine()
            engine.load_voice({"gpt_weight": gpt_w, "sovits_weight": sov_w})
            success = engine.synthesize(
                text=text, ref_audio=ref_audio, ref_text=ref_text,
                output_path=out_wav, language=self.target_language,
            )
            if success:
                logger.debug(f"[SoVITS:{line_idx}] 합성 성공: {out_wav}")
                # v62.10: loudnorm 누락 수정 — generate_voice_and_subtitles_v33 경로에서
                # synthesize_with_sovits 호출 시 amplify 없이 raw 32kHz WAV가 그대로
                # 저장되던 버그. 치지직 노이즈 근본 원인.
                self.amplify_tts_volume(out_wav)
            return success
        except Exception as e:
            logger.error(f"[SoVITS:{line_idx}] 합성 실패: {e}")
            return False

    def synthesize_with_qwen3(
        self, role_key: str, emotion: str, text: str,
        out_wav: str, line_idx: int, voice_type: str, project_name: str,
    ) -> bool:
        """v57.3.0: Qwen3 비활성화"""
        logger.warning(f"[Qwen3:{line_idx}] Qwen3 비활성화됨 (v57.3.0)")
        return False

    def generate_single_tts(
        self, role: str, text: str, emotion: str, out_path: str,
        text_language: str = "ko", voice_type: str = None,
    ) -> bool:
        """
        단일 TTS 생성 (역할 자동 해석 + 가중치 로드 + 합성)

        Args:
            role: 역할명 (나레이션, 할아버지 등)
            text: 합성할 텍스트
            emotion: 감정 (calm, scared, sad 등)
            out_path: 출력 WAV 경로
            text_language: 언어 코드
            voice_type: 음성 타입 (지정 시 role 대신 사용)

        Returns:
            합성 성공 여부
        """
        clean_tts_text = self._clean_text_for_tts_fn or self._clean_text_fn or (lambda x: x)

        if voice_type:
            role_key = voice_type.lower()
        elif self._role_key_normalize_fn:
            role_key = self._role_key_normalize_fn(role)
        else:
            role_key = role.lower()

        emotion = (emotion or "calm").lower().strip()
        cleaned = clean_tts_text(text)

        if not self._engine_requires_reference_audio():
            success = self._synthesize_reference_free(
                cleaned, out_path, text_language, emotion, role_key, voice_type
            )
            if success:
                self.amplify_tts_volume(out_path)
                return True
            fallback_success = self._fallback_reference_free_to_sovits(
                role_key, emotion, cleaned, out_path, 0, voice_type
            )
            if fallback_success:
                self.amplify_tts_volume(out_path)
            return fallback_success

        gpt_w, sov_w, ref_audio, ref_text = self.resolve_tts_assets(
            role_key, emotion, voice_type
        )

        if not ref_audio or not os.path.exists(ref_audio):
            gpt_w2, sov_w2, ref_audio2, ref_text2 = self.resolve_tts_assets(
                role_key, "calm", voice_type
            )
            if (
                self.ensure_weights_loaded(gpt_w2, sov_w2)
                and ref_audio2
                and os.path.exists(ref_audio2)
            ):
                gpt_w, sov_w, ref_audio, ref_text = (
                    gpt_w2, sov_w2, ref_audio2, ref_text2
                )
            else:
                return False

        if (
            self._tts_engine
            and hasattr(self._tts_engine, "is_available")
            and self._tts_engine.is_available
        ):
            return self._generate_tts_with_engine(
                cleaned, ref_audio, ref_text, out_path, text_language, gpt_w, sov_w
            )
        return self._generate_tts_legacy(
            cleaned, ref_audio, ref_text, out_path, text_language, gpt_w, sov_w
        )

    def _generate_tts_with_engine(
        self, text: str, ref_audio: str, ref_text: str,
        out_path: str, language: str, gpt_w: str, sov_w: str,
    ) -> bool:
        """TTS 엔진 추상화를 통한 음성 합성"""
        try:
            self._tts_engine.load_voice(
                {"gpt_weight": gpt_w, "sovits_weight": sov_w}
            )
            success = self._tts_engine.synthesize(
                text=text, ref_audio=ref_audio, ref_text=ref_text,
                output_path=out_path, language=language,
            )
            if success:
                self.amplify_tts_volume(out_path)
            else:
                return self._generate_tts_legacy(
                    text, ref_audio, ref_text, out_path, language, gpt_w, sov_w
                )
            return success
        except Exception as e:
            logger.error(f"[TTS Engine] 예외 발생: {e}, 레거시 모드로 폴백")
            return self._generate_tts_legacy(
                text, ref_audio, ref_text, out_path, language, gpt_w, sov_w
            )

    def _generate_tts_legacy(
        self, text: str, ref_audio: str, ref_text: str,
        out_path: str, language: str, gpt_w: str, sov_w: str,
    ) -> bool:
        """레거시 TTS 생성"""
        if not self.ensure_weights_loaded(gpt_w, sov_w):
            return False

        clean_for_retry = self._clean_text_for_retry_fn or (lambda t, a: t)

        for attempt in range(3):
            try:
                if attempt > 0:
                    time.sleep(0.5)
                send_text = (
                    text if attempt == 0 else clean_for_retry(text, attempt)
                )
                wav_bytes = self.tts_post_request(
                    send_text, ref_audio, ref_text, language
                )
                if wav_bytes:
                    with open(out_path, "wb") as f:
                        f.write(wav_bytes)
                    self.amplify_tts_volume(out_path)
                    return True
            except Exception as e:
                logger.warning(f"[TTS Legacy] 시도 {attempt+1}/3 실패: {e}")
        return False

    def amplify_tts_volume(
        self, wav_path: str, target_db: float = -10.0
    ) -> bool:
        """TTS WAV 파일 볼륨 증폭 (FFmpeg loudnorm)"""
        if not os.path.exists(wav_path):
            return False
        try:
            ffmpeg = self.ffmpeg_path
            # v61.1-fix(#19): 시스템 PATH ffmpeg 4.3.2 사용 방지 — 경로 없으면 스킵
            if not ffmpeg or not os.path.exists(ffmpeg):
                logger.warning("[TTS Volume] FFmpeg 경로 미설정 — 볼륨 정규화 스킵")
                return False
            temp_path = wav_path.replace(".wav", "_amp.wav")
            cmd = [
                ffmpeg, "-y", "-i", wav_path,
                "-af", f"aresample=44100,loudnorm=I={target_db}:TP=-1:LRA=11",
                "-ar", "44100", temp_path,  # v62.8: aresample=44100 먼저 → loudnorm (GPT-SoVITS 32kHz 네이티브 근본 수정)
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                shell=False,  # v62.10: shell=True 보안/신뢰성 위험 제거 (경로에 공백 있으면 리스트 방식이 안전)
                timeout=30,
                creationflags=_NO_WINDOW,  # v62.17: 콘솔 창 숨김
                startupinfo=_hidden_startupinfo(),  # v62.17: 이중 방어 — 일부 Windows에서 creationflags만으로 부족
            )
            if result.returncode == 0 and os.path.exists(temp_path):
                os.replace(temp_path, wav_path)
                logger.info(f"[TTS Volume] loudnorm OK: {os.path.basename(wav_path)}")
                return True
            else:
                logger.warning(f"[TTS Volume] FFmpeg 실패 rc={result.returncode}: {result.stderr[-200:] if result.stderr else ''}")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return False
        except Exception as e:
            logger.warning(f"[TTS Volume] 예외: {e}")
            _safe_remove_file(temp_path, "loudnorm temp")
            return False

    # ============================================================
    # 4. Audio Generation Pipeline
    # ============================================================

    @staticmethod
    def _split_subtitle_entry(entry: Dict[str, Any], max_chars: int = 30) -> List[Dict[str, Any]]:
        """v62.9: 긴 나레이션 자막을 문장 단위로 분할 (타이밍 글자 수 비례 배분)

        TTS 오디오는 그대로 두고 자막 타임스탬프만 분할한다.
        나레이터 이외 캐릭터는 분할하지 않는다.

        Args:
            entry: subtitle_data 단일 항목 {text, role, start, end, scene_end, ...}
            max_chars: 이 글자 수 초과 시 분할 (기본 30자)

        Returns:
            분할된 항목 리스트 (분할 불필요하면 원소 1개)
        """
        role = entry.get("role", "").lower()
        text = entry.get("text", "")
        # 나레이터 전용 처리, 30자 이하는 그대로
        if role not in ("narrator", "narration") or len(text) <= max_chars:
            return [entry]

        start = float(entry.get("start", 0))
        end = float(entry.get("end", start))
        scene_end = float(entry.get("scene_end", end))
        total_dur = end - start
        trail_dur = scene_end - end  # pause 포함 구간

        # 문장 분리: 마침표/느낌표/물음표 뒤 + 공백 or 끝
        import re as _re
        sentences = _re.split(r'(?<=[.!?])\s+|(?<=。)\s*', text)
        # 재분할: 여전히 max_chars 초과인 문장은 띄어쓰기로 추가 분할
        final_parts = []
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            if len(s) <= max_chars:
                final_parts.append(s)
            else:
                # 단어 단위 분할
                words = s.split()
                chunk = ""
                for w in words:
                    if len(chunk) + len(w) + 1 > max_chars and chunk:
                        final_parts.append(chunk.strip())
                        chunk = w
                    else:
                        chunk = (chunk + " " + w).strip()
                if chunk:
                    final_parts.append(chunk)

        if len(final_parts) <= 1:
            return [entry]

        # 글자 수 비례로 타임스탬프 배분
        total_chars = sum(len(p) for p in final_parts)
        if total_chars == 0:
            return [entry]

        result = []
        cursor = start
        for idx, part in enumerate(final_parts):
            ratio = len(part) / total_chars
            part_dur = total_dur * ratio
            is_last = (idx == len(final_parts) - 1)
            part_end = cursor + part_dur
            # 마지막 파트에 trail_dur 붙임
            part_scene_end = (cursor + part_dur + trail_dur) if is_last else part_end
            new_entry = dict(entry)
            new_entry["text"] = part
            new_entry["start"] = cursor
            new_entry["end"] = part_end
            new_entry["scene_end"] = part_scene_end
            # v62.10: sfx_tag는 첫 파트에만 — 분할된 모든 파트에 동일 sfx_tag가 복사되면
            # SFX가 중복 재생됨. 첫 번째 파트에만 적용하고 나머지는 비움.
            if idx > 0:
                new_entry["sfx_tag"] = ""
            result.append(new_entry)
            cursor = part_end

        return result

    def estimate_silence_duration(self, text: str) -> float:
        """
        텍스트 길이 기반 무음 시간 추정

        v60.1.0: _legacy/video_assembler.py에서 인라인 이동.
        v61.1-fix(#20): 글자당 0.06→0.15초 (한국어 TTS 실측 기준 ~0.12-0.18초/char)
        최소 0.7초 ~ 최대 6.0초.

        Args:
            text: 대사 텍스트

        Returns:
            추정 무음 시간 (초)
        """
        n = len((text or "").strip())
        if n <= 0:
            return 0.7
        dur = 0.15 * n
        return float(max(0.7, min(dur, 6.0)))

    def tts_line_to_clip(
        self, role_key: str, emotion: str, text: str,
        out_wav: str, line_idx: int,
        text_language: str = "ko", voice_type: str = None,
    ):
        """TTS 한 줄 합성 → AudioFileClip 반환"""
        # v60.1.0: 모듈 최상단에서 import (MOVIEPY_AVAILABLE 체크)
        if not MOVIEPY_AVAILABLE:
            raise ImportError("moviepy 미설치. pip install moviepy 실행 필요.")

        clean_tts_text = self._clean_text_for_tts_fn or self._clean_text_fn or (lambda x: x)
        role_lower = role_key.lower()
        # v61.1-fix(#21): 나레이터 감정 오버라이드 — 6개 alias 전부 포함
        if role_lower in ("narrator", "나레이션", "narration", "해설", "내레이터", "내레이션"):
            emotion = "calm"
        cleaned = clean_tts_text(text)

        if not self._engine_requires_reference_audio():
            try:
                success = self._synthesize_reference_free(
                    cleaned, out_wav, text_language, emotion, role_key, voice_type
                )
                if success and os.path.exists(out_wav):
                    self.amplify_tts_volume(out_wav)
                    return AudioFileClip(out_wav)
            except Exception as e:
                logger.error(f"[TTS:{line_idx}] reference-free TTS 예외: {e}")
            fallback_success = self._fallback_reference_free_to_sovits(
                role_key, emotion, cleaned, out_wav, line_idx, voice_type
            )
            if fallback_success and os.path.exists(out_wav):
                self.amplify_tts_volume(out_wav)
                return AudioFileClip(out_wav)
            return None

        gpt_w, sov_w, ref_audio, ref_text = self.resolve_tts_assets(
            role_key, emotion, voice_type
        )

        if not ref_audio or not os.path.exists(ref_audio):
            gpt_w2, sov_w2, ref_audio2, ref_text2 = self.resolve_tts_assets(
                role_key, "calm", voice_type
            )
            if self._using_sovits:
                if (
                    self.ensure_weights_loaded(gpt_w2, sov_w2)
                    and ref_audio2
                    and os.path.exists(ref_audio2)
                ):
                    gpt_w, sov_w, ref_audio, ref_text = (
                        gpt_w2, sov_w2, ref_audio2, ref_text2
                    )
                else:
                    return None
            elif ref_audio2 and os.path.exists(ref_audio2):
                gpt_w, sov_w, ref_audio, ref_text = (
                    gpt_w2, sov_w2, ref_audio2, ref_text2
                )
            else:
                return None

        if (
            self._tts_engine
            and hasattr(self._tts_engine, "is_available")
            and self._tts_engine.is_available
        ):
            try:
                if self._using_sovits:
                    self._tts_engine.load_voice(
                        {"gpt_weight": gpt_w, "sovits_weight": sov_w}
                    )

                if (
                    hasattr(self._tts_engine, "synthesize_consistent")
                    and not self._using_sovits
                ):
                    char_id = f"{self.channel}_{role_key}"
                    success = self._tts_engine.synthesize_consistent(
                        text=cleaned, character_id=char_id,
                        output_path=out_wav, emotion=emotion,
                        language=text_language,
                    )
                else:
                    character = voice_type if voice_type else "narrator"
                    success = self._tts_engine.synthesize(
                        text=cleaned, ref_audio=ref_audio,
                        ref_text=ref_text, output_path=out_wav,
                        language=text_language, emotion=emotion,
                        character=character,
                    )

                if success and os.path.exists(out_wav):
                    # v61.1-fix: 프로덕션 경로에서도 볼륨 정규화 적용
                    self.amplify_tts_volume(out_wav)
                    return AudioFileClip(out_wav)
                else:
                    if self._using_sovits:
                        return self._tts_line_to_clip_legacy(
                            role_key, emotion, cleaned, out_wav,
                            line_idx, text_language, gpt_w, sov_w,
                            ref_audio, ref_text,
                        )
                    return None
            except Exception as e:
                logger.error(f"[TTS:{line_idx}] TTS 엔진 예외: {e}")
                if self._using_sovits:
                    return self._tts_line_to_clip_legacy(
                        role_key, emotion, cleaned, out_wav,
                        line_idx, text_language, gpt_w, sov_w,
                        ref_audio, ref_text,
                    )
                return None

        return self._tts_line_to_clip_legacy(
            role_key, emotion, cleaned, out_wav,
            line_idx, text_language, gpt_w, sov_w,
            ref_audio, ref_text,
        )

    def _tts_line_to_clip_legacy(
        self, role_key, emotion, cleaned, out_wav,
        line_idx, text_language, gpt_w, sov_w,
        ref_audio, ref_text,
    ):
        """레거시 TTS 합성 (GPT-SoVITS 직접 호출)"""
        # v60.1.0: 모듈 최상단에서 import (MOVIEPY_AVAILABLE 체크)
        if not MOVIEPY_AVAILABLE:
            raise ImportError("moviepy 미설치. pip install moviepy 실행 필요.")

        if not self.ensure_weights_loaded(gpt_w, sov_w):
            return None

        clean_for_retry = self._clean_text_for_retry_fn or (lambda t, a: t)

        for attempt in range(3):
            try:
                if attempt > 0:
                    time.sleep(0.5)
                send_text = (
                    cleaned if attempt == 0
                    else clean_for_retry(cleaned, attempt)
                )
                wav_bytes = self.tts_post_request(
                    send_text, ref_audio, ref_text, text_language
                )
                if wav_bytes:
                    with open(out_wav, "wb") as f:
                        f.write(wav_bytes)
                    # v61.1-fix: 레거시 경로에서도 볼륨 정규화 적용
                    self.amplify_tts_volume(out_wav)
                    return AudioFileClip(out_wav)
            except Exception as e:
                logger.warning(
                    f"[TTS:{line_idx}] 레거시 시도 {attempt+1}/3 실패: {e}"
                )
        # v62.19: TTS 3회 시도 전부 실패 시 최종 error 로그 (디버깅용)
        text_preview = cleaned[:60] + "..." if len(cleaned) > 60 else cleaned
        logger.error(f"[TTS:{line_idx}] 레거시 3회 전부 실패 — text: {text_preview}")
        return None

    def generate_voice_and_subtitles_v33(
        self,
        script_list: List[Dict],
        project_name: str,
        progress_callback: Optional[Callable] = None,
        sanitize_fn: Callable = None,
    ) -> Tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
        """v57.2: 하이브리드 TTS 오케스트레이터"""
        from pipeline.pipeline_utils import safe_print
        # v60.1.0: 모듈 최상단에서 import (MOVIEPY_AVAILABLE 체크)
        if not MOVIEPY_AVAILABLE:
            raise ImportError("moviepy 미설치. pip install moviepy 실행 필요.")

        if not self._hybrid_tts_enabled:
            return self.generate_voice_and_subtitles_sequential(
                script_list, project_name, progress_callback, sanitize_fn
            )

        clean_text = self._clean_text_fn or (lambda x: x)
        clean_tts_text = self._clean_text_for_tts_fn or clean_text
        split_sentences = self._split_into_sentences_fn or (lambda x: [x])
        sanitize = sanitize_fn or (lambda x: x)

        safe_project_name = sanitize(project_name)
        temp_dir = os.path.join(self.data_dir, "temp_audio", safe_project_name)
        os.makedirs(temp_dir, exist_ok=True)

        # Phase 0: 역할별 분류
        sovits_tasks = []
        qwen3_tasks = []
        for i, item in enumerate(script_list):
            vt = item.get("voice_type", "narrator").lower()
            rk = item.get("role", "나레이션").lower()
            if vt in self._sovits_roles or rk in self._sovits_roles:
                sovits_tasks.append((i, item))
            else:
                qwen3_tasks.append((i, item))

        sovits_count = len(sovits_tasks)
        qwen3_count = len(qwen3_tasks)
        logger.info(
            f"[Hybrid TTS] 분류 완료: SoVITS {sovits_count}문장, "
            f"Qwen3 {qwen3_count}문장"
        )
        safe_print(
            f"   📊 SoVITS: {sovits_count}문장 (빠름) | "
            f"Qwen3: {qwen3_count}문장 (감정)"
        )

        wav_results: Dict[int, str] = {}
        tts_success = 0
        tts_failed = 0
        failed_indices: List[int] = []

        # Phase 1: SoVITS 일괄 처리
        if sovits_tasks:
            safe_print(
                f"\n   🎤 [Phase 1] SoVITS 처리 시작 ({sovits_count}문장)..."
            )
            self.ensure_sovits_engine()

            for idx, (orig_idx, item) in enumerate(sovits_tasks):
                if self.cancellation_token and self.cancellation_token.check():
                    raise InterruptedError("작업이 취소되었습니다.")

                caption_text = clean_text(item.get("text", ""))
                speech_text = clean_tts_text(item.get("text", ""))
                if not caption_text:
                    continue

                out_wav = os.path.join(temp_dir, f"s_{orig_idx:03d}.wav")
                role_key = item.get("role", "나레이션")
                emotion = (item.get("emotion", "calm") or "calm").lower().strip()
                voice_type = item.get("voice_type", "narrator").lower()

                success = self.synthesize_with_sovits(
                    role_key, emotion, speech_text, out_wav, orig_idx, voice_type
                )
                if success and os.path.exists(out_wav):
                    wav_results[orig_idx] = out_wav
                    tts_success += 1
                else:
                    tts_failed += 1
                    failed_indices.append(orig_idx + 1)

                if progress_callback and idx % 5 == 0:
                    pct = (
                        25 + int((idx / sovits_count) * 10)
                        if sovits_count > 0 else 25
                    )
                    progress_callback(
                        f"SoVITS 처리 중... ({idx+1}/{sovits_count})", pct
                    )
                safe_print(
                    f"   ▶ [SoVITS {idx+1}/{sovits_count}] "
                    f"{role_key} 완료",
                    end="\r",
                )
            safe_print("")

        # Phase 2-3: Qwen3 (현재 비활성화)
        if qwen3_tasks:
            safe_print(f"\n   🔄 [Phase 2] VRAM 정리 및 Qwen3 로드...")
            self.release_tts_resources()

            safe_print(
                f"\n   🎭 [Phase 3] Qwen3 처리 시작 ({qwen3_count}문장)..."
            )
            self.ensure_qwen3_engine()

            if self._register_characters_fn:
                self._register_characters_fn(script_list, project_name)

            for idx, (orig_idx, item) in enumerate(qwen3_tasks):
                if self.cancellation_token and self.cancellation_token.check():
                    raise InterruptedError("작업이 취소되었습니다.")

                caption_text = clean_text(item.get("text", ""))
                speech_text = clean_tts_text(item.get("text", ""))
                if not caption_text:
                    continue

                out_wav = os.path.join(temp_dir, f"s_{orig_idx:03d}.wav")
                role_key = item.get("role", "나레이션")
                emotion = (item.get("emotion", "calm") or "calm").lower().strip()
                voice_type = item.get("voice_type", "narrator").lower()

                success = self.synthesize_with_qwen3(
                    role_key, emotion, speech_text, out_wav, orig_idx,
                    voice_type, project_name,
                )
                if success and os.path.exists(out_wav):
                    wav_results[orig_idx] = out_wav
                    tts_success += 1
                else:
                    tts_failed += 1
                    failed_indices.append(orig_idx + 1)

            safe_print("")
            self.release_tts_resources()

        # Phase 4: 오디오 파일 조립
        safe_print(f"\n   🎬 [Phase 4] 오디오 조립 중...")
        audio_clips: List = []
        subtitle_data: List[Dict[str, Any]] = []
        current_time = 0.0

        for i, item in enumerate(script_list):
            if self._test_mode and current_time >= self._test_duration:
                break

            caption_text = clean_text(item.get("text", ""))
            speech_text = clean_tts_text(item.get("text", ""))
            if not caption_text:
                continue

            out_wav = os.path.join(temp_dir, f"s_{i:03d}.wav")

            if i in wav_results and os.path.exists(out_wav):
                clip = AudioFileClip(out_wav)
            else:
                dur = self.estimate_silence_duration(speech_text)
                clip = AudioClip(lambda t: [0], duration=dur)

            turn_dur = float(getattr(clip, "duration", 0.0) or 0.0)
            if turn_dur <= 0:
                turn_dur = self.estimate_silence_duration(speech_text)

            voice_type = item.get("voice_type", "narrator").lower()
            role_key = item.get("role", "나레이션")
            # v61.1-fix(#22): 감정 기반 pause
            emo_h = (item.get("emotion") or "calm").lower().strip()
            if emo_h in ("scared", "desperate", "angry"):
                pause_dur = random.uniform(0.2, 0.4)
            elif emo_h in ("sad", "worried"):
                pause_dur = random.uniform(0.5, 0.8)
            else:
                pause_dur = random.uniform(0.3, 0.6)

            sentences = split_sentences(caption_text)
            if len(sentences) > 1 and turn_dur > 0:
                total_chars = sum(len(s) for s in sentences)
                sent_start = current_time
                for idx_sent, sent in enumerate(sentences):
                    if not sent.strip():
                        continue
                    sent_ratio = (
                        len(sent) / total_chars
                        if total_chars > 0
                        else 1.0 / len(sentences)
                    )
                    sent_dur = turn_dur * sent_ratio
                    is_last = idx_sent == len(sentences) - 1
                    subtitle_data.append({
                        "text": sent.strip(),
                        "role": role_key,
                        "voice_type": voice_type,
                        "emotion": emo_h,  # v62.21: sfx_integrator 감정 매칭용
                        "sfx_tag": item.get("sfx_tag", "") if idx_sent == 0 else "",  # v62.21: 첫 문장만 SFX
                        "start": sent_start,
                        "end": sent_start + sent_dur,
                        "scene_end": sent_start + sent_dur + (
                            pause_dur if is_last else 0
                        ),
                    })
                    sent_start += sent_dur
            else:
                subtitle_data.append({
                    "text": caption_text,
                    "role": role_key,
                    "voice_type": voice_type,
                    "emotion": emo_h,  # v62.21: sfx_integrator 감정 매칭용
                    "sfx_tag": item.get("sfx_tag", ""),  # v62.21: 작가 SFX 태그 전달
                    "start": current_time,
                    "end": current_time + turn_dur,
                    "scene_end": current_time + turn_dur + pause_dur,
                })

            audio_clips.append(clip)
            current_time += turn_dur
            pause = AudioClip(lambda t: [0], duration=pause_dur)
            audio_clips.append(pause)
            current_time += pause_dur

        # TTS 결과 요약
        safe_print("")
        if tts_failed > 0:
            failed_str = ", ".join(map(str, failed_indices[:10]))
            if len(failed_indices) > 10:
                failed_str += f" 외 {len(failed_indices) - 10}개"
            safe_print(
                f"   [WARN] 하이브리드 TTS 결과: 성공 {tts_success}개, "
                f"실패 {tts_failed}개"
            )
        else:
            safe_print(
                f"   [OK] 하이브리드 TTS 결과: 전체 {tts_success}개 성공"
            )

        if not audio_clips:
            return None, None

        # v61.1-fix(#18): 하이브리드 TTS 실패 임계값 — 50% 이상 실패 시 중단
        total_attempted_h = tts_success + tts_failed
        if total_attempted_h > 0 and tts_failed > total_attempted_h * 0.5:
            fail_pct = round(tts_failed / total_attempted_h * 100)
            logger.error(f"[TTS Hybrid] 실패율 {fail_pct}% ({tts_failed}/{total_attempted_h}) — 임계값 초과, 중단")
            safe_print(f"🚨 TTS 실패율 {fail_pct}% — 음성 품질 보장 불가, 중단합니다.")
            # v62.21 M-8: early return 전 AudioFileClip 해제
            for _clip in audio_clips:
                _safe_close_resource(_clip, "audio clip")
            return None, None

        final_audio = concatenate_audioclips(audio_clips)
        audio_path = os.path.join(temp_dir, "full.wav")
        try:
            final_audio.write_audiofile(audio_path, fps=44100, logger=None)  # v62.10: 48000→44100 (GPT-SoVITS 44.1kHz 기준 통일)
        finally:
            # v62.21 H-7: final_audio 핸들 해제 (파일 핸들 누수 방지)
            _safe_close_resource(final_audio, "final audio")

        for clip in audio_clips:
            try:
                clip.close()
            except Exception as e:
                logger.debug(f"[TTS] 오디오 클립 close 실패 (무시): {e}")
        gc.collect()

        return audio_path, subtitle_data

    def generate_voice_and_subtitles_sequential(
        self,
        script_list: List[Dict],
        project_name: str,
        progress_callback: Optional[Callable] = None,
        sanitize_fn: Callable = None,
    ) -> Tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
        """순차 TTS 처리"""
        from pipeline.pipeline_utils import safe_print
        # v60.1.0: 모듈 최상단에서 import (MOVIEPY_AVAILABLE 체크)
        if not MOVIEPY_AVAILABLE:
            raise ImportError("moviepy 미설치. pip install moviepy 실행 필요.")

        clean_text = self._clean_text_fn or (lambda x: x)
        clean_tts_text = self._clean_text_for_tts_fn or clean_text
        sanitize = sanitize_fn or (lambda x: x)

        safe_project_name = sanitize(project_name)
        temp_dir = os.path.join(self.data_dir, "temp_audio", safe_project_name)
        os.makedirs(temp_dir, exist_ok=True)

        if self._register_characters_fn:
            self._register_characters_fn(script_list, project_name)

        audio_clips: List = []
        subtitle_data: List[Dict[str, Any]] = []
        current_time = 0.0
        tts_success = 0
        tts_failed = 0

        total = len(script_list)
        for i, item in enumerate(script_list):
            if self.cancellation_token and self.cancellation_token.check():
                raise InterruptedError("작업이 취소되었습니다.")
            if self._test_mode and current_time >= self._test_duration:
                break

            role_key = item.get("role", "나레이션")
            voice_type = item.get("voice_type", "narrator").lower()
            emotion = (item.get("emotion", "calm") or "calm").lower().strip()
            text = clean_text(item.get("text", ""))
            speech_text = clean_tts_text(item.get("text", ""))
            if not text:
                continue

            out_wav = os.path.join(temp_dir, f"s_{i:03d}.wav")
            clip = self.tts_line_to_clip(
                role_key, emotion, speech_text, out_wav, i, voice_type=voice_type
            )

            if clip is None:
                tts_failed += 1
                dur = self.estimate_silence_duration(speech_text)
                clip = AudioClip(lambda t: [0], duration=dur)
            else:
                tts_success += 1

            turn_dur = float(getattr(clip, "duration", 0.0) or 0.0)
            if turn_dur <= 0:
                turn_dur = self.estimate_silence_duration(speech_text)

            # v61.1-fix(#22): 감정 기반 pause
            emo_s = (item.get("emotion") or "calm").lower().strip()
            if emo_s in ("scared", "desperate", "angry"):
                pause_dur = random.uniform(0.2, 0.4)
            elif emo_s in ("sad", "worried"):
                pause_dur = random.uniform(0.5, 0.8)
            else:
                pause_dur = random.uniform(0.3, 0.6)

            # v62.9: 긴 나레이션 자막 분할 (30자 초과 시)
            raw_entry = {
                "text": text,
                "role": role_key,
                "voice_type": voice_type,
                "emotion": emo_s,  # v62.21: sfx_integrator 감정 매칭용
                "sfx_tag": item.get("sfx_tag", ""),  # v62.21: 작가 SFX 태그 전달
                "start": current_time,
                "end": current_time + turn_dur,
                "scene_end": current_time + turn_dur + pause_dur,
            }
            for split_entry in self._split_subtitle_entry(raw_entry):
                subtitle_data.append(split_entry)

            audio_clips.append(clip)
            current_time += turn_dur

            pause = AudioClip(lambda t: [0], duration=pause_dur)
            audio_clips.append(pause)
            current_time += pause_dur

            safe_print(
                f"   ▶ [{i+1}/{total}] {role_key} 합성 완료", end="\r"
            )

        if not audio_clips:
            return None, None

        # v60.1.0: TTS 실패 임계값 — 50% 이상 실패 시 중단 (무음 영상 방지)
        total_attempted = tts_success + tts_failed
        if total_attempted > 0 and tts_failed > total_attempted * 0.5:
            fail_pct = round(tts_failed / total_attempted * 100)
            logger.error(f"[TTS] 실패율 {fail_pct}% ({tts_failed}/{total_attempted}) — 임계값 초과, 제작 중단")
            safe_print(f"🚨 TTS 실패율 {fail_pct}% — 음성 품질 보장 불가, 중단합니다.")
            # v62.21 M-8: early return 전 AudioFileClip 해제
            for _clip in audio_clips:
                _safe_close_resource(_clip, "audio clip")
            return None, None

        final_audio = concatenate_audioclips(audio_clips)
        audio_path = os.path.join(temp_dir, "full.wav")
        try:
            final_audio.write_audiofile(audio_path, fps=44100, logger=None)  # v62.10: 48000→44100
        finally:
            # v62.21 H-7: final_audio 핸들 해제
            _safe_close_resource(final_audio, "final audio")

        # v61.1-fix(#23): 오디오 클립 핸들 해제
        for clip in audio_clips:
            _safe_close_resource(clip, "audio clip")

        return audio_path, subtitle_data

    def generate_voice_and_subtitles(
        self,
        script_list: List[Dict],
        project_name: str,
        sanitize_fn: Callable = None,
    ):
        """TTS + 자막 생성 (엔트리 포인트)"""
        from pipeline.pipeline_utils import safe_print
        # v60.1.0: 모듈 최상단에서 import (MOVIEPY_AVAILABLE 체크)
        if not MOVIEPY_AVAILABLE:
            raise ImportError("moviepy 미설치. pip install moviepy 실행 필요.")

        clean_text = self._clean_text_fn or (lambda x: x)
        clean_tts_text = self._clean_text_for_tts_fn or clean_text
        sanitize = sanitize_fn or (lambda x: x)

        safe_project_name = sanitize(project_name)
        temp_dir = os.path.join(self.data_dir, "temp_audio", safe_project_name)
        os.makedirs(temp_dir, exist_ok=True)

        if self._register_characters_fn:
            self._register_characters_fn(script_list, project_name)

        audio_clips: List = []
        subtitle_data: List[Dict[str, Any]] = []
        current_time = 0.0
        # v61.1-fix(#18): base 경로에도 TTS 실패 카운터 추가
        tts_success_b = 0
        tts_failed_b = 0

        for i, item in enumerate(script_list):
            if self._test_mode and current_time >= self._test_duration:
                break

            role_key = item.get("role", "나레이션")
            voice_type = item.get("voice_type", "narrator").lower()
            emotion = (item.get("emotion", "calm") or "calm").lower().strip()
            text = clean_text(item.get("text", ""))
            speech_text = clean_tts_text(item.get("text", ""))
            if not text:
                continue

            out_wav = os.path.join(temp_dir, f"s_{i:03d}.wav")
            clip = self.tts_line_to_clip(
                role_key, emotion, speech_text, out_wav, i, voice_type=voice_type
            )

            if clip is None:
                dur = self.estimate_silence_duration(speech_text)
                clip = AudioClip(lambda t: [0], duration=dur)
                tts_failed_b += 1
            else:
                tts_success_b += 1

            turn_dur = float(getattr(clip, "duration", 0.0) or 0.0)
            if turn_dur <= 0:
                turn_dur = self.estimate_silence_duration(speech_text)

            # v61.1-fix(#22): 감정 기반 pause (랜덤 0.3~0.8 → 감정별 차등)
            emo = (item.get("emotion") or "calm").lower().strip()
            if emo in ("scared", "desperate", "angry"):
                pause_dur = random.uniform(0.2, 0.4)  # 긴장: 짧은 간격
            elif emo in ("sad", "worried"):
                pause_dur = random.uniform(0.5, 0.8)  # 감정: 긴 간격
            else:
                pause_dur = random.uniform(0.3, 0.6)  # 기본

            # v62.9: 긴 나레이션 자막 분할 (30자 초과 시)
            raw_entry = {
                "text": text,
                "role": role_key,
                "voice_type": voice_type,
                "emotion": emo,  # v62.21: sfx_integrator 감정 매칭용
                "sfx_tag": item.get("sfx_tag", ""),  # v62.21: 작가 SFX 태그 전달
                "start": current_time,
                "end": current_time + turn_dur,
                "scene_end": current_time + turn_dur + pause_dur,
            }
            for split_entry in self._split_subtitle_entry(raw_entry):
                subtitle_data.append(split_entry)

            audio_clips.append(clip)
            current_time += turn_dur

            pause = AudioClip(lambda t: [0], duration=pause_dur)
            audio_clips.append(pause)
            current_time += pause_dur

            safe_print(
                f"   ▶ [{i+1}/{len(script_list)}] {role_key} 합성 완료",
                end="\r",
            )

        if not audio_clips:
            return None, None

        # v61.1-fix(#18): base 경로 TTS 실패 임계값 — 50% 이상 실패 시 중단
        total_attempted_b = tts_success_b + tts_failed_b
        if total_attempted_b > 0 and tts_failed_b > total_attempted_b * 0.5:
            fail_pct = round(tts_failed_b / total_attempted_b * 100)
            logger.error(f"[TTS Base] 실패율 {fail_pct}% ({tts_failed_b}/{total_attempted_b}) — 임계값 초과, 중단")
            safe_print(f"🚨 TTS 실패율 {fail_pct}% — 음성 품질 보장 불가, 중단합니다.")
            # v62.21 M-8: early return 전 AudioFileClip 해제
            for _clip in audio_clips:
                _safe_close_resource(_clip, "audio clip")
            return None, None

        final_audio = concatenate_audioclips(audio_clips)
        audio_path = os.path.join(temp_dir, "full.wav")
        try:
            final_audio.write_audiofile(audio_path, fps=44100, logger=None)  # v62.10: 48000→44100
        finally:
            # v62.21 H-7: final_audio 핸들 해제
            _safe_close_resource(final_audio, "final audio")

        # v61.1-fix(#23): 오디오 클립 핸들 해제
        for clip in audio_clips:
            _safe_close_resource(clip, "audio clip")

        return audio_path, subtitle_data

    # ============================================================
    # Properties
    # ============================================================

    @property
    def tts_engine(self):
        """현재 TTS 엔진"""
        return self._tts_engine

    @property
    def using_sovits(self) -> bool:
        """SoVITS 사용 여부"""
        return self._using_sovits

    @property
    def hybrid_enabled(self) -> bool:
        """하이브리드 모드 활성화 여부"""
        return self._hybrid_tts_enabled
