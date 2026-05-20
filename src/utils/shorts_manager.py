import logging
import os
import subprocess
from typing import Any, Dict, Iterable, List, Optional

from utils.runtime_utils import get_ffmpeg_path, sanitize_for_path

logger = logging.getLogger(__name__)


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _parse_tags(raw_tags: Any) -> List[str]:
    if isinstance(raw_tags, list):
        items = raw_tags
    elif isinstance(raw_tags, str):
        items = raw_tags.split(",")
    else:
        items = []

    seen = set()
    result: List[str] = []
    for item in items:
        text = str(item).strip().lstrip("#")
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def ensure_shorts_title(title: str, fallback_text: str = "") -> str:
    base = (title or fallback_text or "지금 밝혀진 진실").strip()
    if "#shorts" not in base.lower():
        base = f"{base} #Shorts"
    return base[:70].rstrip()


def normalize_shorts_plan(
    shorts_raw: Any,
    *,
    topic: str = "",
    hook: str = "",
    cold_open: Optional[List[Dict[str, Any]]] = None,
    tags: Any = None,
) -> Dict[str, Any]:
    cold_open = cold_open or []
    base_tags = _parse_tags(tags)

    hook_line = ""
    for turn in cold_open:
        if turn.get("_is_bridge"):
            continue
        text = str(turn.get("text", "")).strip()
        if text:
            hook_line = text
            break
    if not hook_line:
        hook_line = (hook or topic or "").strip()

    data = shorts_raw if isinstance(shorts_raw, dict) else {}
    auto_enabled = bool(hook_line)
    enabled = _to_bool(data.get("enabled"), default=auto_enabled) if data else auto_enabled

    duration_sec = data.get("duration_sec", 35)
    try:
        duration_sec = int(duration_sec)
    except Exception:
        duration_sec = 35
    duration_sec = max(20, min(duration_sec, 58))

    start_sec = data.get("start_sec", 0)
    try:
        start_sec = max(0, float(start_sec))
    except Exception:
        start_sec = 0.0

    shorts_tags = _parse_tags(data.get("tags", base_tags))
    if "shorts" not in {tag.lower() for tag in shorts_tags}:
        shorts_tags.append("shorts")

    title = ensure_shorts_title(str(data.get("title", "")).strip(), hook_line or topic)
    description = str(data.get("description", "")).strip()
    if not description:
        description = f"{hook_line or topic}\n\n#Shorts"

    return {
        "enabled": enabled,
        "title": title,
        "hook_line": str(data.get("hook_line", "")).strip() or hook_line,
        "description": description,
        "tags": shorts_tags,
        "duration_sec": duration_sec,
        "start_sec": start_sec,
        "upload_with_main": _to_bool(data.get("upload_with_main"), default=True),
    }


def build_shorts_variant(
    video_path: str,
    *,
    output_dir: str,
    project_name: str,
    duration_sec: int = 35,
    start_sec: float = 0.0,
) -> str:
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"video not found: {video_path}")

    os.makedirs(output_dir, exist_ok=True)
    safe_name = sanitize_for_path(project_name or "shorts")
    output_path = os.path.join(output_dir, f"{safe_name}_shorts.mp4")
    ffmpeg = get_ffmpeg_path()

    filter_complex = (
        "split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:10[bg];"
        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]"
    )

    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start_sec:.2f}",
        "-i",
        video_path,
        "-t",
        str(max(20, min(int(duration_sec), 58))),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        output_path,
    ]

    logger.info("[Shorts] rendering vertical variant: %s", output_path)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        logger.error("[Shorts] ffmpeg failed: %s", result.stderr[-800:])
        raise RuntimeError("failed to build shorts variant")

    return output_path


__all__ = [
    "build_shorts_variant",
    "ensure_shorts_title",
    "normalize_shorts_plan",
]
