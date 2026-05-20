# src/modules_pro/tts_sovits_adapter.py
# ============================================================
# v56.5: GPT-SoVITS TTS 어댑터
# 기존 AudioSynthesizer, TTSServerManager 래핑
# ============================================================
import os
import logging
from typing import Dict, Any, Optional

# 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("tts_sovits")
except ImportError:
    logger = logging.getLogger("tts_sovits")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)

# 내부 모듈
from .tts_engine import TTSConfig, TTSEngineType
from .tts_server_manager import TTSServerManager, call_tts_api
from .audio_synthesizer import AudioSynthesizer


class GPTSoVITSAdapter:
    """
    GPT-SoVITS TTS 어댑터

    v56.5: 기존 AudioSynthesizer와 TTSServerManager를 래핑하여
    TTSEngine 인터페이스를 구현
    """

    def __init__(self, config: TTSConfig):
        """
        초기화

        Args:
            config: TTS 설정
        """
        self.config = config
        self._available = False

        # 기존 모듈 재사용
        self._synthesizer = AudioSynthesizer(sovits_url=config.sovits_url)
        self._server_manager = TTSServerManager(
            sovits_url=config.sovits_url,
            sovits_root=config.sovits_root
        )

        # 초기 연결 확인
        self._check_availability()

        logger.info(f"[GPTSoVITS] 어댑터 초기화: url={config.sovits_url}")

    def _check_availability(self) -> bool:
        """서버 연결 상태 확인"""
        self._available = self._server_manager.check_connection()
        return self._available

    def synthesize(
        self,
        text: str,
        ref_audio: str,
        ref_text: str,
        output_path: str,
        language: str = "ko",
        **kwargs  # v57.6.2: emotion, character 등 추가 파라미터 무시 (Qwen3 호환성)
    ) -> bool:
        """
        음성 합성

        Args:
            text: 합성할 텍스트
            ref_audio: 참조 음성 파일 경로
            ref_text: 참조 음성의 텍스트
            output_path: 출력 파일 경로
            language: 언어 코드
            **kwargs: 추가 파라미터 (emotion, character 등) - 무시됨

        Returns:
            성공 여부
        """
        # 서버 연결 확인 및 시동
        if not self._check_availability():
            logger.warning("[GPTSoVITS] 서버 연결 안됨, 시동 시도...")
            if not self._server_manager.boot_engine():
                logger.error("[GPTSoVITS] 서버 시동 실패")
                return False
            self._available = True

        # 텍스트 전처리
        clean_text = self._synthesizer.clean_text(text)
        if not clean_text:
            logger.warning("[GPTSoVITS] 빈 텍스트, 합성 스킵")
            return False

        # TTS 생성 (기존 AudioSynthesizer 사용)
        success = self._synthesizer.generate_tts(
            text=clean_text,
            ref_audio=ref_audio,
            ref_text=ref_text,
            output_path=output_path,
            language=language
        )

        if success:
            logger.info(f"[GPTSoVITS] 음성 합성 완료: {os.path.basename(output_path)}")
        else:
            logger.error(f"[GPTSoVITS] 음성 합성 실패: {text[:30]}...")

        return success

    def load_voice(self, config: Dict[str, Any]) -> bool:
        """
        음성 모델/가중치 로드

        Args:
            config: 음성 설정
                - gpt_weight: GPT 가중치 경로
                - sovits_weight: SoVITS 가중치 경로

        Returns:
            로드 성공 여부
        """
        gpt_weight = config.get("gpt_weight", self.config.gpt_weight)
        sovits_weight = config.get("sovits_weight", self.config.sovits_weight)

        if not gpt_weight or not sovits_weight:
            logger.warning("[GPTSoVITS] 가중치 경로 미지정")
            return False

        return self._synthesizer.ensure_weights_loaded(
            gpt_weight=gpt_weight,
            sovits_weight=sovits_weight
        )

    def get_status(self) -> Dict[str, Any]:
        """
        엔진 상태 조회

        Returns:
            상태 정보
        """
        self._check_availability()

        return {
            "engine": "GPT-SoVITS",
            "available": self._available,
            "url": self.config.sovits_url,
            "current_gpt": self._synthesizer.current_gpt,
            "current_sovits": self._synthesizer.current_sovits,
        }

    def cleanup(self) -> None:
        """리소스 정리 (SoVITS는 외부 서버이므로 특별한 정리 불필요)"""
        logger.info("[GPTSoVITS] 어댑터 정리 완료")

    @property
    def is_available(self) -> bool:
        """엔진 사용 가능 여부"""
        return self._check_availability()

    @property
    def engine_name(self) -> str:
        """엔진 이름"""
        return "GPT-SoVITS"

    def restart_server(self, force: bool = False) -> bool:
        """
        서버 재시작 (쿨다운 적용)

        Args:
            force: 쿨다운 무시

        Returns:
            재시작 성공 여부
        """
        success = self._server_manager.restart_server(force=force)
        if success:
            self._available = True
        return success
