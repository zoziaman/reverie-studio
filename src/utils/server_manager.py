# src/utils/server_manager.py
# ============================================================
# AI 서버 자동 시작/관리 매니저
#
# SD WebUI, GPT-SoVITS, ComfyUI 서버 자동 시작 및 상태 관리
# ============================================================
import os
import sys
import time
import subprocess
import threading
import requests
import logging
from typing import Dict, Optional, Callable, List
from dataclasses import dataclass
from enum import Enum

# 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("server_manager")
except ImportError:
    logger = logging.getLogger("server_manager")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)


_registered_processes: Dict[str, List[subprocess.Popen]] = {}


def _terminate_process(process: Optional[subprocess.Popen], server_name: str) -> bool:
    """Terminate a managed subprocess and its child tree when possible."""
    if process is None:
        return True

    try:
        if process.poll() is not None:
            return True

        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                text=True,
                timeout=15,
            )
        else:
            process.terminate()
            process.wait(timeout=10)

        if process.poll() is None:
            process.kill()

        logger.info(f"[ServerManager] {server_name} managed process stopped (PID: {process.pid})")
        return True
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except Exception:
            pass
        logger.warning(f"[ServerManager] {server_name} process kill timeout, forced kill (PID: {process.pid})")
        return True
    except Exception as e:
        logger.error(f"[ServerManager] {server_name} process stop failed: {e}")
        return False


def register_managed_process(server_name: str, process: Optional[subprocess.Popen]) -> None:
    """Register a detached subprocess so GUI shutdown can stop only app-started servers."""
    if not server_name or process is None:
        return
    existing = _registered_processes.setdefault(server_name, [])
    if any(getattr(proc, "pid", None) == getattr(process, "pid", None) for proc in existing if proc):
        return
    existing.append(process)
    logger.debug(f"[ServerManager] registered managed process: {server_name} (PID: {process.pid})")


def has_registered_processes(server_name: str) -> bool:
    """Return whether the app is currently tracking detached processes for this server."""
    processes = _registered_processes.get(server_name, [])
    alive = [proc for proc in processes if proc and proc.poll() is None]
    if alive:
        _registered_processes[server_name] = alive
        return True
    _registered_processes.pop(server_name, None)
    return False


def stop_registered_processes(server_names: Optional[List[str]] = None) -> Dict[str, bool]:
    """Stop detached managed subprocesses for the provided servers."""
    names = server_names or list(_registered_processes.keys())
    results: Dict[str, bool] = {}

    for server_name in names:
        processes = list(_registered_processes.get(server_name, []))
        success = True
        remaining: List[subprocess.Popen] = []

        for process in processes:
            stopped = _terminate_process(process, server_name)
            success = success and stopped
            if process and process.poll() is None:
                remaining.append(process)

        if remaining:
            _registered_processes[server_name] = remaining
        else:
            _registered_processes.pop(server_name, None)

        results[server_name] = success

    return results


class ServerStatus(Enum):
    """서버 상태"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class ServerConfig:
    """서버 설정"""
    name: str
    url: str
    health_endpoint: str  # 상태 확인 엔드포인트
    root_path: str        # 서버 루트 경로
    start_script: str     # 시작 스크립트 (상대경로)
    start_args: List[str] # 시작 인자
    port: int
    startup_timeout: int = 120  # 시작 대기 시간 (초)
    venv_path: Optional[str] = None  # 가상환경 경로 (선택)


class ServerInfo:
    """서버 정보 및 상태"""
    def __init__(self, config: ServerConfig):
        self.config = config
        self.status = ServerStatus.STOPPED
        self.process: Optional[subprocess.Popen] = None
        self.error_message: str = ""
        self.start_time: float = 0


class ServerManager:
    """
    AI 서버 통합 관리자

    SD WebUI, GPT-SoVITS, ComfyUI 서버 자동 시작 및 상태 관리
    """

    def __init__(self):
        self.servers: Dict[str, ServerInfo] = {}
        self._status_callbacks: List[Callable[[str, ServerStatus, str], None]] = []
        self._init_default_servers()

    def _init_default_servers(self):
        """기본 서버 설정 초기화"""
        # config에서 경로 로드 (.env 파일 포함)
        try:
            from config.settings import config
            sd_webui_root = config.SD_WEBUI_ROOT
            sd_webui_script = config.SD_WEBUI_SCRIPT
            sovits_root = config.GS_ROOT
            sovits_script = config.SOVITS_SCRIPT
            comfyui_root = config.COMFYUI_ROOT
            comfyui_script = config.COMFYUI_SCRIPT
            sd_url = config.SD_URL
            sovits_url = config.SOVITS_URL
            comfyui_url = config.COMFYUI_URL
        except ImportError:
            # v60.1.0: config 없으면 환경변수 → 빈 문자열 폴백 (하드코딩 제거)
            sd_webui_root = os.environ.get("SD_WEBUI_ROOT", "")
            sd_webui_script = "webui-user.bat"
            sovits_root = os.environ.get("GS_ROOT", os.environ.get("SOVITS_ROOT", ""))
            sovits_script = "go-webui.bat"
            comfyui_root = os.environ.get("COMFYUI_ROOT", "")
            comfyui_script = "run_nvidia_gpu.bat"
            sd_url = os.environ.get("SD_URL", "http://127.0.0.1:7860")
            sovits_url = os.environ.get("SOVITS_URL", "http://127.0.0.1:9880")
            comfyui_url = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")

        # SD WebUI - URL에서 포트 추출
        sd_port = int(sd_url.split(":")[-1].replace("/", "")) if ":" in sd_url else 7860
        self.register_server(ServerConfig(
            name="SD WebUI",
            url=sd_url,
            health_endpoint="/sdapi/v1/sd-models",
            root_path=sd_webui_root,
            start_script=sd_webui_script,
            start_args=[],
            port=sd_port,
            startup_timeout=180,  # SD는 모델 로딩이 오래 걸림
        ))

        # GPT-SoVITS API 서버 (go-webui.bat이 아닌 start_api_with_ffmpeg.bat 사용!)
        # v59.1.3: health_endpoint를 /set_gpt_weights로 변경 (API 서버 확인용)
        sovits_port = int(sovits_url.split(":")[-1].replace("/", "")) if ":" in sovits_url else 9880
        self.register_server(ServerConfig(
            name="GPT-SoVITS",
            url=sovits_url,
            health_endpoint="/set_gpt_weights",  # API 서버 확인용 (200 or 422 응답)
            root_path=sovits_root,
            start_script=sovits_script,  # .env에서 start_api_with_ffmpeg.bat으로 설정해야 함!
            start_args=[],
            port=sovits_port,
            startup_timeout=300,  # 5분 (모델 로딩 오래 걸림)
        ))

        # ComfyUI (v50)
        self.register_server(ServerConfig(
            name="ComfyUI",
            url=comfyui_url,
            health_endpoint="/system_stats",
            root_path=comfyui_root,
            start_script=comfyui_script,
            start_args=[],
            port=8188,
            startup_timeout=120,
        ))

    def register_server(self, config: ServerConfig):
        """서버 등록"""
        self.servers[config.name] = ServerInfo(config)
        logger.info(f"[ServerManager] 서버 등록: {config.name} ({config.url})")

    def add_status_callback(self, callback: Callable[[str, ServerStatus, str], None]):
        """상태 변경 콜백 추가"""
        self._status_callbacks.append(callback)

    def _notify_status(self, server_name: str, status: ServerStatus, message: str = ""):
        """상태 변경 알림"""
        for callback in self._status_callbacks:
            try:
                callback(server_name, status, message)
            except Exception as e:
                logger.error(f"[ServerManager] 콜백 오류: {e}")

    def check_server(self, server_name: str) -> bool:
        """서버 연결 상태 확인"""
        if server_name not in self.servers:
            return False

        info = self.servers[server_name]
        config = info.config

        try:
            response = requests.get(
                f"{config.url}{config.health_endpoint}",
                timeout=5
            )
            if response.status_code < 500:  # v59.2.3: 400/422도 "살아있음" (GPT-SoVITS)
                if info.status != ServerStatus.RUNNING:
                    info.status = ServerStatus.RUNNING
                    self._notify_status(server_name, ServerStatus.RUNNING, "연결됨")
                return True
        except requests.exceptions.RequestException:
            pass

        if info.status == ServerStatus.RUNNING:
            info.status = ServerStatus.STOPPED
            self._notify_status(server_name, ServerStatus.STOPPED, "연결 끊김")

        return False

    def check_all_servers(self) -> Dict[str, bool]:
        """모든 서버 상태 확인"""
        results = {}
        for name in self.servers:
            results[name] = self.check_server(name)
        return results

    def start_server(
        self,
        server_name: str,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> bool:
        """
        서버 시작

        Args:
            server_name: 서버 이름
            progress_callback: 진행률 콜백 (percent, message)

        Returns:
            성공 여부
        """
        if server_name not in self.servers:
            logger.error(f"[ServerManager] 알 수 없는 서버: {server_name}")
            return False

        info = self.servers[server_name]
        config = info.config

        # 이미 실행 중인지 확인
        if self.check_server(server_name):
            logger.info(f"[ServerManager] {server_name} 이미 실행 중")
            return True

        # v60.1.0: 경로 미설정 vs 존재하지 않음 구분
        if not config.root_path:
            error_msg = f"{server_name} 서버 경로 미설정 (.env에서 해당 경로를 설정하세요)"
        elif not os.path.exists(config.root_path):
            error_msg = f"서버 경로 없음: {config.root_path}"
        else:
            error_msg = None
        if error_msg:
            logger.error(f"[ServerManager] {error_msg}")
            info.status = ServerStatus.ERROR
            info.error_message = error_msg
            self._notify_status(server_name, ServerStatus.ERROR, error_msg)
            return False

        # 시작 스크립트 확인
        script_path = os.path.join(config.root_path, config.start_script)
        if not os.path.exists(script_path):
            # 대체 스크립트 시도
            alt_scripts = self._get_alternative_scripts(server_name)
            for alt in alt_scripts:
                alt_path = os.path.join(config.root_path, alt)
                if os.path.exists(alt_path):
                    script_path = alt_path
                    config.start_script = alt
                    break
            else:
                error_msg = f"시작 스크립트 없음: {config.start_script}"
                logger.error(f"[ServerManager] {error_msg}")
                info.status = ServerStatus.ERROR
                info.error_message = error_msg
                self._notify_status(server_name, ServerStatus.ERROR, error_msg)
                return False

        # 서버 시작
        info.status = ServerStatus.STARTING
        info.start_time = time.time()
        self._notify_status(server_name, ServerStatus.STARTING, "시작 중...")

        if progress_callback:
            progress_callback(0, f"{server_name} 시작 중...")

        try:
            # 환경변수 설정 (FFmpeg 등 필요한 도구 경로 추가)
            env = os.environ.copy()
            # 서버 root_path를 PATH에 추가 (FFmpeg 등 포함)
            env["PATH"] = config.root_path + os.pathsep + env.get("PATH", "")

            # 플랫폼별 Popen 옵션 설정
            # v59.1.3: 콘솔창에서 출력이 보이도록 PIPE 제거
            is_windows = sys.platform == 'win32'
            popen_kwargs = {
                "cwd": config.root_path,
                "env": env,
            }
            if is_windows:
                # CREATE_NEW_CONSOLE: 새 콘솔창에서 실행 (출력 보임)
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            else:
                # Linux/Mac: 출력을 파이프로 (백그라운드)
                popen_kwargs["stdout"] = subprocess.PIPE
                popen_kwargs["stderr"] = subprocess.PIPE

            # 실행 명령 구성
            if script_path.endswith('.bat'):
                cmd = [script_path] + config.start_args
                # Windows에서 .bat 파일 실행
                info.process = subprocess.Popen(
                    cmd,
                    shell=True,
                    **popen_kwargs
                )
            elif script_path.endswith('.py'):
                # Python 스크립트 직접 실행
                python_exe = sys.executable

                # GPT-SoVITS 전용: runtime python 사용
                if server_name == "GPT-SoVITS":
                    runtime_python = os.path.join(config.root_path, "runtime", "python.exe")
                    if os.path.exists(runtime_python):
                        python_exe = runtime_python
                        logger.info(f"[ServerManager] GPT-SoVITS: runtime python 사용 - {runtime_python}")
                elif config.venv_path:
                    # 플랫폼별 가상환경 python 경로
                    if is_windows:
                        venv_python = os.path.join(config.venv_path, "Scripts", "python.exe")
                    else:
                        venv_python = os.path.join(config.venv_path, "bin", "python")
                    if os.path.exists(venv_python):
                        python_exe = venv_python

                cmd = [python_exe, script_path] + config.start_args
                info.process = subprocess.Popen(
                    cmd,
                    **popen_kwargs
                )
            else:
                # 기타 실행 파일
                cmd = [script_path] + config.start_args
                info.process = subprocess.Popen(
                    cmd,
                    shell=True,
                    **popen_kwargs
                )

            logger.info(f"[ServerManager] {server_name} 프로세스 시작됨 (PID: {info.process.pid})")

        except Exception as e:
            error_msg = f"프로세스 시작 실패: {e}"
            logger.error(f"[ServerManager] {error_msg}")
            info.status = ServerStatus.ERROR
            info.error_message = error_msg
            self._notify_status(server_name, ServerStatus.ERROR, error_msg)
            return False

        # 서버 준비 대기
        start_time = time.time()
        while time.time() - start_time < config.startup_timeout:
            elapsed = time.time() - start_time
            percent = min(int((elapsed / config.startup_timeout) * 100), 95)

            if progress_callback:
                progress_callback(percent, f"{server_name} 준비 중... ({int(elapsed)}초)")

            if self.check_server(server_name):
                if progress_callback:
                    progress_callback(100, f"{server_name} 준비 완료")
                logger.info(f"[ServerManager] {server_name} 준비 완료 ({int(elapsed)}초)")
                return True

            # 프로세스가 종료되었는지 확인
            if info.process and info.process.poll() is not None:
                error_msg = f"프로세스 비정상 종료 (코드: {info.process.returncode})"
                logger.error(f"[ServerManager] {error_msg}")
                info.status = ServerStatus.ERROR
                info.error_message = error_msg
                self._notify_status(server_name, ServerStatus.ERROR, error_msg)
                return False

            time.sleep(2)

        # 타임아웃
        error_msg = f"시작 타임아웃 ({config.startup_timeout}초)"
        logger.error(f"[ServerManager] {server_name} {error_msg}")
        info.status = ServerStatus.ERROR
        info.error_message = error_msg
        self._notify_status(server_name, ServerStatus.ERROR, error_msg)
        return False

    def _get_alternative_scripts(self, server_name: str) -> List[str]:
        """대체 시작 스크립트 목록"""
        alternatives = {
            "SD WebUI": ["webui.bat", "run.bat", "launch.py"],
            "GPT-SoVITS": ["start_api_with_ffmpeg.bat", "go-api.bat", "api.bat", "go-webui.bat", "api.py", "api_v2.py"],
            "ComfyUI": ["main.py", "run.bat", "run_nvidia_gpu.bat", "run_cpu.bat"],
        }
        return alternatives.get(server_name, [])

    def stop_server(self, server_name: str) -> bool:
        """서버 중지"""
        if server_name not in self.servers:
            return False

        info = self.servers[server_name]

        if info.process and info.process.poll() is None:
            try:
                info.process.terminate()
                info.process.wait(timeout=10)
                logger.info(f"[ServerManager] {server_name} 중지됨")
            except subprocess.TimeoutExpired:
                info.process.kill()
                logger.warning(f"[ServerManager] {server_name} 강제 종료됨")
            except Exception as e:
                logger.error(f"[ServerManager] {server_name} 중지 실패: {e}")
                return False

        info.status = ServerStatus.STOPPED
        info.process = None
        self._notify_status(server_name, ServerStatus.STOPPED, "중지됨")
        return True

    def start_all_servers(
        self,
        servers: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[str, int, str], None]] = None
    ) -> Dict[str, bool]:
        """
        여러 서버 순차 시작

        Args:
            servers: 시작할 서버 목록 (None이면 전체)
            progress_callback: 진행률 콜백 (server_name, percent, message)

        Returns:
            서버별 성공 여부
        """
        if servers is None:
            servers = list(self.servers.keys())

        results = {}

        for server_name in servers:
            def server_progress(percent, message):
                if progress_callback:
                    progress_callback(server_name, percent, message)

            results[server_name] = self.start_server(server_name, server_progress)

        return results

    def start_servers_async(
        self,
        servers: Optional[List[str]] = None,
        callback: Optional[Callable[[Dict[str, bool]], None]] = None
    ):
        """
        비동기로 서버 시작 (백그라운드 스레드)

        Args:
            servers: 시작할 서버 목록
            callback: 완료 시 콜백
        """
        def worker():
            results = self.start_all_servers(servers)
            if callback:
                callback(results)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread

    def get_status(self, server_name: str) -> Dict:
        """서버 상태 조회"""
        if server_name not in self.servers:
            return {"status": "unknown", "message": "서버 없음"}

        info = self.servers[server_name]
        return {
            "status": info.status.value,
            "running": info.status == ServerStatus.RUNNING,
            "error": info.error_message,
            "url": info.config.url,
            "port": info.config.port,
        }

    def get_all_status(self) -> Dict[str, Dict]:
        """모든 서버 상태 조회"""
        return {name: self.get_status(name) for name in self.servers}

    def update_server_path(self, server_name: str, root_path: str):
        """서버 경로 업데이트"""
        if server_name in self.servers:
            self.servers[server_name].config.root_path = root_path
            logger.info(f"[ServerManager] {server_name} 경로 업데이트: {root_path}")


# 싱글톤 인스턴스
_server_manager: Optional[ServerManager] = None


def get_server_manager() -> ServerManager:
    """서버 매니저 싱글톤 반환"""
    global _server_manager
    if _server_manager is None:
        _server_manager = ServerManager()
    return _server_manager


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Server Manager Test")
    print("=" * 60)

    manager = get_server_manager()

    # 상태 콜백
    def on_status_change(name, status, message):
        print(f"[STATUS] {name}: {status.value} - {message}")

    manager.add_status_callback(on_status_change)

    # 모든 서버 상태 확인
    print("\n[서버 상태 확인]")
    status = manager.check_all_servers()
    for name, running in status.items():
        info = manager.get_status(name)
        print(f"  {name}: {'🟢 실행 중' if running else '🔴 중지됨'}")
        print(f"    URL: {info['url']}")
        print(f"    경로: {manager.servers[name].config.root_path}")

    print("\n[테스트 완료]")
