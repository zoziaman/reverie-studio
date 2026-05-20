"""Runtime patches for robust app-managed AI server shutdown."""

import os
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional

import requests

from utils.server_manager import (
    ServerManager,
    ServerStatus,
    _terminate_process,
    has_registered_processes,
    register_managed_process,
    stop_registered_processes,
)
from utils.runtime_utils import parse_url_host_port


def apply_server_runtime_patch() -> None:
    """Patch ServerManager once so GUI startup/shutdown handles managed servers cleanly."""
    if getattr(ServerManager, "_reverie_runtime_patch_applied", False):
        return

    original_start_server = ServerManager.start_server

    def patched_start_server(
        self,
        server_name: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> bool:
        result = original_start_server(self, server_name, progress_callback)
        if result and server_name in self.servers:
            register_managed_process(server_name, self.servers[server_name].process)
        return result

    def patched_stop_server(self, server_name: str) -> bool:
        if server_name not in self.servers:
            return False

        info = self.servers[server_name]
        success = True

        if info.process and info.process.poll() is None:
            success = _terminate_process(info.process, server_name)

        if has_registered_processes(server_name):
            registered = stop_registered_processes([server_name])
            success = success and registered.get(server_name, True)

        info.status = ServerStatus.STOPPED
        info.process = None
        self._notify_status(server_name, ServerStatus.STOPPED, "stopped")
        return success

    def patched_stop_all_servers(
        self,
        server_names: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        names = server_names or list(self.servers.keys())
        return {name: self.stop_server(name) for name in names}

    from modules_pro.audio_synthesizer import AudioSynthesizer
    from modules_pro.image_generator import ImageGenerator
    from modules_pro.tts_server_manager import TTSServerManager, _safe_print
    from pipeline.image_pipeline import ImagePipeline

    def patched_image_pipeline_boot_sd_webui(self) -> bool:
        import requests as _requests

        self.logger = getattr(self, "logger", None)
        sd_root = self.sd_webui_root
        is_windows = sys.platform == "win32"
        sd_python = os.path.join(sd_root, "venv", "Scripts", "python.exe") if is_windows else os.path.join(sd_root, "venv", "bin", "python")
        sd_launch = os.path.join(sd_root, "launch.py")

        if not os.path.exists(sd_python) or not os.path.exists(sd_launch):
            return False

        try:
            popen_kwargs = {"cwd": sd_root}
            if is_windows:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

            process = subprocess.Popen([sd_python, sd_launch, "--api", "--xformers"], **popen_kwargs)
            register_managed_process("SD WebUI", process)

            for _ in range(90):
                time.sleep(2)
                try:
                    res = _requests.get(f"{self.sd_url}/sdapi/v1/sd-models", timeout=5)
                    if res.status_code == 200:
                        return True
                except Exception:
                    pass
            return False
        except Exception:
            return False

    def patched_image_generator_boot_sd_webui(self) -> bool:
        from config.settings import config as _config

        sd_root = _config.SD_WEBUI_ROOT

        is_windows = sys.platform == "win32"
        sd_python = os.path.join(sd_root, "venv", "Scripts", "python.exe") if is_windows else os.path.join(sd_root, "venv", "bin", "python")
        sd_launch = os.path.join(sd_root, "launch.py")
        if not os.path.exists(sd_python) or not os.path.exists(sd_launch):
            return False

        try:
            popen_kwargs = {"cwd": sd_root}
            if is_windows:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

            process = subprocess.Popen([sd_python, sd_launch, "--api", "--xformers"], **popen_kwargs)
            register_managed_process("SD WebUI", process)

            for _ in range(90):
                time.sleep(2)
                if self.check_connection():
                    return True
            return False
        except Exception:
            return False

    def patched_audio_synthesizer_boot_sovits_engine(self) -> bool:
        from config.settings import config as _config

        sovits_root = _config.SOVITS_ROOT
        is_windows = sys.platform == "win32"
        sovits_python = os.path.join(sovits_root, "runtime", "python.exe") if is_windows else os.path.join(sovits_root, "venv", "bin", "python")
        api_script = os.path.join(sovits_root, "api_v2.py")
        if not os.path.exists(sovits_python) or not os.path.exists(api_script):
            return False

        try:
            popen_kwargs = {"cwd": sovits_root}
            if is_windows:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

            host, port = parse_url_host_port(self.sovits_url, "127.0.0.1", 9880)
            process = subprocess.Popen([sovits_python, api_script, "-a", host, "-p", str(port)], **popen_kwargs)
            register_managed_process("GPT-SoVITS", process)

            for _ in range(30):
                time.sleep(2)
                if self.check_connection():
                    return True
            return False
        except Exception:
            return False

    def patched_tts_server_start_engine(self) -> bool:
        is_windows = sys.platform == "win32"
        gs_python = os.path.join(self.sovits_root, "runtime", "python.exe") if is_windows else os.path.join(self.sovits_root, "runtime", "bin", "python")
        if not is_windows and not os.path.exists(gs_python):
            gs_python = sys.executable

        gs_script = os.path.join(self.sovits_root, "api_v2.py")
        if not os.path.exists(gs_python) or not os.path.exists(gs_script):
            return False

        env = os.environ.copy()
        env["PATH"] = os.pathsep.join([self.sovits_root, r"C:\ffmpeg"] if is_windows else [self.sovits_root, "/usr/bin", "/usr/local/bin"]) + os.pathsep + env.get("PATH", "")
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            popen_kwargs = {"cwd": self.sovits_root, "env": env}
            if is_windows:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

            host, port = parse_url_host_port(self.sovits_url, "127.0.0.1", 9880)
            process = subprocess.Popen(
                [gs_python, gs_script, "-a", host, "-p", str(port), "-c", "GPT_SoVITS/configs/tts_infer.yaml"],
                **popen_kwargs,
            )
            register_managed_process("GPT-SoVITS", process)

            for _ in range(15):
                time.sleep(2)
                try:
                    requests.get(f"{self.sovits_url}/ping", timeout=2)
                    _safe_print("    engine started")
                    return True
                except (requests.RequestException, ConnectionError):
                    pass
            return False
        except Exception:
            return False

    def patched_tts_server_restart_server(self, force: bool = False) -> bool:
        current_time = time.time()
        if not force and (current_time - TTSServerManager._last_restart_time) < TTSServerManager._RESTART_COOLDOWN:
            return False
        if not os.path.exists(self.sovits_root):
            return False

        host, port = parse_url_host_port(self.sovits_url, "127.0.0.1", 9880)
        self.kill_port_process(port)
        if not self.wait_for_port_free(port, timeout=10):
            return False

        is_windows = sys.platform == "win32"
        gs_python = os.path.join(self.sovits_root, "runtime", "python.exe") if is_windows else os.path.join(self.sovits_root, "runtime", "bin", "python")
        if not is_windows and not os.path.exists(gs_python):
            gs_python = sys.executable
        gs_script = os.path.join(self.sovits_root, "api_v2.py")
        if not os.path.exists(gs_python) or not os.path.exists(gs_script):
            return False

        env = os.environ.copy()
        env["PATH"] = os.pathsep.join([self.sovits_root, r"C:\ffmpeg"] if is_windows else [self.sovits_root, "/usr/bin", "/usr/local/bin"]) + os.pathsep + env.get("PATH", "")
        env["PYTHONIOENCODING"] = "utf-8"

        popen_kwargs = {"cwd": self.sovits_root, "env": env}
        if is_windows:
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

        process = subprocess.Popen(
            [gs_python, gs_script, "-a", host, "-p", str(port), "-c", "GPT_SoVITS/configs/tts_infer.yaml"],
            **popen_kwargs,
        )
        register_managed_process("GPT-SoVITS", process)

        for _ in range(15):
            time.sleep(1)
            try:
                requests.get(f"{self.sovits_url}/", timeout=2)
                TTSServerManager._last_restart_time = time.time()
                return True
            except (requests.RequestException, OSError):
                pass
        return False

    ServerManager.start_server = patched_start_server
    ServerManager.stop_server = patched_stop_server
    ServerManager.stop_all_servers = patched_stop_all_servers
    ImagePipeline.boot_sd_webui = patched_image_pipeline_boot_sd_webui
    ImageGenerator.boot_sd_webui = patched_image_generator_boot_sd_webui
    AudioSynthesizer.boot_sovits_engine = patched_audio_synthesizer_boot_sovits_engine
    TTSServerManager._start_engine = patched_tts_server_start_engine
    TTSServerManager.restart_server = patched_tts_server_restart_server
    ServerManager._reverie_runtime_patch_applied = True
