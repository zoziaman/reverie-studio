# src/modules_pro/tts_qwen3_adapter.py
# ============================================================
# v56.7: Qwen3-TTS 어댑터 (감정 표현 + 일관성 유지)
# Alibaba Qwen3-TTS 연동 (Python 직접 호출)
# - Base 모델: 보이스 클로닝 (참조 음성 복제)
# - VoiceDesign 모델: 감정/스타일 제어 (instruct 파라미터)
# - 캐릭터 시드: 동일 캐릭터 → 동일 목소리 보장
# ============================================================
import os
import re
import logging
import hashlib
import io
import contextlib
from typing import Dict, Any, Optional
from enum import Enum

# 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("tts_qwen3")
except ImportError:
    logger = logging.getLogger("tts_qwen3")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)

# TTS 설정
from .tts_engine import TTSConfig


# Qwen3-TTS 패키지 존재 여부
QWEN3_AVAILABLE = False
Qwen3TTSModel = None
soundfile = None


@contextlib.contextmanager
def _suppress_native_console_output():
    """qwen_tts import 시 SoX/torchaudio가 남기는 콘솔 출력을 숨긴다."""
    null_stream = open(os.devnull, "w", encoding="utf-8", errors="ignore")
    saved_stdout_fd = None
    saved_stderr_fd = None
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                saved_stdout_fd = os.dup(1)
                saved_stderr_fd = os.dup(2)
                os.dup2(null_stream.fileno(), 1)
                os.dup2(null_stream.fileno(), 2)
            except OSError:
                saved_stdout_fd = None
                saved_stderr_fd = None
            yield
    finally:
        for saved_fd, target_fd in ((saved_stdout_fd, 1), (saved_stderr_fd, 2)):
            if saved_fd is None:
                continue
            try:
                os.dup2(saved_fd, target_fd)
            finally:
                os.close(saved_fd)
        null_stream.close()

try:
    with _suppress_native_console_output():
        from qwen_tts import Qwen3TTSModel as _Model
        import soundfile as _sf
    Qwen3TTSModel = _Model
    soundfile = _sf
    QWEN3_AVAILABLE = True
    logger.info("[Qwen3TTS] qwen-tts 패키지 로드 완료")
except Exception as e:
    logger.warning(f"[Qwen3TTS] qwen-tts 패키지 없음: {e}")


# 언어 코드 매핑 (ko → korean)
LANGUAGE_MAP = {
    "ko": "korean",
    "en": "english",
    "ja": "japanese",
    "zh": "chinese",
    "de": "german",
    "fr": "french",
    "ru": "russian",
    "pt": "portuguese",
    "es": "spanish",
    "it": "italian",
}


class Qwen3ModelType(Enum):
    """Qwen3-TTS 모델 타입"""
    BASE = "base"                  # 보이스 클로닝 (참조 음성 필요)
    VOICE_DESIGN = "voice_design"  # 감정/스타일 제어 (instruct 지원)
    CUSTOM_VOICE = "custom_voice"  # 사전 정의 음성 (generate_custom_voice)


# =============================================================================
# v57.2.4: CustomVoice 스피커 매핑
# - 9개 프리셋 음성 중 캐릭터에 맞는 스피커 선택
# - narrator, grandpa는 SoVITS로 처리되므로 제외
# =============================================================================
CUSTOM_VOICE_SPEAKERS = {
    "grandma": "Vivian",      # 여성 (70대 할머니)
    "man": "Dylan",           # 중년 남성 (40-50대)
    "woman": "Serena",        # 중년 여성 (40-50대)
    "young_man": "Aiden",     # 청년 남성 (20-30대)
    "young_woman": "Sohee",   # 한국 여성 (20-30대)
    # 기본값: Dylan (남성)
}


# =============================================================================
# 감정 강도별 지시문 템플릿 (VoiceDesign 모델용)
# v56.7: 라디오 드라마용 2단계 감정 강도 시스템
#
# 강도 레벨:
# - normal: 담백한 감정 (일반 대화, 회상, 독백용) - 자연스럽고 듣기 편함
# - intense: 과한 감정 (클라이맥스, 막장 장면용) - 강렬한 감정 표현
# =============================================================================

# 캐릭터별 기본 설정 (영어로 상세 묘사 + 한국어 뉘앙스)
CHARACTER_VOICE_BASE = {
    "grandma": "An elderly Korean grandmother, 70+ years old. Warm, aged voice with slight tremor.",
    "grandpa": "An elderly Korean grandfather, 70+ years old. Deep, weathered voice, speaks slowly.",
    "man": "A middle-aged Korean man, 40-50 years old. Calm, steady male voice.",
    "woman": "A middle-aged Korean woman, 40-50 years old. Warm, gentle female voice.",
    "narrator": "A Korean male narrator, 30-40 years old. Clear, professional storytelling voice.",
    "young_man": "A young Korean man, 20-30 years old. Energetic, clear voice.",
    "young_woman": "A young Korean woman, 20-30 years old. Bright, lively voice.",
}

# 감정별 지시문 (2단계 강도)
# v57.2.4: 직접적 스타일 (Speak in a ... tone) - 테스트 결과 가장 효과적
EMOTION_TEMPLATES = {
    # 슬픔 (sad)
    "sad": {
        "normal": (
            "Speak in a very sad and sorrowful tone. Crying. Heartbroken."
        ),
        "intense": (
            "Speak in a deeply sad tone. Sobbing uncontrollably. "
            "Voice breaking with grief. Cannot stop crying."
        ),
    },
    # 분노 (angry)
    "angry": {
        "normal": (
            "Speak in a very angry and furious tone. Losing temper."
        ),
        "intense": (
            "Speak in an extremely angry tone. Screaming with rage. "
            "Completely losing control. Furious."
        ),
    },
    # 공포 (scared/fear)
    "scared": {
        "normal": (
            "Speak in a very scared and terrified tone. Trembling with fear."
        ),
        "intense": (
            "Speak in a terrified tone. Panicking. "
            "Voice shaking with pure fear. Hyperventilating."
        ),
    },
    # 기쁨 (happy)
    "happy": {
        "normal": (
            "Speak in a very happy and excited tone. Overjoyed."
        ),
        "intense": (
            "Speak in an extremely happy tone. Laughing with joy. "
            "Cannot contain the excitement. Ecstatic."
        ),
    },
    # 차분 (calm)
    "calm": {
        "normal": (
            "Speak in a calm and gentle tone. Peaceful and soothing."
        ),
        "intense": (
            "Speak in a very calm and serene tone. Meditative. "
            "Deeply peaceful. Zen-like tranquility."
        ),
    },
    # 흥분 (excited)
    "excited": {
        "normal": (
            "Speak in a very excited and energetic tone. Cannot contain excitement."
        ),
        "intense": (
            "Speak in an extremely excited tone. Bursting with energy. "
            "Words tumbling out rapidly. Thrilled."
        ),
    },
    # 속삭임 (whisper)
    "whisper": {
        "normal": (
            "Speak in a soft whisper. Very quiet and secretive."
        ),
        "intense": (
            "Speak in an urgent whisper. Hushed but intense. "
            "Fear of being heard. Desperate."
        ),
    },
    # v57.7.6: worried (걱정) - 공포 콘텐츠에서 불안/걱정 표현
    "worried": {
        "normal": (
            "Speak in a worried and anxious tone. Uneasy and concerned."
        ),
        "intense": (
            "Speak in a very worried tone. Deeply anxious. "
            "Voice trembling with concern. Restless."
        ),
    },
    # v57.7.6: desperate (절박) - 위기 상황의 절박한 감정
    "desperate": {
        "normal": (
            "Speak in a desperate and pleading tone. Begging for help."
        ),
        "intense": (
            "Speak in an extremely desperate tone. Hopeless. "
            "Voice breaking with desperation. Last resort."
        ),
    },
    # v62.4: warm (따뜻함) - 감동 콘텐츠에서 사랑/감사/온기 표현
    "warm": {
        "normal": (
            "Speak in a warm and tender tone. Gentle and loving. Full of affection."
        ),
        "intense": (
            "Speak in a deeply warm tone. Voice filled with love. "
            "Tender and caring. Almost tearful with gratitude."
        ),
    },
    # v56.8: neutral 폐기 → calm을 기본값으로 사용
    # "neutral"은 지시문이 약해서 품질이 안 좋음
    # 기존 neutral 요청은 calm으로 fallback
}

# =============================================================================
# 감정 Fallback 매핑 (v56.8)
# Gemini나 레거시 시스템에서 출력한 감정을 지원 감정으로 변환
# =============================================================================
EMOTION_FALLBACK_MAP = {
    # neutral 계열 → calm
    "neutral": "calm",
    "normal": "calm",
    "default": "calm",
    "flat": "calm",
    "plain": "calm",

    # fear 계열 → scared
    "fear": "scared",
    "afraid": "scared",
    "terrified": "scared",
    "frightened": "scared",
    "horror": "scared",

    # joy 계열 → happy
    "joy": "happy",
    "joyful": "happy",
    "cheerful": "happy",
    "delighted": "happy",
    "pleased": "happy",

    # anger 계열 → angry
    "anger": "angry",
    "rage": "angry",
    "furious": "angry",
    "mad": "angry",

    # sadness 계열 → sad
    "sadness": "sad",
    "sorrow": "sad",
    "grief": "sad",
    "melancholy": "sad",
    "depressed": "sad",

    # surprise 계열 → excited
    "surprise": "excited",
    "surprised": "excited",
    "shocked": "excited",
    "amazed": "excited",

    # 기타
    "anxiety": "worried",   # v57.7.6: 명사형 추가
    "anxious": "worried",  # v57.7.6: worried로 변경 (scared보다 정확)
    "nervous": "worried",   # v57.7.6: worried로 변경
    "tense": "worried",     # v57.7.6: worried로 변경
    "uneasy": "worried",    # v57.7.6: 추가
    "concerned": "worried", # v57.7.6: 추가
    "peaceful": "calm",
    "serene": "calm",

    # v62.4: warm 계열 추가
    "tender": "warm",
    "loving": "warm",
    "affectionate": "warm",
    "heartwarming": "warm",
    "gentle": "warm",
    "quiet": "whisper",
    "soft": "whisper",

    # v57.7.6: desperate 계열 추가
    "pleading": "desperate",
    "begging": "desperate",
    "hopeless": "desperate",
    "helpless": "desperate",

    # v57.7.6: LLM이 자주 출력하는 무효 감정 매핑
    "crying": "sad",
    "weeping": "sad",
    "tension": "scared",
    "suspense": "scared",
    "dread": "scared",
}

# 지원되는 9가지 감정 (v57.7.6: worried, desperate 추가)
SUPPORTED_EMOTIONS = frozenset(EMOTION_TEMPLATES.keys())


def normalize_emotion(emotion: Optional[str]) -> str:
    """
    감정 태그를 지원 감정으로 정규화

    v57.7.6: Gemini나 레거시 시스템에서 출력한 감정을
    TTS가 지원하는 9가지 감정으로 변환

    지원 감정: sad, angry, scared, happy, calm, excited, whisper, worried, desperate

    Args:
        emotion: 원본 감정 태그 (None, "neutral", "fear" 등)

    Returns:
        정규화된 감정 ("calm", "scared" 등)
    """
    if emotion is None:
        return "calm"

    emotion_lower = emotion.lower().strip()

    # 이미 지원 감정이면 그대로 반환
    if emotion_lower in SUPPORTED_EMOTIONS:
        return emotion_lower

    # Fallback 매핑 적용
    if emotion_lower in EMOTION_FALLBACK_MAP:
        mapped = EMOTION_FALLBACK_MAP[emotion_lower]
        logger.debug(f"[EmotionNorm] 감정 Fallback: {emotion} → {mapped}")
        return mapped

    # 매핑 없으면 calm 기본값
    # v57.6.6: 로그 prefix 변경 (Qwen3TTS → EmotionNorm) - SoVITS 전용 모드에서 혼란 방지
    logger.warning(f"[EmotionNorm] 알 수 없는 감정 '{emotion}' → calm 기본값 적용")
    return "calm"


# 레거시 호환용 단순 지시문 (기존 EMOTION_INSTRUCTIONS 대체)
EMOTION_INSTRUCTIONS = {
    emotion: templates["normal"]
    for emotion, templates in EMOTION_TEMPLATES.items()
}


# =============================================================================
# 캐릭터 시드 시스템 (일관성 유지용)
# v56.7: VoiceDesign 모델에서도 동일 캐릭터 → 동일 목소리 보장
#
# 원리: 캐릭터 ID를 시드로 변환하여 torch generator에 전달
# 동일 캐릭터 ID → 동일 시드 → 동일 음성 특성
# =============================================================================

def _generate_character_seed(character_id: str) -> int:
    """
    캐릭터 ID를 시드 값으로 변환

    동일한 character_id는 항상 동일한 시드를 반환하여
    VoiceDesign 모델에서도 목소리 일관성 유지

    Args:
        character_id: 캐릭터 고유 ID (예: "grandma_001", "horror_narrator")

    Returns:
        정수 시드 값 (0 ~ 2^31-1)
    """
    # MD5 해시의 앞 8바이트를 정수로 변환
    hash_bytes = hashlib.md5(character_id.encode('utf-8')).digest()[:8]
    seed = int.from_bytes(hash_bytes, byteorder='big') % (2**31)
    return seed


# 캐릭터 프로필 저장소 (에피소드 간 일관성 유지)
# 형식: { "character_id": {"seed": int, "instruct_base": str, "voice_ref": str} }
CHARACTER_PROFILES: Dict[str, Dict[str, Any]] = {}


class Qwen3TTSAdapter:
    """
    Qwen3-TTS 어댑터

    v56.6: Alibaba Qwen3-TTS 연동 (감정 표현 지원)
    - Base 모델: 보이스 클로닝 (참조 음성 복제, 0.95 유사도)
    - VoiceDesign 모델: 감정/스타일 제어 (instruct 파라미터)
    - Python 직접 호출 (HTTP 서버 불필요)

    모델 선택:
    - Qwen/Qwen3-TTS-12Hz-1.7B-Base: 보이스 클로닝용
    - Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign: 감정 표현용
    """

    def __init__(self, config: TTSConfig):
        """
        초기화

        Args:
            config: TTS 설정
        """
        self.config = config
        self._model = None
        self._model_type: Optional[Qwen3ModelType] = None
        self._available = False
        self._load_error: Optional[str] = None

        # v56.7: 캐릭터 프로필 (일관성 유지용)
        self._character_profiles: Dict[str, Dict[str, Any]] = {}

        # 모델 로드 시도
        if QWEN3_AVAILABLE:
            self._load_model()
        else:
            self._load_error = "qwen-tts 패키지 미설치"

        logger.info(f"[Qwen3TTS] 어댑터 초기화: model={config.qwen3_model}, type={self._model_type}, available={self._available}")

    def _load_model(self):
        """Qwen3-TTS 모델 로드"""
        try:
            logger.info(f"[Qwen3TTS] 모델 로딩 중: {self.config.qwen3_model}")

            # 모델 초기화 (device_map으로 GPU 강제 지정)
            device_map = f"{self.config.qwen3_device}:0" if self.config.qwen3_device == "cuda" else self.config.qwen3_device
            self._model = Qwen3TTSModel.from_pretrained(
                self.config.qwen3_model,
                device_map=device_map
            )

            # 모델 타입 감지
            model_type_str = getattr(self._model.model, 'tts_model_type', 'base')
            if model_type_str == 'voice_design':
                self._model_type = Qwen3ModelType.VOICE_DESIGN
            elif model_type_str == 'custom_voice':
                self._model_type = Qwen3ModelType.CUSTOM_VOICE
            else:
                self._model_type = Qwen3ModelType.BASE

            self._available = True
            self._load_error = None
            logger.info(f"[Qwen3TTS] 모델 로드 완료: type={self._model_type.value}")

        except ImportError as e:
            self._available = False
            self._load_error = f"패키지 import 실패: {e}"
            logger.error(f"[Qwen3TTS] {self._load_error}")

        except Exception as e:
            self._available = False
            self._load_error = f"모델 로드 실패: {e}"
            logger.error(f"[Qwen3TTS] {self._load_error}")

    def _clean_text(self, text: str) -> str:
        """
        TTS용 텍스트 전처리

        Args:
            text: 원본 텍스트

        Returns:
            전처리된 텍스트
        """
        if not text:
            return ""

        # 기본 정리
        text = text.strip()

        # 특수문자 변환
        text = re.sub(r'["""]', '"', text)
        text = re.sub(r"[''']", "'", text)
        text = re.sub(r'…', '...', text)
        text = re.sub(r'[-–—]', '-', text)

        # 연속 공백 제거
        text = re.sub(r'\s+', ' ', text)

        # 이모지 제거
        text = re.sub(r'[\U00010000-\U0010ffff]', '', text)

        return text.strip()

    def synthesize(
        self,
        text: str,
        ref_audio: str,
        ref_text: str,
        output_path: str,
        language: str = "ko",
        emotion: Optional[str] = None,
        instruct: Optional[str] = None,
        intensity: str = "normal",
        character: Optional[str] = None
    ) -> bool:
        """
        음성 합성

        모델 타입에 따라 동작:
        - Base 모델: 보이스 클로닝 (ref_audio 필요)
        - VoiceDesign 모델: 감정/스타일 제어 (emotion 또는 instruct 사용)

        Args:
            text: 합성할 텍스트
            ref_audio: 참조 음성 파일 경로 (Base 모델 필수, 3초 이상 권장)
            ref_text: 참조 음성의 텍스트 (Base 모델용)
            output_path: 출력 파일 경로
            language: 언어 코드 (ko, en, ja, zh 등)
            emotion: 감정 키워드 - calm, sad, scared, angry, happy 등
            instruct: 직접 지시문 (emotion보다 우선)
            intensity: 감정 강도 - "normal" (담백) 또는 "intense" (과함)
            character: 캐릭터 타입 - grandma, grandpa, man, woman, narrator 등

        Returns:
            성공 여부
        """
        if not self._available:
            logger.error(f"[Qwen3TTS] 엔진 사용 불가: {self._load_error}")
            return False

        # 텍스트 전처리
        clean_text = self._clean_text(text)
        if not clean_text:
            logger.warning("[Qwen3TTS] 빈 텍스트, 합성 스킵")
            return False

        try:
            # 출력 디렉토리 생성
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            # 언어 코드 변환 (ko → korean)
            lang_full = LANGUAGE_MAP.get(language, language)

            # 모델 타입에 따른 합성
            # v57.2.4: CustomVoice는 별도 API 사용 (generate_custom_voice)
            if self._model_type == Qwen3ModelType.VOICE_DESIGN:
                # VoiceDesign 모델: instruct 기반 감정 표현
                audios, sample_rate = self._synthesize_voice_design(
                    clean_text, lang_full, emotion, instruct, intensity, character
                )
            elif self._model_type == Qwen3ModelType.CUSTOM_VOICE:
                # CustomVoice 모델: 프리셋 스피커 + instruct
                audios, sample_rate = self._synthesize_custom_voice(
                    clean_text, lang_full, emotion, instruct, intensity, character
                )
            else:
                # Base 모델: 보이스 클로닝
                if not os.path.exists(ref_audio):
                    logger.error(f"[Qwen3TTS] 참조 음성 파일 없음: {ref_audio}")
                    return False
                audios, sample_rate = self._synthesize_voice_clone(
                    clean_text, ref_audio, ref_text, lang_full
                )

            # 오디오 파일 저장 (soundfile 사용)
            audio = audios[0]  # 첫 번째 오디오
            soundfile.write(output_path, audio, sample_rate)

            # 결과 확인
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                logger.info(f"[Qwen3TTS] 음성 합성 완료: {os.path.basename(output_path)}")
                return True
            else:
                logger.error("[Qwen3TTS] 출력 파일 생성 실패 또는 크기 부족")
                return False

        except Exception as e:
            logger.error(f"[Qwen3TTS] 음성 합성 실패: {e}")
            return False

    def _synthesize_voice_clone(
        self,
        text: str,
        ref_audio: str,
        ref_text: str,
        language: str
    ) -> tuple:
        """
        보이스 클로닝 (Base 모델)

        Args:
            text: 합성할 텍스트
            ref_audio: 참조 음성 파일 경로
            ref_text: 참조 음성의 텍스트
            language: 언어 (full name)

        Returns:
            (audios, sample_rate)
        """
        logger.debug(f"[Qwen3TTS] 보이스 클로닝: ref={os.path.basename(ref_audio)}")
        return self._model.generate_voice_clone(
            text=text,
            ref_audio=ref_audio,
            ref_text=ref_text,
            language=language
        )

    def _synthesize_voice_design(
        self,
        text: str,
        language: str,
        emotion: Optional[str] = None,
        instruct: Optional[str] = None,
        intensity: str = "normal",
        character: Optional[str] = None
    ) -> tuple:
        """
        감정 표현 합성 (VoiceDesign 모델)

        Args:
            text: 합성할 텍스트
            language: 언어 (full name)
            emotion: 감정 키워드
            instruct: 직접 지시문
            intensity: 감정 강도 ("normal" 또는 "intense")
            character: 캐릭터 타입

        Returns:
            (audios, sample_rate)
        """
        # 지시문 결정 우선순위: instruct > (character + emotion + intensity) > emotion > neutral
        if instruct:
            final_instruct = instruct
        else:
            final_instruct = self._build_instruct(emotion, intensity, character)

        if final_instruct:
            logger.debug(f"[Qwen3TTS] VoiceDesign: char={character}, emotion={emotion}, intensity={intensity}")
            logger.debug(f"[Qwen3TTS] instruct: {final_instruct[:80]}...")

        return self._model.generate_voice_design(
            text=text,
            instruct=final_instruct,
            language=language
        )

    def _synthesize_custom_voice(
        self,
        text: str,
        language: str,
        emotion: Optional[str] = None,
        instruct: Optional[str] = None,
        intensity: str = "normal",
        character: Optional[str] = None
    ) -> tuple:
        """
        v57.2.4: CustomVoice 모델 합성 (프리셋 스피커 + instruct)

        Args:
            text: 합성할 텍스트
            language: 언어 (full name)
            emotion: 감정 키워드
            instruct: 직접 지시문
            intensity: 감정 강도
            character: 캐릭터 타입

        Returns:
            (audios, sample_rate)
        """
        # 스피커 결정 (캐릭터 → 프리셋 스피커)
        speaker = CUSTOM_VOICE_SPEAKERS.get(character, "Dylan")  # 기본값 Dylan

        # instruct 생성 (감정만 사용, 캐릭터 설명은 스피커가 대신함)
        if instruct:
            final_instruct = instruct
        else:
            # 감정 템플릿만 사용 (캐릭터 기본 설명 제외 - 스피커가 담당)
            normalized_emotion = normalize_emotion(emotion)
            if normalized_emotion in EMOTION_TEMPLATES:
                intensity_key = intensity if intensity in ("normal", "intense") else "normal"
                final_instruct = EMOTION_TEMPLATES[normalized_emotion].get(intensity_key, "")
            else:
                final_instruct = ""

        logger.debug(f"[Qwen3TTS] CustomVoice: speaker={speaker}, char={character}, emotion={emotion}")
        if final_instruct:
            logger.debug(f"[Qwen3TTS] instruct: {final_instruct[:80]}...")

        return self._model.generate_custom_voice(
            text=text,
            language=language,
            speaker=speaker,
            instruct=final_instruct if final_instruct else None
        )

    def _build_instruct(
        self,
        emotion: Optional[str],
        intensity: str = "normal",
        character: Optional[str] = None
    ) -> str:
        """
        캐릭터 + 감정 + 강도를 조합하여 instruct 생성

        Args:
            emotion: 감정 키워드
            intensity: 감정 강도 ("normal" 또는 "intense")
            character: 캐릭터 타입

        Returns:
            조합된 instruct 문자열
        """
        parts = []

        # 1. 캐릭터 기본 설정
        if character and character in CHARACTER_VOICE_BASE:
            parts.append(CHARACTER_VOICE_BASE[character])

        # 2. 감정 정규화 + 강도 (v56.8: Fallback 적용)
        normalized_emotion = normalize_emotion(emotion)
        if normalized_emotion in EMOTION_TEMPLATES:
            intensity_key = intensity if intensity in ("normal", "intense") else "normal"
            emotion_instruct = EMOTION_TEMPLATES[normalized_emotion].get(intensity_key, "")
            if emotion_instruct:
                parts.append(emotion_instruct)

        return " ".join(parts)

    def load_voice(self, config: Dict[str, Any]) -> bool:
        """
        음성 모델 설정 변경

        Qwen3-TTS는 런타임에 다른 모델로 전환 가능

        Args:
            config: 음성 설정
                - model: 모델 ID (예: "Qwen/Qwen3-TTS-12Hz-1.7B")
                - device: 디바이스 (cuda, cpu)

        Returns:
            성공 여부
        """
        new_model = config.get("model", self.config.qwen3_model)
        new_device = config.get("device", self.config.qwen3_device)

        # 모델이 같으면 스킵 (v57.0.2: debug 레벨로 변경 - 매 문장마다 출력 방지)
        if new_model == self.config.qwen3_model and self._available:
            logger.debug("[Qwen3TTS] 이미 동일 모델 로드됨")
            return True

        # 기존 모델 정리
        self.cleanup()

        # 새 설정 적용
        self.config.qwen3_model = new_model
        self.config.qwen3_device = new_device

        # 모델 재로드
        self._load_model()

        return self._available

    def get_status(self) -> Dict[str, Any]:
        """
        엔진 상태 조회

        Returns:
            상태 정보
        """
        return {
            "engine": "Qwen3-TTS",
            "available": self._available,
            "model": self.config.qwen3_model,
            "model_type": self._model_type.value if self._model_type else None,
            "device": self.config.qwen3_device,
            "error": self._load_error,
            "package_installed": QWEN3_AVAILABLE,
            "supports_emotion": self._model_type == Qwen3ModelType.VOICE_DESIGN,
            "supports_voice_clone": self._model_type == Qwen3ModelType.BASE,
        }

    def cleanup(self) -> None:
        """리소스 정리 (GPU 메모리 해제)"""
        if self._model is not None:
            try:
                # 모델 메모리 해제
                del self._model
                self._model = None

                # CUDA 캐시 정리
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass

                logger.info("[Qwen3TTS] 모델 메모리 해제 완료")
            except Exception as e:
                logger.warning(f"[Qwen3TTS] 정리 중 오류: {e}")

        self._available = False

    @property
    def is_available(self) -> bool:
        """엔진 사용 가능 여부"""
        return self._available

    @property
    def engine_name(self) -> str:
        """엔진 이름"""
        return "Qwen3-TTS"

    def switch_model(self, model_id: str) -> bool:
        """
        모델 전환 (경량 ↔ 고품질)

        Args:
            model_id: 모델 ID
                - "Qwen/Qwen3-TTS-12Hz-0.6B" (경량, 3-4GB VRAM)
                - "Qwen/Qwen3-TTS-12Hz-1.7B" (고품질, 6-8GB VRAM)

        Returns:
            전환 성공 여부
        """
        return self.load_voice({"model": model_id})

    def get_supported_speakers(self) -> list:
        """지원하는 사전 정의 음성 목록"""
        if not self._available:
            return []
        try:
            return self._model.get_supported_speakers()
        except Exception:
            return []

    def get_supported_languages(self) -> list:
        """지원하는 언어 목록 (short code)"""
        return list(LANGUAGE_MAP.keys())

    def get_supported_emotions(self) -> list:
        """지원하는 감정 목록 (VoiceDesign 모델용)"""
        return list(EMOTION_INSTRUCTIONS.keys())

    def supports_emotion(self) -> bool:
        """감정 표현 지원 여부"""
        return self._model_type == Qwen3ModelType.VOICE_DESIGN

    def supports_voice_clone(self) -> bool:
        """보이스 클로닝 지원 여부"""
        return self._model_type == Qwen3ModelType.BASE

    def synthesize_with_emotion(
        self,
        text: str,
        output_path: str,
        emotion: str = "calm",
        language: str = "ko",
        intensity: str = "normal",
        character: Optional[str] = None,
        custom_instruct: Optional[str] = None
    ) -> bool:
        """
        감정 표현 음성 합성 (VoiceDesign/CustomVoice 모델)

        v56.7: 감정 강도 2단계 지원
        - normal: 담백한 감정 (일반 대화, 회상용)
        - intense: 과한 감정 (클라이맥스, 막장 장면용)

        v57.2.4: CustomVoice 모델도 지원 (instruct 파라미터 사용)

        Args:
            text: 합성할 텍스트
            output_path: 출력 파일 경로
            emotion: 감정 키워드 (calm, sad, scared, angry, happy 등)
            language: 언어 코드
            intensity: 감정 강도 ("normal" 또는 "intense")
            character: 캐릭터 타입 (grandma, grandpa, man, woman, narrator 등)
            custom_instruct: 사용자 정의 지시문 (있으면 모든 자동 생성 무시)

        Returns:
            성공 여부
        """
        # v57.2.4: VoiceDesign과 CustomVoice 둘 다 instruct 지원
        if self._model_type not in (Qwen3ModelType.VOICE_DESIGN, Qwen3ModelType.CUSTOM_VOICE):
            logger.error("[Qwen3TTS] 감정 표현은 VoiceDesign/CustomVoice 모델에서만 지원됩니다")
            return False

        return self.synthesize(
            text=text,
            ref_audio="",  # VoiceDesign은 참조 음성 불필요
            ref_text="",
            output_path=output_path,
            language=language,
            emotion=emotion,
            instruct=custom_instruct,
            intensity=intensity,
            character=character
        )

    def get_emotion_template(self, emotion: str, intensity: str = "normal") -> str:
        """
        특정 감정의 instruct 템플릿 조회

        Args:
            emotion: 감정 키워드
            intensity: 감정 강도 ("normal" 또는 "intense")

        Returns:
            instruct 템플릿 문자열
        """
        # v56.8: Fallback 적용
        normalized = normalize_emotion(emotion)
        if normalized in EMOTION_TEMPLATES:
            return EMOTION_TEMPLATES[normalized].get(intensity, "")
        return ""

    def get_character_base(self, character: str) -> str:
        """
        캐릭터 기본 음성 설명 조회

        Args:
            character: 캐릭터 타입

        Returns:
            캐릭터 음성 설명 문자열
        """
        return CHARACTER_VOICE_BASE.get(character, "")

    # =========================================================================
    # 일관성 유지 시스템 (v56.7)
    # =========================================================================

    def register_character(
        self,
        character_id: str,
        character_type: str = "narrator",
        custom_instruct: Optional[str] = None,
        ref_audio_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        캐릭터 프로필 등록 (일관성 유지용)

        같은 character_id로 합성하면 항상 동일한 목소리가 나옴
        에피소드 간, 세션 간 일관성 보장

        Args:
            character_id: 캐릭터 고유 ID (예: "grandma_001", "narrator_horror")
            character_type: 캐릭터 타입 (grandma, grandpa, man, woman, narrator 등)
            custom_instruct: 커스텀 지시문 (없으면 character_type 기반 자동 생성)
            ref_audio_path: 참조 음성 경로 (Base 모델용, VoiceDesign에서는 무시)

        Returns:
            등록된 프로필 정보
        """
        # 시드 생성 (동일 ID → 동일 시드)
        seed = _generate_character_seed(character_id)

        # 기본 지시문 결정
        base_instruct = custom_instruct or CHARACTER_VOICE_BASE.get(character_type, "")

        profile = {
            "character_id": character_id,
            "character_type": character_type,
            "seed": seed,
            "instruct_base": base_instruct,
            "ref_audio": ref_audio_path,
            "created": True
        }

        self._character_profiles[character_id] = profile
        CHARACTER_PROFILES[character_id] = profile  # 전역 저장소에도 저장

        logger.info(f"[Qwen3TTS] 캐릭터 등록: {character_id} (type={character_type}, seed={seed})")
        return profile

    def get_character_profile(self, character_id: str) -> Optional[Dict[str, Any]]:
        """캐릭터 프로필 조회"""
        return self._character_profiles.get(character_id) or CHARACTER_PROFILES.get(character_id)

    def synthesize_consistent(
        self,
        text: str,
        character_id: str,
        output_path: str,
        emotion: str = "calm",
        intensity: str = "normal",
        language: str = "ko"
    ) -> bool:
        """
        일관된 목소리로 음성 합성 (캐릭터 시드 기반)

        동일 character_id → 동일 목소리 보장
        VoiceDesign 모델의 "매번 다른 목소리" 문제 해결

        Args:
            text: 합성할 텍스트
            character_id: 캐릭터 고유 ID (register_character로 등록 필요)
            output_path: 출력 파일 경로
            emotion: 감정 키워드
            intensity: 감정 강도 ("normal" 또는 "intense")
            language: 언어 코드

        Returns:
            성공 여부
        """
        # 프로필 조회 (없으면 자동 등록)
        profile = self.get_character_profile(character_id)
        if not profile:
            logger.warning(f"[Qwen3TTS] 캐릭터 미등록, 자동 등록: {character_id}")
            profile = self.register_character(character_id, "narrator")

        # v56.8: torch 글로벌 시드 설정 (캐릭터 목소리 일관성 보장)
        # 동일 시드 → 동일 랜덤 패턴 → 동일 목소리
        seed = profile["seed"]
        try:
            import torch
            import random
            import numpy as np

            # 모든 랜덤 소스에 시드 적용
            torch.manual_seed(seed)
            random.seed(seed)
            np.random.seed(seed)

            # CUDA 시드도 설정 (GPU 사용 시)
            if torch.cuda.is_available():
                torch.cuda.manual_seed(seed)
                torch.cuda.manual_seed_all(seed)  # 멀티 GPU 대응

            # 결정론적 동작 강화 (선택적)
            # torch.backends.cudnn.deterministic = True  # 속도 저하 가능
            # torch.backends.cudnn.benchmark = False

            logger.info(f"[Qwen3TTS] 시드 적용 완료: {seed} (char={character_id})")
        except Exception as e:
            logger.warning(f"[Qwen3TTS] 시드 적용 실패: {e}")

        # 지시문 조합: 캐릭터 기본 + 감정
        base_instruct = profile.get("instruct_base", "")
        emotion_instruct = self._build_instruct(emotion, intensity, None)
        combined_instruct = f"{base_instruct} {emotion_instruct}".strip()

        # 합성
        return self.synthesize(
            text=text,
            ref_audio=profile.get("ref_audio", "") or "",
            ref_text="",
            output_path=output_path,
            language=language,
            emotion=None,  # 직접 instruct 사용
            instruct=combined_instruct,
            intensity=intensity,
            character=None  # 이미 instruct에 포함
        )

    def get_all_characters(self) -> Dict[str, Dict[str, Any]]:
        """등록된 모든 캐릭터 프로필 조회"""
        # 로컬 + 전역 병합
        all_profiles = {**CHARACTER_PROFILES, **self._character_profiles}
        return all_profiles

    def remove_character(self, character_id: str) -> bool:
        """캐릭터 프로필 삭제"""
        removed = False
        if character_id in self._character_profiles:
            del self._character_profiles[character_id]
            removed = True
        if character_id in CHARACTER_PROFILES:
            del CHARACTER_PROFILES[character_id]
            removed = True
        if removed:
            logger.info(f"[Qwen3TTS] 캐릭터 삭제: {character_id}")
        return removed

    def save_character_profiles(self, filepath: str) -> bool:
        """
        캐릭터 프로필을 파일로 저장 (세션 간 일관성 유지용)

        Args:
            filepath: 저장할 JSON 파일 경로

        Returns:
            성공 여부
        """
        import json
        try:
            all_profiles = self.get_all_characters()
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(all_profiles, f, ensure_ascii=False, indent=2)
            logger.info(f"[Qwen3TTS] 캐릭터 프로필 저장: {filepath} ({len(all_profiles)}개)")
            return True
        except Exception as e:
            logger.error(f"[Qwen3TTS] 프로필 저장 실패: {e}")
            return False

    def load_character_profiles(self, filepath: str) -> bool:
        """
        캐릭터 프로필 파일 로드 (이전 세션 복원)

        Args:
            filepath: JSON 파일 경로

        Returns:
            성공 여부
        """
        import json
        try:
            if not os.path.exists(filepath):
                logger.warning(f"[Qwen3TTS] 프로필 파일 없음: {filepath}")
                return False

            with open(filepath, 'r', encoding='utf-8') as f:
                profiles = json.load(f)

            self._character_profiles.update(profiles)
            CHARACTER_PROFILES.update(profiles)

            logger.info(f"[Qwen3TTS] 캐릭터 프로필 로드: {filepath} ({len(profiles)}개)")
            return True
        except Exception as e:
            logger.error(f"[Qwen3TTS] 프로필 로드 실패: {e}")
            return False
