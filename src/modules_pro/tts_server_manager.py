# src/modules_pro/tts_server_manager.py
# ============================================================
# v56.1: TTS 서버 관리 유틸리티
# media_factory.py에서 분리
# GPT-SoVITS 서버 연결, 시동, 재시작, 포트 관리
# ============================================================
import os
import sys
import time
import random
import logging
import subprocess
import requests
from typing import Optional, List, Dict, Any, Tuple

from config.settings import config
from utils.runtime_utils import parse_url_host_port

# 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("tts_server_manager")
except ImportError:
    logger = logging.getLogger("tts_server_manager")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)


# ============================================================
# 안전 출력 함수
# ============================================================
def _safe_print(msg: str):
    """이모지를 제거하고 안전하게 출력"""
    try:
        print(msg)
    except UnicodeEncodeError:
        import re
        clean_msg = re.sub(r'[^\x00-\x7F\uAC00-\uD7A3\u3131-\u318E]+', '', msg)
        print(clean_msg)


# ============================================================
# TTS 서버 상태 관리
# ============================================================
class TTSServerManager:
    """
    GPT-SoVITS 서버 관리자

    - 서버 연결 확인
    - 자동 시동
    - 재시작 (쿨다운 적용)
    - 포트 관리
    """

    # 클래스 레벨 상태 (싱글톤 패턴 유사)
    _last_restart_time: float = 0.0
    _RESTART_COOLDOWN: int = 60  # 재시작 쿨다운: 60초

    def __init__(self, sovits_url: str = None, sovits_root: str = None):
        """
        초기화

        Args:
            sovits_url: GPT-SoVITS API URL (기본: config.SOVITS_URL)
            sovits_root: GPT-SoVITS 설치 경로 (기본: config.GS_ROOT)
        """
        self.sovits_url = sovits_url or config.SOVITS_URL
        self.sovits_root = sovits_root or config.GS_ROOT

        logger.info(f"[TTSServerManager] 초기화: url={self.sovits_url}")

    def check_connection(self, timeout: int = 5) -> bool:
        """
        서버 연결 확인

        Args:
            timeout: 타임아웃 (초)

        Returns:
            연결 성공 여부
        """
        try:
            res = requests.get(f"{self.sovits_url}/", timeout=timeout)
            return True  # 서버 응답하면 OK (404도 OK)
        except requests.exceptions.ConnectionError:
            logger.warning("[TTS] 서버 연결 실패")
            return False
        except Exception as e:
            logger.warning(f"[TTS] 서버 상태 확인 실패: {e}")
            return True  # 다른 에러는 일단 진행

    def boot_engine(self) -> bool:
        """
        GPT-SoVITS 엔진 시동

        Returns:
            시동 성공 여부
        """
        logger.info(f"[SoVITS] 엔진 상태 점검 중... (URL: {self.sovits_url})")
        _safe_print(f"\n [시스템] SoVITS 엔진 상태 점검 중... ({self.sovits_url})")

        # 연결 확인 (재시도 포함)
        check_endpoints = ["/", "/ping", "/docs"]
        for attempt in range(3):
            for ep in check_endpoints:
                try:
                    res = requests.get(f"{self.sovits_url}{ep}", timeout=3)
                    if res.status_code < 500:
                        logger.info(f"[SoVITS] 엔진 가동 확인됨 ({ep}: {res.status_code})")
                        _safe_print("    엔진 가동 확인됨.")
                        return True
                except requests.exceptions.ConnectionError:
                    continue
                except Exception as e:
                    logger.debug(f"[SoVITS] {ep} 체크 실패: {e}")
                    continue
            if attempt < 2:
                delay = 1.0 * (2 ** attempt) * (0.5 + random.random())
                logger.warning(f"[SoVITS] 연결 실패. 재시도 {attempt+1}/3, {delay:.1f}초 대기")
                time.sleep(delay)

        # 엔진이 꺼져 있으면 자동 시동
        logger.warning("[SoVITS] 엔진이 꺼져 있음. 자동 시동 시도")
        _safe_print("    엔진이 꺼져 있습니다. 자동 시동 중...")

        return self._start_engine()

    def _start_engine(self) -> bool:
        """실제 엔진 시동 로직"""
        is_windows = sys.platform == 'win32'

        # Python 경로 결정
        if is_windows:
            gs_python = os.path.join(self.sovits_root, "runtime", "python.exe")
        else:
            gs_python = os.path.join(self.sovits_root, "runtime", "bin", "python")
            if not os.path.exists(gs_python):
                gs_python = sys.executable

        gs_script = os.path.join(self.sovits_root, "api_v2.py")

        if not os.path.exists(gs_python):
            logger.error(f"[SoVITS] Python 없음: {gs_python}")
            return False

        if not os.path.exists(gs_script):
            logger.error(f"[SoVITS] api_v2.py 없음: {gs_script}")
            return False

        # 환경 변수 설정
        env = os.environ.copy()
        if is_windows:
            ffmpeg_paths = [self.sovits_root, r"C:\ffmpeg"]
        else:
            ffmpeg_paths = [self.sovits_root, "/usr/bin", "/usr/local/bin"]
        env["PATH"] = os.pathsep.join(ffmpeg_paths) + os.pathsep + env.get("PATH", "")
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            popen_kwargs = {"cwd": self.sovits_root, "env": env}
            if is_windows:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

            # v60.1.0: config.SOVITS_URL에서 host/port 파싱 (하드코딩 방지)
            _host, _port = parse_url_host_port(self.sovits_url, "127.0.0.1", 9880)
            subprocess.Popen(
                [gs_python, gs_script, "-a", _host, "-p", str(_port), "-c", "GPT_SoVITS/configs/tts_infer.yaml"],
                **popen_kwargs
            )
            logger.info("[SoVITS] 엔진 시동 명령 전송")

            # 준비 대기 (최대 30초)
            for i in range(15):
                time.sleep(2)
                try:
                    requests.get(f"{self.sovits_url}/ping", timeout=2)
                    logger.info("[SoVITS] 엔진 시동 완료")
                    _safe_print("    엔진 시동 완료.")
                    return True
                except (requests.RequestException, ConnectionError):
                    pass  # 아직 시동 중 — 다음 루프에서 재시도

            logger.error("[SoVITS] 엔진 시동 타임아웃")
            _safe_print("    엔진 시동 타임아웃. TTS가 실패할 수 있습니다.")
            return False

        except Exception as e:
            logger.error(f"[SoVITS] 엔진 시동 실패: {e}")
            _safe_print(f"    엔진 시동 실패: {e}")
            return False

    def kill_port_process(self, port: int = 9880) -> bool:
        """
        포트 사용 프로세스 강제 종료 (Windows 전용)

        Args:
            port: 종료할 포트 번호

        Returns:
            종료 성공 여부
        """
        if sys.platform != 'win32':
            logger.warning("[TTS] 포트 종료는 Windows만 지원")
            return False

        try:
            result = subprocess.run(
                f'netstat -ano | findstr ":{port}"',
                shell=True, capture_output=True, text=True
            )

            killed_pids = set()
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if 'LISTENING' in line:
                        parts = line.split()
                        if parts:
                            pid = parts[-1]
                            if pid not in killed_pids and pid != '0':
                                kill_result = subprocess.run(
                                    f'taskkill /F /T /PID {pid}',
                                    shell=True, capture_output=True, text=True
                                )
                                killed_pids.add(pid)
                                logger.info(f"[TTS] 프로세스 트리 강제 종료 (PID: {pid})")

            if killed_pids:
                logger.debug("[TTS] 포트 반환 대기 중 (3초)...")
                time.sleep(3)
                return True
            return False

        except Exception as e:
            logger.debug(f"[TTS] 프로세스 종료 중 오류: {e}")
            return False

    def wait_for_port_free(self, port: int = 9880, timeout: int = 10) -> bool:
        """
        포트가 비어있는지 확인하고 대기 (Windows 전용)

        Args:
            port: 확인할 포트
            timeout: 최대 대기 시간 (초)

        Returns:
            포트 사용 가능 여부
        """
        if sys.platform != 'win32':
            return True

        for i in range(timeout):
            result = subprocess.run(
                f'netstat -ano | findstr ":{port}" | findstr "LISTENING"',
                shell=True, capture_output=True, text=True
            )
            if not result.stdout.strip():
                logger.debug(f"[TTS] 포트 {port} 사용 가능")
                return True
            logger.debug(f"[TTS] 포트 {port} 아직 사용 중, 대기... ({i+1}/{timeout})")
            time.sleep(1)

        logger.warning(f"[TTS] 포트 {port} 해제 타임아웃")
        return False

    def restart_server(self, force: bool = False) -> bool:
        """
        TTS 서버 재시작 (쿨다운 적용)

        Args:
            force: 쿨다운 무시 여부

        Returns:
            재시작 성공 여부
        """
        # 쿨다운 체크
        current_time = time.time()
        if not force and (current_time - TTSServerManager._last_restart_time) < TTSServerManager._RESTART_COOLDOWN:
            remaining = int(TTSServerManager._RESTART_COOLDOWN - (current_time - TTSServerManager._last_restart_time))
            logger.info(f"[TTS] 재시작 쿨다운 중 ({remaining}초 남음), 재시작 건너뜀")
            return False

        if not os.path.exists(self.sovits_root):
            logger.error(f"[TTS] GPT-SoVITS 경로 없음: {self.sovits_root}")
            return False

        try:
            # Step 1: 기존 프로세스 강제 종료
            # v60.1.0: config.SOVITS_URL에서 host/port 파싱 (하드코딩 방지)
            _host, _port = parse_url_host_port(self.sovits_url, "127.0.0.1", 9880)

            logger.info("[TTS] Step 1: 기존 서버 프로세스 강제 종료...")
            self.kill_port_process(_port)

            # Step 2: 포트 해제 대기
            logger.info(f"[TTS] Step 2: 포트 {_port} 해제 대기...")
            if not self.wait_for_port_free(_port, timeout=10):
                logger.error("[TTS] 포트 해제 실패, 재시작 중단")
                return False

            # Step 3: 서버 시작
            logger.info("[TTS] Step 3: 서버 시작...")
            if sys.platform == 'win32':
                cmd = f'cd /d "{self.sovits_root}" && start /B runtime\\python.exe api_v2.py -a {_host} -p {_port} -c GPT_SoVITS/configs/tts_infer.yaml'
                subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                return self._start_engine()

            # Step 4: 서버 시작 확인
            logger.info("[TTS] Step 4: 서버 시작 확인 중...")
            for i in range(15):
                time.sleep(1)
                try:
                    res = requests.get(f"{self.sovits_url}/", timeout=2)
                    logger.info(f"[TTS] 서버 재시작 성공 ({i+1}초)")
                    TTSServerManager._last_restart_time = time.time()
                    return True
                except (requests.RequestException, OSError):
                    pass

            logger.error("[TTS] 서버 시작 타임아웃 (15초)")
            return False

        except Exception as e:
            logger.error(f"[TTS] 서버 재시작 중 오류: {e}")
            return False

    def get_ref_audio_for_role(self, voice_type: str) -> Optional[str]:
        """
        v57.2.3: 역할에 맞는 기본 참조 음성 경로 반환

        SoVITS 서버의 ref_audio 경로를 조회하여 Qwen3 Base 모델 안전망으로 활용

        Args:
            voice_type: 캐릭터 타입 (narrator, grandpa, grandma 등)

        Returns:
            참조 음성 파일 경로 또는 None
        """
        # voice_type → ref_audio 경로 매핑
        # 실제 프로젝트의 assets/ref_audio 폴더에서 조회
        ref_audio_dir = os.path.join(os.path.dirname(os.path.dirname(self.sovits_root)), "assets", "ref_audio")

        # 대체 경로: 프로젝트 루트 기준
        if not os.path.exists(ref_audio_dir):
            ref_audio_dir = os.path.join(config.DATA_DIR, "..", "assets", "ref_audio")

        if not os.path.exists(ref_audio_dir):
            logger.debug(f"[TTS] ref_audio 디렉토리 없음: {ref_audio_dir}")
            return None

        # voice_type에 맞는 파일 찾기
        voice_type_lower = voice_type.lower()
        for ext in ["wav", "mp3", "ogg"]:
            ref_path = os.path.join(ref_audio_dir, f"{voice_type_lower}.{ext}")
            if os.path.exists(ref_path):
                logger.debug(f"[TTS] ref_audio 발견: {ref_path}")
                return ref_path

        # 매핑 테이블로 대체 이름 시도
        alias_map = {
            "narrator": ["narration", "나레이션", "내레이션"],
            "grandpa": ["grandfather", "할아버지", "노인남"],
            "grandma": ["grandmother", "할머니", "노인여"],
            "man": ["male", "남자", "중년남"],
            "woman": ["female", "여자", "중년여"],
            "young_man": ["youngman", "청년", "청년남"],
            "young_woman": ["youngwoman", "청년여"],
            "middle_man": ["young_man", "man"],
            "middle_woman": ["young_woman", "woman"],
            "child": ["young_woman", "young_man", "girl", "boy"],
        }

        aliases = alias_map.get(voice_type_lower, [])
        for alias in aliases:
            for ext in ["wav", "mp3", "ogg"]:
                ref_path = os.path.join(ref_audio_dir, f"{alias}.{ext}")
                if os.path.exists(ref_path):
                    logger.debug(f"[TTS] ref_audio 발견 (alias): {ref_path}")
                    return ref_path

        logger.debug(f"[TTS] ref_audio 없음: {voice_type}")
        return None


# ============================================================
# TTS API 호출 유틸리티
# ============================================================
def call_tts_api(
    sovits_url: str,
    text: str,
    ref_audio_path: str,
    ref_text: str,
    text_language: str = "ko",
    timeout: int = 60,
    max_retries: int = 3,
    server_manager: TTSServerManager = None
) -> Optional[bytes]:
    """
    TTS API 호출 (지수 백오프 적용, GET/POST 모두 지원)

    Args:
        sovits_url: GPT-SoVITS API URL
        text: 합성할 텍스트
        ref_audio_path: 참조 오디오 경로 (정규화된 경로)
        ref_text: 참조 텍스트
        text_language: 텍스트 언어 코드 (ko, en, ja, zh)
        timeout: 요청 타임아웃 (초)
        max_retries: 최대 재시도 횟수
        server_manager: TTSServerManager 인스턴스 (서버 재시작용)

    Returns:
        오디오 데이터 (bytes) 또는 None
    """
    import urllib.parse

    # 서버 상태 확인
    if server_manager and not server_manager.check_connection():
        logger.warning("[TTS] 서버 연결 안됨, 재시작 시도...")
        if not server_manager.restart_server():
            logger.error("[TTS] 서버 사용 불가")
            return None

    # POST 방식 후보들
    post_candidates = [
        ("/tts", {
            "text": text,
            "text_lang": text_language,
            "ref_audio_path": ref_audio_path,
            "prompt_text": ref_text,
            "prompt_lang": text_language,
        }),
        ("/tts", {
            "text": text,
            "ref_audio": ref_audio_path,
            "prompt_text": ref_text,
        }),
        ("/infer", {
            "text": text,
            "text_lang": text_language,
            "ref_audio_path": ref_audio_path,
            "prompt_text": ref_text,
            "prompt_lang": text_language,
        }),
        ("/", {
            "text": text,
            "text_language": text_language,
            "refer_wav_path": ref_audio_path,
            "prompt_text": ref_text,
            "prompt_language": text_language,
        }),
    ]

    # GET 방식 파라미터
    get_params = {
        "text": text,
        "text_lang": text_language,
        "ref_audio_path": ref_audio_path,
        "prompt_text": ref_text,
        "prompt_lang": text_language,
    }

    last_error = None
    last_response = None

    for attempt in range(max_retries):
        # 1. POST 방식 시도
        for endpoint, payload in post_candidates:
            try:
                url = f"{sovits_url}{endpoint}"
                logger.debug(f"[TTS API] POST {url}")
                res = requests.post(url, json=payload, timeout=timeout)
                if res.status_code == 200 and len(res.content) > 1000:
                    logger.debug(f"[TTS API] POST 성공: {len(res.content)} bytes")
                    return res.content
                else:
                    last_response = f"{res.status_code}: {res.text[:200] if res.text else 'empty'}"
                    logger.debug(f"[TTS API] POST 실패 응답: {last_response}")
            except requests.exceptions.ConnectionError as e:
                last_error = f"연결 실패 ({sovits_url}): {e}"
                logger.debug(f"[TTS API] {last_error}")
            except Exception as e:
                last_error = str(e)
                logger.debug(f"[TTS API] POST 예외: {last_error}")
                continue

        # 2. GET 방식 시도
        try:
            query_string = urllib.parse.urlencode(get_params)
            url = f"{sovits_url}/tts?{query_string}"
            logger.debug(f"[TTS API] GET {url[:100]}...")
            res = requests.get(url, timeout=timeout)
            if res.status_code == 200 and len(res.content) > 1000:
                logger.debug(f"[TTS API] GET 성공: {len(res.content)} bytes")
                return res.content
            else:
                last_response = f"GET {res.status_code}: {res.text[:200] if res.text else 'empty'}"
                logger.debug(f"[TTS API] GET 실패 응답: {last_response}")
        except Exception as e:
            logger.debug(f"[TTS API] GET 예외: {e}")

        # 재시도 전 대기
        if attempt < max_retries - 1:
            # Errno 22 감지 시 재시작 시도
            if last_response and ("Errno 22" in last_response or "Invalid argument" in last_response):
                logger.warning(f"[TTS] Errno 22 감지 (ref_audio 경로 확인 필요): {ref_audio_path}")
                if server_manager and attempt == max_retries - 2:
                    server_manager.restart_server()

            delay = 1.0 * (2 ** attempt) * (0.5 + random.random())
            logger.warning(f"[TTS] API 호출 실패. 재시도 {attempt+1}/{max_retries}, {delay:.1f}초 대기")
            time.sleep(delay)

    error_detail = last_error or last_response or "알 수 없는 오류"
    logger.error(f"[TTS] API 호출 최종 실패: {error_detail}")
    return None


# ============================================================
# 편의 함수
# ============================================================
def get_tts_server_manager(sovits_url: str = None, sovits_root: str = None) -> TTSServerManager:
    """
    TTSServerManager 인스턴스 반환

    Args:
        sovits_url: GPT-SoVITS API URL
        sovits_root: GPT-SoVITS 설치 경로

    Returns:
        TTSServerManager 인스턴스
    """
    return TTSServerManager(sovits_url=sovits_url, sovits_root=sovits_root)
