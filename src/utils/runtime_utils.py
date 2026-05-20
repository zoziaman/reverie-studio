"""
Runtime-safe utility helpers shared across GUI, modules, and pipeline layers.

These helpers stay dependency-light so higher-level modules can import them
without creating architecture inversions such as modules_pro -> pipeline.
"""
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Callable, Optional, Sequence

try:
    from utils.logger import get_logger
    logger = get_logger("runtime_utils")
except ImportError:
    logger = logging.getLogger("runtime_utils")


_gui_log_callback: Optional[Callable[[str], None]] = None


def set_gui_log_callback(callback: Optional[Callable[[str], None]]):
    """Register a global GUI log callback used by safe_print."""
    global _gui_log_callback
    _gui_log_callback = callback


def safe_print(msg: str, end: str = "\n", flush: bool = False):
    """Print safely across Windows encodings and mirror logs to the GUI."""
    if _gui_log_callback:
        try:
            _gui_log_callback(msg)
        except Exception as e:
            logging.getLogger(__name__).debug(f"GUI log callback failed and was ignored: {e}")

    try:
        print(msg, end=end, flush=flush)
    except UnicodeEncodeError:
        clean_msg = re.sub(r'[^\x00-\x7F\uAC00-\uD7A3\u3131-\u318E]+', '', msg)
        print(clean_msg, end=end, flush=flush)


def sanitize_for_path(name: str, max_length: int = 80) -> str:
    """Return a filesystem-safe slug for filenames and directory names."""
    if not name:
        return "unknown"
    safe_name = re.sub(r'[\\/*?:"<>|#]', '_', name)
    safe_name = re.sub(r'_+', '_', safe_name)
    safe_name = safe_name.strip('_.  ')
    if max_length > 0:
        safe_name = safe_name[:max_length]
    return safe_name or "unknown"


def get_project_root() -> Path:
    """Return the repository root for runtime-safe path helpers."""
    return Path(__file__).resolve().parents[2]


def ensure_data_path(*parts: str) -> Path:
    """Create and return a path rooted under the project's data directory."""
    path = get_project_root() / "data"
    for part in parts:
        path /= str(part)
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_probe_output_dir(project_name: str) -> Path:
    """Return a stable project folder for current probe outputs."""
    return ensure_data_path("outputs", "current", sanitize_for_path(project_name, max_length=120))


def ensure_report_output_dir(*parts: str) -> Path:
    """Return a stable folder for generated report or summary artifacts."""
    return ensure_data_path("outputs", "reports", *parts)


def ensure_channel_temp_project_dir(
    channel_name: str,
    project_name: str,
    bucket: str = "current",
) -> Path:
    """Return a stable temp_images folder for a channel/project pair."""
    base = get_project_root() / "data" / "temp_images" / channel_name / bucket
    base.mkdir(parents=True, exist_ok=True)
    target = base / sanitize_for_path(project_name, max_length=120)
    target.mkdir(parents=True, exist_ok=True)
    return target


def relocate_generated_image_dir(image_paths: Sequence[str], target_dir: Path) -> Path:
    """
    Move a generated scene-image directory into a stable target location.

    The image pipeline may emit into a transient folder. Probe tools use this
    helper to consolidate the whole directory, including `_motiontoon` bundles.
    """
    source_dir: Optional[Path] = None
    for raw_path in image_paths:
        if not raw_path:
            continue
        candidate = Path(str(raw_path))
        if candidate.exists():
            source_dir = candidate.resolve().parent
            break
    if source_dir is None:
        return target_dir

    resolved_target = target_dir.resolve()
    if source_dir == resolved_target:
        return resolved_target

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    shutil.move(str(source_dir), str(target_dir))
    return target_dir


def get_ffmpeg_path() -> str:
    """
    Resolve FFmpeg from config first, then environment, then known paths.

    The PATH fallback is allowed only when the discovered version is new enough
    for the filters used by this project.
    """
    for module_name in ("config.settings_v2", "config.settings"):
        try:
            import importlib

            mod = importlib.import_module(module_name)
            cfg = getattr(mod, "config", None)
            ffmpeg_path = getattr(cfg, "FFMPEG_PATH", "") if cfg else ""
            if ffmpeg_path and os.path.isfile(ffmpeg_path):
                return ffmpeg_path
        except Exception:
            pass

    env_path = os.environ.get("IMAGEIO_FFMPEG_EXE", "")
    if env_path and os.path.isfile(env_path):
        return env_path

    known_paths = [
        r"C:\ffmpeg8\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    for path in known_paths:
        if os.path.isfile(path):
            return path

    import shutil
    import subprocess

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        try:
            ver_out = subprocess.run(
                [system_ffmpeg, "-version"], capture_output=True, text=True, timeout=5
            ).stdout
            ver_match = re.search(r"ffmpeg version (\d+\.\d+)", ver_out)
            if ver_match:
                ver_str = ver_match.group(1)
                major = int(ver_str.split(".")[0])
                if major < 5:
                    logger.error(
                        "[FFmpeg] System PATH points to an unsupported legacy version "
                        f"({ver_str}). Configure FFMPEG_PATH to 8.0+."
                    )
                    raise FileNotFoundError(
                        f"FFmpeg {ver_str} is incompatible with this project. 8.0+ required."
                    )
                logger.warning(f"[FFmpeg] Falling back to system PATH: {system_ffmpeg} (v{ver_str})")
                return system_ffmpeg
        except FileNotFoundError:
            raise
        except Exception as e:
            logger.warning(f"[FFmpeg] Version check failed ({e}); using system PATH fallback")
            return system_ffmpeg

    logger.error("[FFmpeg] FFmpeg not found. config.FFMPEG_PATH must be configured.")
    return "ffmpeg"


def get_ffprobe_path() -> str:
    """Resolve ffprobe alongside the configured ffmpeg binary when possible."""
    ffmpeg = get_ffmpeg_path()
    if ffmpeg and ffmpeg != "ffmpeg":
        dirname = os.path.dirname(ffmpeg)
        basename = os.path.basename(ffmpeg).replace("ffmpeg", "ffprobe")
        ffprobe = os.path.join(dirname, basename)
        if os.path.isfile(ffprobe):
            return ffprobe
    return "ffprobe"


def parse_url_host_port(
    url: str,
    default_host: str = "127.0.0.1",
    default_port: int = 7860,
):
    """Parse host and port from a URL with safe defaults."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname or default_host
        port = parsed.port or default_port
        return host, port
    except Exception:
        return default_host, default_port


__all__ = [
    "ensure_channel_temp_project_dir",
    "ensure_data_path",
    "ensure_probe_output_dir",
    "ensure_report_output_dir",
    "get_project_root",
    "get_ffmpeg_path",
    "get_ffprobe_path",
    "parse_url_host_port",
    "relocate_generated_image_dir",
    "safe_print",
    "sanitize_for_path",
    "set_gui_log_callback",
]
