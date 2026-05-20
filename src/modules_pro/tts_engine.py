# src/modules_pro/tts_engine.py
# ============================================================
# v56.5: TTS 엔진 추상화 레이어
# GPT-SoVITS와 Qwen3-TTS 간 전환 및 롤백 지원
# ============================================================
import os
import logging
from typing import Protocol, Dict, Any, Optional, Tuple, runtime_checkable
from dataclasses import dataclass, field
from enum import Enum

# 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("tts_engine")
except ImportError:
    logger = logging.getLogger("tts_engine")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)


# ============================================================
# TTS 엔진 타입
# ============================================================
class TTSEngineType(Enum):
    """TTS 엔진 종류"""
    SOVITS = "sovits"      # GPT-SoVITS (기존)
    QWEN3 = "qwen3"        # Qwen3-TTS (신규)
    SUPERTONIC = "supertonic"  # Supertonic 3 로컬 ONNX TTS


# ============================================================
# TTS 설정
# ============================================================
@dataclass
class TTSConfig:
    """
    TTS 엔진 설정

    v56.5: GPT-SoVITS와 Qwen3-TTS 공통/개별 설정
    """
    # 엔진 선택
    engine_type: TTSEngineType = TTSEngineType.SOVITS

    # 공통 설정
    language: str = "ko"
    fallback_enabled: bool = True  # 롤백 활성화

    # GPT-SoVITS 설정 — v60.1.0: config에서 기본값 유도
    sovits_url: str = ""  # 빈 문자열이면 create_tts_engine()에서 config.SOVITS_URL 사용
    sovits_root: str = ""
    gpt_weight: str = ""
    sovits_weight: str = ""

    # Qwen3-TTS 설정
    # 모델 옵션:
    # - Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign: 감정 표현 지원 (권장)
    # - Qwen/Qwen3-TTS-12Hz-1.7B-Base: 보이스 클로닝 지원
    # - Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice: 프리셋 스피커 + instruct (v57.2.4)
    # - Qwen/Qwen3-TTS-12Hz-0.6B-Base: 경량 모델 (저사양)
    qwen3_model: str = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"  # v57.2.4: CustomVoice 기본값
    qwen3_device: str = "cuda"
    qwen3_use_flash_attn: bool = True  # FlashAttention 사용

    # Supertonic 3 settings.
    # Defaults favor short-form Korean production: balanced steps, compact
    # chunks, and a little less pause between generated segments.
    supertonic_auto_download: bool = True
    supertonic_default_voice: str = "M1"
    supertonic_voice_map: Dict[str, str] = field(default_factory=dict)
    supertonic_total_steps: int = 5
    supertonic_speed: float = 1.05
    supertonic_max_chunk_length: int = 120
    supertonic_silence_duration: float = 0.25
    supertonic_intra_op_threads: int = 0
    supertonic_inter_op_threads: int = 0


# ============================================================
# TTS 엔진 인터페이스 (Protocol)
# ============================================================
@runtime_checkable
class TTSEngine(Protocol):
    """
    TTS 엔진 추상 인터페이스

    모든 TTS 어댑터가 구현해야 하는 메서드 정의
    """

    def synthesize(
        self,
        text: str,
        ref_audio: str,
        ref_text: str,
        output_path: str,
        language: str = "ko"
    ) -> bool:
        """
        음성 합성

        Args:
            text: 합성할 텍스트
            ref_audio: 참조 음성 파일 경로
            ref_text: 참조 음성의 텍스트
            output_path: 출력 파일 경로
            language: 언어 코드 (ko, en, ja, zh 등)

        Returns:
            성공 여부
        """
        ...

    def load_voice(self, config: Dict[str, Any]) -> bool:
        """
        음성 모델/가중치 로드

        Args:
            config: 음성 설정 (가중치 경로, 참조 음성 등)

        Returns:
            로드 성공 여부
        """
        ...

    def get_status(self) -> Dict[str, Any]:
        """
        엔진 상태 조회

        Returns:
            상태 정보 딕셔너리
        """
        ...

    def cleanup(self) -> None:
        """리소스 정리"""
        ...

    @property
    def is_available(self) -> bool:
        """엔진 사용 가능 여부"""
        ...

    @property
    def engine_name(self) -> str:
        """엔진 이름"""
        ...


# ============================================================
# TTS 엔진 팩토리
# ============================================================
class TTSEngineFactory:
    """
    TTS 엔진 팩토리

    v56.5: 설정 기반 엔진 생성 + 자동 롤백 지원
    """

    _instances: Dict[Tuple[Any, ...], TTSEngine] = {}

    @staticmethod
    def _cache_key(config: TTSConfig) -> Tuple[Any, ...]:
        """Build a cache key from settings that change engine behavior."""
        return (
            config.engine_type,
            config.language,
            config.sovits_url,
            config.sovits_root,
            config.gpt_weight,
            config.sovits_weight,
            config.qwen3_model,
            config.qwen3_device,
            config.qwen3_use_flash_attn,
            config.supertonic_auto_download,
            config.supertonic_default_voice,
            tuple(sorted((config.supertonic_voice_map or {}).items())),
            config.supertonic_total_steps,
            config.supertonic_speed,
            config.supertonic_max_chunk_length,
            config.supertonic_silence_duration,
            config.supertonic_intra_op_threads,
            config.supertonic_inter_op_threads,
        )

    @classmethod
    def create(cls, config: TTSConfig) -> TTSEngine:
        """
        설정에 따른 TTS 엔진 생성

        Args:
            config: TTS 설정

        Returns:
            TTS 엔진 인스턴스
        """
        engine_type = config.engine_type
        cache_key = cls._cache_key(config)

        # 캐시된 인스턴스 반환 (동작에 영향을 주는 설정까지 동일한 경우)
        if cache_key in cls._instances:
            logger.debug(f"[TTSFactory] 캐시된 {engine_type.value} 엔진 반환")
            return cls._instances[cache_key]

        # 새 인스턴스 생성
        if engine_type == TTSEngineType.QWEN3:
            from .tts_qwen3_adapter import Qwen3TTSAdapter
            engine = Qwen3TTSAdapter(config)
            logger.info(f"[TTSFactory] Qwen3-TTS 엔진 생성")
        elif engine_type == TTSEngineType.SUPERTONIC:
            from .tts_supertonic_adapter import SupertonicTTSAdapter
            engine = SupertonicTTSAdapter(config)
            logger.info("[TTSFactory] Supertonic 3 엔진 생성")
        else:
            from .tts_sovits_adapter import GPTSoVITSAdapter
            engine = GPTSoVITSAdapter(config)
            logger.info(f"[TTSFactory] GPT-SoVITS 엔진 생성")

        cls._instances[cache_key] = engine
        return engine

    @classmethod
    def get_with_fallback(cls, config: TTSConfig) -> TTSEngine:
        """
        메인 엔진 실패 시 폴백 엔진 반환

        Qwen3 사용 불가 → GPT-SoVITS로 자동 롤백

        Args:
            config: TTS 설정

        Returns:
            사용 가능한 TTS 엔진
        """
        primary = cls.create(config)

        if primary.is_available:
            logger.info(f"[TTSFactory] {primary.engine_name} 엔진 사용")
            return primary

        # 롤백: 로컬 대체 엔진 실패 시 SoVITS로
        if config.engine_type in {TTSEngineType.QWEN3, TTSEngineType.SUPERTONIC}:
            logger.warning(f"[TTSFactory] {config.engine_type.value} 사용 불가, GPT-SoVITS로 롤백")
            fallback_config = TTSConfig(
                engine_type=TTSEngineType.SOVITS,
                language=config.language,
                sovits_url=config.sovits_url,
                sovits_root=config.sovits_root,
                gpt_weight=config.gpt_weight,
                sovits_weight=config.sovits_weight,
                fallback_enabled=False  # 무한 롤백 방지
            )
            fallback = cls.create(fallback_config)
            if fallback.is_available:
                return fallback
            logger.error("[TTSFactory] 폴백 엔진(SoVITS)도 사용 불가")

        # 폴백도 실패하면 원래 엔진 반환 (에러 처리는 호출자가)
        return primary

    @classmethod
    def clear_cache(cls):
        """캐시된 엔진 인스턴스 정리"""
        for engine in cls._instances.values():
            try:
                engine.cleanup()
            except Exception as e:
                logger.warning(f"[TTSFactory] 엔진 정리 중 오류: {e}")
        cls._instances.clear()
        logger.info("[TTSFactory] 엔진 캐시 초기화 완료")

    @classmethod
    def switch_engine(cls, new_type: TTSEngineType, config: TTSConfig) -> TTSEngine:
        """
        런타임 엔진 전환

        Args:
            new_type: 전환할 엔진 타입
            config: TTS 설정 (engine_type은 무시됨)

        Returns:
            새 TTS 엔진
        """
        logger.info(f"[TTSFactory] 엔진 전환: {config.engine_type.value} → {new_type.value}")

        # 새 설정 생성
        new_config = TTSConfig(
            engine_type=new_type,
            language=config.language,
            fallback_enabled=config.fallback_enabled,
            sovits_url=config.sovits_url,
            sovits_root=config.sovits_root,
            gpt_weight=config.gpt_weight,
            sovits_weight=config.sovits_weight,
            qwen3_model=config.qwen3_model,
            qwen3_device=config.qwen3_device,
            qwen3_use_flash_attn=config.qwen3_use_flash_attn,
            supertonic_auto_download=config.supertonic_auto_download,
            supertonic_default_voice=config.supertonic_default_voice,
            supertonic_voice_map=dict(config.supertonic_voice_map),
            supertonic_total_steps=config.supertonic_total_steps,
            supertonic_speed=config.supertonic_speed,
            supertonic_max_chunk_length=config.supertonic_max_chunk_length,
            supertonic_silence_duration=config.supertonic_silence_duration,
            supertonic_intra_op_threads=config.supertonic_intra_op_threads,
            supertonic_inter_op_threads=config.supertonic_inter_op_threads,
        )

        # 기존 엔진 정리 (선택적)
        for key in [key for key in cls._instances if key and key[0] == new_type]:
            try:
                cls._instances[key].cleanup()
            except Exception as e:
                logger.warning(f"[TTSFactory] 기존 {new_type.value} 엔진 정리 중 오류: {e}")
            del cls._instances[key]

        return cls.create(new_config)


# ============================================================
# 편의 함수
# ============================================================
def get_tts_engine(
    engine_type: str = "sovits",
    fallback: bool = True,
    **kwargs
) -> TTSEngine:
    """
    TTS 엔진 간편 생성 함수

    Args:
        engine_type: "sovits", "qwen3", 또는 "supertonic"
        fallback: 롤백 활성화 여부
        **kwargs: 추가 설정 (sovits_url, qwen3_model 등)

    Returns:
        TTS 엔진 인스턴스

    Example:
        >>> engine = get_tts_engine("qwen3", fallback=True)
        >>> engine.synthesize("안녕하세요", ref_audio, ref_text, output_path)
    """
    try:
        from config.settings import config as app_config
        sovits_url = kwargs.get("sovits_url", app_config.SOVITS_URL)
        sovits_root = kwargs.get("sovits_root", getattr(app_config, "GS_ROOT", ""))
    except ImportError:
        sovits_url = kwargs.get("sovits_url", "http://127.0.0.1:9880")
        sovits_root = kwargs.get("sovits_root", "")

    tts_config = TTSConfig(
        engine_type=TTSEngineType(engine_type),
        fallback_enabled=fallback,
        sovits_url=sovits_url,
        sovits_root=sovits_root,
        gpt_weight=kwargs.get("gpt_weight", ""),
        sovits_weight=kwargs.get("sovits_weight", ""),
        qwen3_model=kwargs.get("qwen3_model", "Qwen/Qwen3-TTS-12Hz-0.6B-Base"),
        qwen3_device=kwargs.get("qwen3_device", "cuda"),
        supertonic_auto_download=kwargs.get("supertonic_auto_download", True),
        supertonic_default_voice=kwargs.get("supertonic_default_voice", "M1"),
        supertonic_voice_map=kwargs.get("supertonic_voice_map", {}),
        supertonic_total_steps=kwargs.get("supertonic_total_steps", 5),
        supertonic_speed=kwargs.get("supertonic_speed", 1.05),
        supertonic_max_chunk_length=kwargs.get("supertonic_max_chunk_length", 120),
        supertonic_silence_duration=kwargs.get("supertonic_silence_duration", 0.25),
        supertonic_intra_op_threads=kwargs.get("supertonic_intra_op_threads", 0),
        supertonic_inter_op_threads=kwargs.get("supertonic_inter_op_threads", 0),
    )

    if fallback:
        return TTSEngineFactory.get_with_fallback(tts_config)
    else:
        return TTSEngineFactory.create(tts_config)
