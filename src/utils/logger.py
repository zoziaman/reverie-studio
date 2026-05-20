# src/utils/logger.py
"""
Reverie Automation - 로깅 시스템

기능:
- 파일 로그 (rotating, 7일 보관)
- 콘솔 출력
- GUI 연동 (선택적)
- 에러 레벨별 분류
"""
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from typing import Optional, Callable


def _is_pytest_process() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    argv0 = os.path.basename(sys.argv[0] or "").lower()
    if "pytest" in argv0:
        return True
    return "pytest" in sys.modules


def _resolve_log_dir(log_dir: Optional[str]) -> str:
    """Prefer the configured project log directory when available."""
    if log_dir and log_dir != "data/logs":
        return log_dir

    try:
        from config.settings_v2 import config

        configured_dir = getattr(config, "LOGS_DIR", "")
        if configured_dir:
            return configured_dir
        data_dir = getattr(config, "DATA_DIR", "")
        if data_dir:
            return os.path.join(data_dir, "logs")
    except Exception:
        pass

    return log_dir or "data/logs"


class ReverieLogger:
    """
    Reverie 통합 로거

    사용법:
        from utils.logger import get_logger
        logger = get_logger("module_name")
        logger.info("메시지")
        logger.error("에러 발생", exc_info=True)
    """

    _instance = None
    _initialized = False
    _gui_callback: Optional[Callable[[str], None]] = None

    def __new__(cls, log_dir: str = "data/logs"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, log_dir: str = "data/logs"):
        if ReverieLogger._initialized:
            return

        self.log_dir = _resolve_log_dir(log_dir)
        os.makedirs(self.log_dir, exist_ok=True)

        # 로그 파일 경로
        today = datetime.now().strftime("%Y%m%d")
        if _is_pytest_process():
            self.log_file = os.path.join(self.log_dir, f"reverie_test_{today}.log")
            self.error_file = os.path.join(self.log_dir, f"errors_test_{today}.log")
        else:
            self.log_file = os.path.join(self.log_dir, f"reverie_{today}.log")
            self.error_file = os.path.join(self.log_dir, f"errors_{today}.log")

        # 루트 로거 설정
        self._setup_root_logger()

        ReverieLogger._initialized = True

    def _setup_root_logger(self):
        """루트 로거 설정"""
        # 루트 로거
        root_logger = logging.getLogger("reverie")
        root_logger.setLevel(logging.DEBUG)

        # 기존 핸들러 제거
        root_logger.handlers.clear()

        # 포맷터
        detailed_formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        simple_formatter = logging.Formatter(
            "[%(levelname)s] %(message)s"
        )

        # 1. 파일 핸들러 (전체 로그)
        file_handler = RotatingFileHandler(
            self.log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=7,  # 7일 보관
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)

        # 2. 에러 파일 핸들러 (에러만)
        error_handler = RotatingFileHandler(
            self.error_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=7,
            encoding="utf-8"
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(error_handler)

        # 3. 콘솔 핸들러 (INFO 이상)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)
        root_logger.addHandler(console_handler)

        # 4. GUI 핸들러 (선택적)
        gui_handler = GUILogHandler(self._get_gui_callback)
        gui_handler.setLevel(logging.INFO)
        gui_handler.setFormatter(simple_formatter)
        root_logger.addHandler(gui_handler)

        self.root_logger = root_logger

    def _get_gui_callback(self) -> Optional[Callable]:
        """GUI 콜백 반환"""
        return ReverieLogger._gui_callback

    @classmethod
    def set_gui_callback(cls, callback: Callable[[str], None]):
        """
        GUI 로그 콜백 설정

        Args:
            callback: 로그 메시지를 받을 함수 (예: self._add_log)
        """
        cls._gui_callback = callback

    def get_logger(self, name: str) -> logging.Logger:
        """
        모듈별 로거 반환

        Args:
            name: 모듈 이름

        Returns:
            logging.Logger
        """
        return logging.getLogger(f"reverie.{name}")

    def cleanup_old_logs(self, days: int = 7):
        """
        오래된 로그 파일 정리

        Args:
            days: 보관 일수
        """
        import glob
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=days)

        for pattern in ["reverie_*.log", "errors_*.log"]:
            for log_file in glob.glob(os.path.join(self.log_dir, pattern)):
                try:
                    # 파일명에서 날짜 추출
                    filename = os.path.basename(log_file)
                    date_str = filename.split("_")[1].split(".")[0]
                    file_date = datetime.strptime(date_str, "%Y%m%d")

                    if file_date < cutoff:
                        os.remove(log_file)
                        print(f"[LOG] 오래된 로그 삭제: {filename}")
                except OSError as e:
                    logging.debug(f"오래된 로그 삭제 실패: {e}")


class GUILogHandler(logging.Handler):
    """GUI 연동 로그 핸들러"""

    def __init__(self, callback_getter):
        super().__init__()
        self.callback_getter = callback_getter

    def emit(self, record):
        try:
            callback = self.callback_getter()
            if callback:
                msg = self.format(record)
                callback(msg)
        except Exception as e:
            logging.debug(f"GUI 로그 콜백 오류: {e}")


# ==============================================
# 편의 함수
# ==============================================

_logger_instance: Optional[ReverieLogger] = None


def init_logger(log_dir: str = "data/logs") -> ReverieLogger:
    """
    로거 초기화

    프로그램 시작 시 한 번 호출하세요.

    Args:
        log_dir: 로그 저장 디렉토리

    Returns:
        ReverieLogger 인스턴스
    """
    global _logger_instance
    _logger_instance = ReverieLogger(log_dir)
    return _logger_instance


def get_logger(name: str = "main") -> logging.Logger:
    """
    모듈별 로거 반환

    Args:
        name: 모듈 이름

    Returns:
        logging.Logger

    Example:
        logger = get_logger("media_factory")
        logger.info("영상 제작 시작")
        logger.error("오류 발생", exc_info=True)
    """
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = ReverieLogger()
    return _logger_instance.get_logger(name)


def set_gui_callback(callback: Callable[[str], None]):
    """
    GUI 로그 콜백 설정

    Args:
        callback: 로그 메시지를 받을 함수

    Example:
        set_gui_callback(self._add_log)
    """
    ReverieLogger.set_gui_callback(callback)


# ==============================================
# 사용자 친화적 에러 메시지 변환
# ==============================================

ERROR_MESSAGES = {
    "ConnectionError": "서버에 연결할 수 없습니다. 인터넷 연결을 확인하세요.",
    "TimeoutError": "서버 응답 시간이 초과되었습니다. 잠시 후 다시 시도하세요.",
    "FileNotFoundError": "필요한 파일을 찾을 수 없습니다.",
    "PermissionError": "파일 접근 권한이 없습니다. 관리자 권한으로 실행하세요.",
    "JSONDecodeError": "설정 파일이 손상되었습니다. 기본값으로 복구합니다.",
    "KeyError": "설정 파일에 필수 항목이 누락되었습니다.",
    "ValueError": "입력 값이 올바르지 않습니다.",
    "MemoryError": "메모리가 부족합니다. 다른 프로그램을 종료하세요.",
}


def get_user_friendly_error(exception: Exception) -> str:
    """
    사용자 친화적 에러 메시지 반환

    Args:
        exception: 발생한 예외

    Returns:
        str: 사용자 친화적 메시지
    """
    error_type = type(exception).__name__

    # 매핑된 메시지가 있으면 반환
    if error_type in ERROR_MESSAGES:
        return ERROR_MESSAGES[error_type]

    # SD/SoVITS 관련 에러
    error_str = str(exception).lower()
    if "connection" in error_str or "refused" in error_str:
        return "AI 서버에 연결할 수 없습니다. SD WebUI 또는 SoVITS가 실행 중인지 확인하세요."
    if "api" in error_str:
        return "API 호출 중 오류가 발생했습니다. API 키와 서버 상태를 확인하세요."
    if "cuda" in error_str or "gpu" in error_str:
        return "GPU 오류가 발생했습니다. 그래픽 드라이버를 확인하세요."

    # v60.1.0: RuntimeError는 개발자가 작성한 메시지이므로 보존
    error_msg = str(exception)
    if error_msg and len(error_msg) < 200:
        return f"오류: {error_msg}"

    # 기본 메시지
    return f"오류가 발생했습니다: {error_type}"


# ==============================================
# 테스트
# ==============================================

if __name__ == "__main__":
    # 초기화
    init_logger("test_logs")

    # 로거 생성
    logger = get_logger("test")

    # 테스트 로그
    logger.debug("디버그 메시지 (파일에만 기록)")
    logger.info("정보 메시지")
    logger.warning("경고 메시지")
    logger.error("에러 메시지")

    # 예외 로깅
    try:
        raise ValueError("테스트 예외")
    except Exception as e:
        logger.error(f"예외 발생: {get_user_friendly_error(e)}", exc_info=True)

    print("\n로그 파일을 확인하세요: test_logs/")
