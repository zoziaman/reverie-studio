# src/gui/mixins/server_mixin.py
"""
v60.1.0: 서버 관리 Mixin — SD WebUI, SoVITS, ComfyUI 상태 확인/시작

ReverieGUI에서 추출된 5개 메서드:
- _check_server_status: SD/SoVITS 서버 상태 폴링
- _start_ai_servers: 서버 수동 시작
- _auto_start_servers: 자동 시작 (설정 기반)
- _check_comfyui_status: ComfyUI 상태 확인
- _boot_comfyui: ComfyUI 자동 시동

의존하는 self 변수 (main_window.__init__에서 생성):
- self.sd_status_label, self.sd_model_label
- self.sovits_status_label
- self.comfyui_status_label (None일 수 있음)
"""
import threading
from tkinter import messagebox

from config.settings import config
from utils.logger import get_logger

logger = get_logger("server_mixin")


def probe_http_endpoints(base_url: str, endpoints: list[str], timeout: float = 5) -> bool:
    """Return True when any endpoint under the base URL answers with HTTP 200."""
    import requests

    normalized = (base_url or "").rstrip("/")
    for endpoint in endpoints:
        suffix = endpoint or "/"
        url = f"{normalized}{suffix}" if suffix.startswith("/") else f"{normalized}/{suffix}"
        try:
            resp = requests.get(url, timeout=timeout)
        except requests.RequestException:
            continue
        if resp.status_code == 200:
            return True
    return False


def safe_after(widget, callback, delay: int = 0) -> bool:
    """Best-effort Tk after that quietly skips callbacks during teardown."""
    try:
        if getattr(widget, "_is_shutting_down", False):
            return False
        exists = getattr(widget, "winfo_exists", None)
        if callable(exists) and not exists():
            return False
        widget.after(delay, callback)
        return True
    except Exception:
        return False


class ServerMixin:
    """서버 관리 횡단 관심사"""

    def _check_server_status(self):
        """SD WebUI 및 SoVITS 서버 상태 확인"""
        import requests

        def ui(callback):
            safe_after(self, callback)

        # SD WebUI 상태 체크
        try:
            sd_url = config.SD_URL.rstrip('/')
            resp = requests.get(f"{sd_url}/sdapi/v1/options", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                model_name = data.get("sd_model_checkpoint", "알 수 없음")
                # 모델명 축약 (경로 제거)
                if "/" in model_name:
                    model_name = model_name.split("/")[-1]
                if "\\" in model_name:
                    model_name = model_name.split("\\")[-1]

                ui(lambda: self.sd_status_label.configure(
                    text="✅ 연결됨",
                    text_color="green"
                ))
                ui(lambda: self.sd_model_label.configure(
                    text=f"모델: {model_name}",
                    text_color="lightblue"
                ))
            else:
                ui(lambda: self.sd_status_label.configure(
                    text=f"⚠️ 응답 오류 ({resp.status_code})",
                    text_color="orange"
                ))
                ui(lambda: self.sd_model_label.configure(text=""))
        except requests.exceptions.ConnectionError:
            ui(lambda: self.sd_status_label.configure(
                text="❌ 연결 실패 (서버 꺼짐)",
                text_color="red"
            ))
            ui(lambda: self.sd_model_label.configure(text=""))
        except requests.exceptions.Timeout:
            ui(lambda: self.sd_status_label.configure(
                text="⚠️ 응답 시간 초과",
                text_color="orange"
            ))
            ui(lambda: self.sd_model_label.configure(text=""))
        except Exception as e:
            ui(lambda: self.sd_status_label.configure(
                text=f"❌ 오류: {str(e)[:30]}",
                text_color="red"
            ))
            ui(lambda: self.sd_model_label.configure(text=""))

        # SoVITS 상태 체크
        try:
            sovits_url = config.SOVITS_URL.rstrip('/')
            # 여러 엔드포인트 시도
            for endpoint in ["/", "/docs", "/ping"]:
                try:
                    resp = requests.get(f"{sovits_url}{endpoint}", timeout=5)
                    if resp.status_code == 200:
                        ui(lambda: self.sovits_status_label.configure(
                            text="✅ 연결됨",
                            text_color="green"
                        ))
                        break
                except Exception:
                    continue
            else:
                ui(lambda: self.sovits_status_label.configure(
                    text="⚠️ 서버 응답 없음",
                    text_color="orange"
                ))
        except requests.exceptions.ConnectionError:
            ui(lambda: self.sovits_status_label.configure(
                text="❌ 연결 실패 (서버 꺼짐)",
                text_color="red"
            ))
        except requests.exceptions.Timeout:
            ui(lambda: self.sovits_status_label.configure(
                text="⚠️ 응답 시간 초과",
                text_color="orange"
            ))
        except Exception as e:
            ui(lambda: self.sovits_status_label.configure(
                text=f"❌ 오류: {str(e)[:30]}",
                text_color="red"
            ))

    def _start_ai_servers(self):
        """AI 서버 시작 (SD WebUI, GPT-SoVITS)"""
        try:
            from utils.server_manager import get_server_manager, ServerStatus
        except ImportError:
            messagebox.showerror("오류", "서버 매니저를 불러올 수 없습니다.")
            return

        manager = get_server_manager()

        # 서버 상태 확인
        sd_running = manager.check_server("SD WebUI")
        sovits_running = manager.check_server("GPT-SoVITS")

        if sd_running and sovits_running:
            messagebox.showinfo("알림", "모든 서버가 이미 실행 중입니다.")
            return

        # 시작할 서버 목록
        servers_to_start = []
        if not sd_running:
            servers_to_start.append("SD WebUI")
        if not sovits_running:
            servers_to_start.append("GPT-SoVITS")

        # 확인 대화상자
        server_list = ", ".join(servers_to_start)
        if not messagebox.askyesno(
            "서버 시작",
            f"다음 서버를 시작할까요?\n\n{server_list}\n\n"
            f"서버 시작에 1~3분 정도 소요될 수 있습니다."
        ):
            return

        # 진행 상태 표시
        self._add_log(f"[START] 서버 시작 중: {server_list}")

        # SD 상태 업데이트
        if "SD WebUI" in servers_to_start:
            self.after(0, lambda: self.sd_status_label.configure(
                text="🔄 시작 중...",
                text_color="#FFA500"
            ))

        # SoVITS 상태 업데이트
        if "GPT-SoVITS" in servers_to_start:
            self.after(0, lambda: self.sovits_status_label.configure(
                text="🔄 시작 중...",
                text_color="#FFA500"
            ))

        # 백그라운드에서 서버 시작
        def start_worker():
            for server_name in servers_to_start:
                self._add_log(f"  → {server_name} 시작 중...")
                success = manager.start_server(server_name)

                if success:
                    self._add_log(f"  [OK] {server_name} 시작 완료")
                else:
                    error = manager.get_status(server_name).get("error", "알 수 없는 오류")
                    self._add_log(f"  [ERROR] {server_name} 시작 실패: {error}")

            # 최종 상태 확인
            self.after(500, self._check_server_status)
            self._add_log("[DONE] 서버 시작 작업 완료")

        threading.Thread(target=start_worker, daemon=True).start()

    def _auto_start_servers(self):
        """자동 서버 시작 (설정에 따라)"""
        try:
            from utils.server_manager import get_server_manager
        except ImportError:
            return

        manager = get_server_manager()

        # 시작할 서버 확인
        servers_to_start = []
        for server_name in config.get_auto_start_list():
            server_name = server_name.strip()
            if server_name and not manager.check_server(server_name):
                servers_to_start.append(server_name)

        if not servers_to_start:
            return

        self._add_log(f"[START] 자동 서버 시작: {', '.join(servers_to_start)}")

        def auto_start_worker():
            for server_name in servers_to_start:
                if not manager.check_server(server_name):
                    self._add_log(f"  → {server_name} 자동 시작...")
                    success = manager.start_server(server_name)
                    if success:
                        self._add_log(f"  [OK] {server_name} 준비됨")
                    else:
                        self._add_log(f"  [WARN] {server_name} 시작 실패")

            self.after(500, self._check_server_status)

        threading.Thread(target=auto_start_worker, daemon=True).start()

    def _check_comfyui_status(self):
        """v50: ComfyUI 연결 상태 확인 및 자동 시동 (현재 비활성화)"""
        # 프리미엄 모드 UI가 비활성화되어 호출되지 않지만, 안전을 위해 유지
        if self.comfyui_status_label is None:
            return  # UI가 없으면 아무것도 안 함

        try:
            import requests
            response = requests.get(f"{config.COMFYUI_URL}/system_stats", timeout=5)
            if response.status_code == 200:
                self.after(0, lambda: self.comfyui_status_label.configure(
                    text="✅ ComfyUI 연결됨",
                    text_color="#4CAF50"
                ))
            else:
                self.after(0, lambda: self.comfyui_status_label.configure(
                    text="⚠️ ComfyUI 응답 없음 - 자동 시동 중...",
                    text_color="#ff9800"
                ))
                self._boot_comfyui()
        except Exception:
            self.after(0, lambda: self.comfyui_status_label.configure(
                text="⏳ ComfyUI 자동 시동 중...",
                text_color="#ff9800"
            ))
            self._boot_comfyui()

    def _boot_comfyui(self):
        """ComfyUI 자동 시동"""
        import subprocess
        import os
        import time
        import sys
        import requests

        comfyui_root = getattr(config, 'COMFYUI_ROOT', r'C:\AI\ComfyUI\ComfyUI')
        comfyui_script = getattr(config, 'COMFYUI_SCRIPT', 'run_nvidia_gpu.bat')
        comfyui_main = os.path.join(comfyui_root, "main.py")

        # 플랫폼별 Python 경로 시도
        is_windows = sys.platform == 'win32'
        if is_windows:
            python_candidates = [
                os.path.join(comfyui_root, "python_embeded", "python.exe"),  # portable 버전
                os.path.join(comfyui_root, "venv", "Scripts", "python.exe"),  # venv 버전
                sys.executable,  # 시스템 Python
            ]
        else:
            python_candidates = [
                os.path.join(comfyui_root, "venv", "bin", "python"),  # venv 버전
                sys.executable,  # 시스템 Python
            ]

        started = False  # 프로세스 시작 여부

        try:
            # 1. main.py가 있는지 확인
            if os.path.exists(comfyui_main):
                # Python 실행 파일 찾기
                python_exe = None
                for candidate in python_candidates:
                    if os.path.exists(candidate):
                        python_exe = candidate
                        break

                if python_exe:
                    self._add_log(f"[ComfyUI] Python 직접 실행 방식으로 시동 중...")
                    self._add_log(f"   Python: {python_exe}")

                    popen_kwargs = {"cwd": comfyui_root}
                    if is_windows:
                        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

                    # v60.1.0: config.COMFYUI_URL에서 host/port 파싱 (하드코딩 방지)
                    from pipeline.pipeline_utils import parse_url_host_port
                    _host, _port = parse_url_host_port(config.COMFYUI_URL, "127.0.0.1", 8188)
                    subprocess.Popen(
                        [python_exe, comfyui_main, "--listen", _host, "--port", str(_port)],
                        **popen_kwargs
                    )
                    started = True
                else:
                    # Python 못찾으면 bat/sh 파일 시도
                    raise FileNotFoundError("Python not found")
            else:
                # main.py 없으면 bat/sh 파일 시도
                raise FileNotFoundError("main.py not found")

        except FileNotFoundError:
            # 스크립트 파일 방식
            if is_windows:
                bat_path = os.path.join(comfyui_root, comfyui_script)
                if os.path.exists(bat_path):
                    self._add_log(f"[ComfyUI] 배치 파일 방식으로 시동 중... ({bat_path})")
                    subprocess.Popen(
                        ["cmd", "/c", bat_path],
                        cwd=comfyui_root,
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                    started = True
            else:
                sh_path = os.path.join(comfyui_root, "run.sh")
                if os.path.exists(sh_path):
                    self._add_log(f"[ComfyUI] 쉘 스크립트 방식으로 시동 중... ({sh_path})")
                    subprocess.Popen(["bash", sh_path], cwd=comfyui_root)
                    started = True

            if not started:
                self._add_log(f"[ComfyUI] 시동 스크립트를 찾을 수 없습니다")
                self._add_log(f"   경로: {comfyui_root}")
                self._add_log(f"   main.py 존재: {os.path.exists(comfyui_main)}")
                self.after(0, lambda: self.comfyui_status_label.configure(
                    text="❌ ComfyUI 경로 확인 필요",
                    text_color="#f44336"
                ))
                return

        except Exception as e:
            self._add_log(f"[ComfyUI] 시동 오류: {e}")
            self.after(0, lambda: self.comfyui_status_label.configure(
                text=f"❌ ComfyUI 시동 오류",
                text_color="#f44336"
            ))
            return

        # 프로세스가 시작되었으면 연결 대기
        if started:
            self._add_log("[ComfyUI] 로딩 대기 중... (최대 2분)")
            self.after(0, lambda: self.comfyui_status_label.configure(
                text="⏳ ComfyUI 로딩 중... (0초)",
                text_color="#ff9800"
            ))

            for i in range(24):  # 24 * 5초 = 2분
                time.sleep(5)
                elapsed_sec = (i + 1) * 5

                try:
                    response = requests.get(f"{config.COMFYUI_URL}/system_stats", timeout=3)
                    if response.status_code == 200:
                        self._add_log(f"[ComfyUI] 시동 완료! ({elapsed_sec}초)")
                        self.after(0, lambda: self.comfyui_status_label.configure(
                            text="✅ ComfyUI 연결됨",
                            text_color="#4CAF50"
                        ))
                        return
                except Exception as e:
                    logger.debug(f"서버 상태 UI 업데이트 실패: {e}")

                # 진행률 업데이트
                self.after(0, lambda sec=elapsed_sec: self.comfyui_status_label.configure(
                    text=f"⏳ ComfyUI 로딩 중... ({sec}초)",
                    text_color="#ff9800"
                ))

            # 타임아웃
            self._add_log("[ComfyUI] 시동 타임아웃 (2분 초과)")
            self.after(0, lambda: self.comfyui_status_label.configure(
                text="❌ ComfyUI 시동 실패 (타임아웃)",
                text_color="#f44336"
            ))
