# src/modules_pro/audio_synthesizer.py
# ============================================================
# v56.1: AudioSynthesizer - GPT-SoVITS 기반 음성 합성기
# MediaFactory에서 분리된 음성 합성 전담 모듈
# ============================================================
import os
import sys
import re
import time
import logging
import requests
import subprocess

from config.settings import config
from utils.runtime_utils import parse_url_host_port

# 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("audio_synthesizer")
except ImportError:
    logger = logging.getLogger("audio_synthesizer")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)


class AudioSynthesizer:
    """
    GPT-SoVITS 기반 음성 합성기

    v56.1: MediaFactory에서 분리된 음성 합성 전담 클래스
    - GPT-SoVITS 서버 연결/시동
    - TTS 생성
    - 가중치 로드
    - 텍스트 전처리
    """

    def __init__(self, channel: str = "daily_life_toon", sovits_url: str = None):
        """
        초기화

        Args:
            channel: 채널 타입 (horror, senior_makjang, senior_touching 등)
            sovits_url: GPT-SoVITS URL (기본: config.SOVITS_URL)
        """
        self.channel = channel
        self.sovits_url = sovits_url or config.SOVITS_URL

        # 현재 로드된 가중치
        self.current_gpt = None
        self.current_sovits = None

        logger.info(f"[AudioSynthesizer] 초기화: channel={channel}, sovits_url={self.sovits_url}")

    def check_connection(self) -> bool:
        """GPT-SoVITS 서버 연결 확인"""
        for endpoint in ("/openapi.json", "/docs", "/ping", "/"):
            try:
                res = requests.get(f"{self.sovits_url}{endpoint}", timeout=5)
                if res.status_code < 500:
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _tts_response_is_audio(res) -> bool:
        content_type = (res.headers.get("content-type") or "").lower()
        return (
            res.status_code == 200
            and len(res.content) > 1000
            and (
                res.content[:4] == b"RIFF"
                or content_type.startswith("audio/")
            )
        )

    @staticmethod
    def _tts_response_is_invalid_argument(res) -> bool:
        try:
            body = res.text[:300] if res.text else ""
        except Exception:
            body = ""
        return (
            res.status_code == 400
            and (
                "Errno 22" in body
                or "Invalid argument" in body
            )
        )

    def _recover_server_after_invalid_argument(self) -> bool:
        from .tts_server_manager import TTSServerManager

        prev_gpt = self.current_gpt
        prev_sovits = self.current_sovits
        manager = TTSServerManager(
            sovits_url=self.sovits_url,
            sovits_root=config.SOVITS_ROOT,
        )
        if not manager.restart_server(force=True):
            return False

        self.current_gpt = None
        self.current_sovits = None
        if prev_gpt and prev_sovits:
            return self.ensure_weights_loaded(prev_gpt, prev_sovits)
        return True

    def boot_sovits_engine(self) -> bool:
        """GPT-SoVITS 엔진 시동"""
        logger.info("[AudioSynthesizer] GPT-SoVITS 엔진 시동 시도")

        sovits_root = config.SOVITS_ROOT
        is_windows = sys.platform == 'win32'

        if is_windows:
            sovits_python = os.path.join(sovits_root, "runtime", "python.exe")
        else:
            sovits_python = os.path.join(sovits_root, "venv", "bin", "python")

        api_script = os.path.join(sovits_root, "api_v2.py")

        if not os.path.exists(sovits_python):
            logger.error(f"[AudioSynthesizer] SoVITS Python 없음: {sovits_python}")
            return False

        if not os.path.exists(api_script):
            logger.error(f"[AudioSynthesizer] api_v2.py 없음: {api_script}")
            return False

        try:
            popen_kwargs = {"cwd": sovits_root}
            if is_windows:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

            # v60.1.0: config.SOVITS_URL에서 host/port 파싱 (하드코딩 방지)
            _host, _port = parse_url_host_port(self.sovits_url, "127.0.0.1", 9880)
            subprocess.Popen(
                [sovits_python, api_script, "-a", _host, "-p", str(_port)],
                **popen_kwargs
            )
            logger.info("[AudioSynthesizer] GPT-SoVITS 시동 명령 전송")

            # 준비 대기 (최대 60초)
            for i in range(30):
                time.sleep(2)
                if self.check_connection():
                    logger.info("[AudioSynthesizer] GPT-SoVITS 시동 완료")
                    return True

            logger.error("[AudioSynthesizer] GPT-SoVITS 시동 타임아웃")
            return False

        except Exception as e:
            logger.error(f"[AudioSynthesizer] GPT-SoVITS 시동 실패: {e}")
            return False

    def ensure_weights_loaded(self, gpt_weight: str, sovits_weight: str) -> bool:
        """
        가중치 로드 확인 및 로드

        Args:
            gpt_weight: GPT 가중치 경로
            sovits_weight: SoVITS 가중치 경로

        Returns:
            로드 성공 여부
        """
        if self.current_gpt == gpt_weight and self.current_sovits == sovits_weight:
            logger.info("[AudioSynthesizer] 이미 가중치 로드됨")
            return True

        try:
            # v57.6.2: media_factory.py와 동일한 API 사용 (GET 방식)
            # 기존 /set_model (POST) → /set_gpt_weights, /set_sovits_weights (GET)
            for attempt in range(3):
                try:
                    # GPT 가중치 로드
                    gpt_url = f"{self.sovits_url}/set_gpt_weights?weights_path={gpt_weight}"
                    res1 = requests.get(gpt_url, timeout=30)

                    # SoVITS 가중치 로드
                    sov_url = f"{self.sovits_url}/set_sovits_weights?weights_path={sovits_weight}"
                    res2 = requests.get(sov_url, timeout=30)

                    if res1.status_code == 200 and res2.status_code == 200:
                        self.current_gpt = gpt_weight
                        self.current_sovits = sovits_weight
                        logger.info(f"[AudioSynthesizer] 가중치 로드 완료")
                        return True
                    else:
                        logger.warning(f"[AudioSynthesizer] 가중치 로드 응답 오류: GPT={res1.status_code}, SoVITS={res2.status_code}")
                except Exception as e:
                    delay = 2.0 * (2 ** attempt)
                    logger.warning(f"[AudioSynthesizer] 가중치 로드 실패, 재시도 {attempt+1}/3: {e}")
                    time.sleep(delay)

            logger.error("[AudioSynthesizer] 가중치 로드 최종 실패")
            return False

        except Exception as e:
            logger.error(f"[AudioSynthesizer] 가중치 로드 예외: {e}")
            return False

    def clean_text(self, text: str) -> str:
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

        # 특수문자 제거/변환
        text = re.sub(r'["""]', '"', text)
        text = re.sub(r"[''']", "'", text)
        text = re.sub(r'…', '...', text)
        text = re.sub(r'[-–—]', '-', text)

        # 연속 공백 제거
        text = re.sub(r'\s+', ' ', text)

        # 이모지 제거
        text = re.sub(r'[\U00010000-\U0010ffff]', '', text)

        return text.strip()

    def generate_tts(self, text: str, ref_audio: str, ref_text: str,
                     output_path: str, language: str = "ko") -> bool:
        """
        TTS 생성

        Args:
            text: 합성할 텍스트
            ref_audio: 참조 오디오 경로
            ref_text: 참조 텍스트
            output_path: 출력 파일 경로
            language: 언어 코드 (ko, en, ja, zh 등)

        Returns:
            생성 성공 여부
        """
        clean_text = self.clean_text(text)
        if not clean_text:
            logger.warning("[AudioSynthesizer] 빈 텍스트")
            return False

        try:
            tts_url = f"{self.sovits_url}/tts"
            payload = {
                "text": clean_text,
                "text_lang": language,
                "ref_audio_path": ref_audio,
                "prompt_text": ref_text,
                "prompt_lang": language,
                "top_k": 5,
                "top_p": 1.0,
                "temperature": 1.0,
                "speed_factor": 1.0
            }
            recovered_once = False

            for attempt in range(3):
                try:
                    res = requests.post(tts_url, json=payload, timeout=60)
                    if self._tts_response_is_audio(res):
                        with open(output_path, "wb") as f:
                            f.write(res.content)
                        logger.info(f"[AudioSynthesizer] TTS 생성 완료: {output_path}")
                        return True
                    if self._tts_response_is_invalid_argument(res) and not recovered_once:
                        logger.warning("[AudioSynthesizer] GPT-SoVITS ref_audio 상태가 꼬였습니다. 서버 재시작 후 재시도합니다.")
                        recovered_once = True
                        if self._recover_server_after_invalid_argument():
                            continue
                    logger.warning(
                        "[AudioSynthesizer] TTS 응답 실패: %s %s",
                        res.status_code,
                        (res.text[:200] if res.text else "empty"),
                    )
                except Exception as e:
                    delay = 1.0 * (2 ** attempt)
                    logger.warning(f"[AudioSynthesizer] TTS 실패, 재시도 {attempt+1}/3: {e}")
                    time.sleep(delay)

            logger.error("[AudioSynthesizer] TTS 생성 최종 실패")
            return False

        except Exception as e:
            logger.error(f"[AudioSynthesizer] TTS 예외: {e}")
            return False
