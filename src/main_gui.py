# src/main_gui.py
"""
Reverie Automation GUI 실행 진입점
"""
# v58.2: 라이브러리 FutureWarning 숨기기
import os
os.environ["PYTHONWARNINGS"] = "ignore::FutureWarning"
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import sys
from utils.console_utils import configure_utf8_stdio

# 콘솔 인코딩 강제 설정 (Windows CP949 대응)
configure_utf8_stdio()

# ============================================================
# v62.37: 최우선 .env 로딩 (exe 모드에서 pydantic-settings 이전에 os.environ 반영)
# ============================================================
# pydantic-settings는 자체적으로 .env를 읽지만 os.environ에 반영하지 않아
# 코드 중간에 os.environ.get()으로 직접 읽는 부분(예: REVERIE_BASE_DIR)이 누락됨
def _load_dotenv_early():
    """스타트업 시 .env 파일을 os.environ에 직접 로드"""
    try:
        # exe 디렉토리 또는 프로젝트 루트에서 .env 탐색
        is_exe = (getattr(sys, 'frozen', False) or
                  (sys.executable.lower().endswith('.exe') and
                   not sys.executable.lower().endswith('python.exe')))
        search_dirs = []
        if is_exe:
            search_dirs.append(os.path.dirname(sys.executable))
        # 프로젝트 루트: main_gui.py → src → 프로젝트 루트
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        search_dirs.append(project_root)

        for d in search_dirs:
            env_path = os.path.join(d, ".env")
            if os.path.isfile(env_path):
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#') or '=' not in line:
                            continue
                        key, _, val = line.partition('=')
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        # 이미 설정된 환경변수는 덮어쓰지 않음 (배치파일 우선)
                        if key and key not in os.environ:
                            os.environ[key] = val
                break  # 첫 번째 .env만 로드
    except Exception:
        pass  # .env 없어도 정상 동작 (환경변수로 대체)


_load_dotenv_early()

# ============================================================
# FFmpeg PATH 전역 설정 (GPT-SoVITS TTS 호환성)
# ============================================================
# GPT-SoVITS가 ffmpeg subprocess를 호출할 때 PATH에서 찾음
# 프로그램 시작 시 PATH에 추가해야 모든 자식 프로세스에 적용됨
# v60.1.0: 하드코딩 경로 제거 → config + 환경변수 기반
def _setup_ffmpeg_path():
    """config.FFMPEG_PATH 및 환경변수 기반으로 FFmpeg PATH 설정"""
    ffmpeg_dirs = []
    # 1순위: config 인스턴스의 FFMPEG_PATH에서 디렉토리 추출
    try:
        from config.settings_v2 import config
        ffmpeg_path = getattr(config, 'FFMPEG_PATH', '')
        if ffmpeg_path and os.path.isfile(ffmpeg_path):
            ffmpeg_dirs.append(os.path.dirname(ffmpeg_path))
    except (ImportError, AttributeError):
        pass
    # 2순위: 환경변수 SOVITS_ROOT (GPT-SoVITS 내장 ffmpeg)
    sovits_root = os.environ.get("GS_ROOT", "") or os.environ.get("SOVITS_ROOT", "")
    if sovits_root and os.path.isdir(sovits_root):
        ffmpeg_dirs.append(sovits_root)
    # 3순위: 환경변수 FFMPEG_DIR (사용자 설치 ffmpeg)
    ffmpeg_dir = os.environ.get("FFMPEG_DIR", "")
    if ffmpeg_dir and os.path.isdir(ffmpeg_dir):
        ffmpeg_dirs.append(ffmpeg_dir)

    for ffpath in ffmpeg_dirs:
        if ffpath not in os.environ.get("PATH", ""):
            os.environ["PATH"] = ffpath + os.pathsep + os.environ.get("PATH", "")

_setup_ffmpeg_path()

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from gui.main_window import main


# ============================================================
# v60.1.0: 글로벌 예외 핸들러 (상용화 배포용)
# ============================================================
# 잡히지 않은 예외 발생 시 로그 파일에 기록 + 사용자 안내
def _setup_global_exception_handler():
    """치명적 크래시 시 로그 저장 + 안내 메시지"""
    import traceback
    import logging
    from datetime import datetime

    try:
        from config.settings import config as app_config
        crash_log_dir = os.path.join(app_config.DATA_DIR, "crash_logs")
    except Exception:
        crash_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "crash_logs")

    def global_exception_handler(exc_type, exc_value, exc_tb):
        """sys.excepthook — 잡히지 않은 예외 핸들러"""
        # KeyboardInterrupt는 그냥 종료
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

        # 콘솔 출력
        print("\n" + "=" * 60)
        print("[CRASH] Reverie Studio 예기치 않은 오류 발생")
        print("=" * 60)
        print(tb_text)

        # 크래시 로그 파일 저장
        try:
            os.makedirs(crash_log_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            crash_file = os.path.join(crash_log_dir, f"crash_{ts}.log")
            with open(crash_file, "w", encoding="utf-8") as f:
                f.write(f"Reverie Studio Crash Report\n")
                f.write(f"Time: {datetime.now().isoformat()}\n")
                f.write(f"Python: {sys.version}\n")
                f.write(f"{'=' * 60}\n\n")
                f.write(tb_text)
            print(f"\n[INFO] 크래시 로그 저장됨: {crash_file}")
        except Exception:
            pass  # 로그 저장 실패해도 프로그램 진행

        # GUI 에러 다이얼로그 시도
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Reverie Studio 오류",
                f"예기치 않은 오류가 발생했습니다.\n\n"
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"크래시 로그가 data/crash_logs/ 폴더에 저장되었습니다.\n"
                f"이 파일을 개발자에게 전달해주세요."
            )
            root.destroy()
        except Exception:
            pass  # tkinter 없으면 콘솔 출력만

    sys.excepthook = global_exception_handler

    # 스레드 예외도 캡처 (Python 3.8+)
    import threading
    if hasattr(threading, 'excepthook'):
        def thread_exception_handler(args):
            """threading.excepthook — 스레드 내 잡히지 않은 예외"""
            if issubclass(args.exc_type, SystemExit):
                return
            global_exception_handler(args.exc_type, args.exc_value, args.exc_traceback)
        threading.excepthook = thread_exception_handler

_setup_global_exception_handler()


if __name__ == "__main__":
    print("-" * 60)
    print("Reverie Automation GUI v60.1.0 Start")
    print("-" * 60)
    main()
