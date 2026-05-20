"""
Pipeline-specific helpers plus compatibility re-exports for shared runtime utils.
"""
import logging
import os
import random
import time
from typing import Optional

from utils.runtime_utils import (
    get_ffmpeg_path,
    get_ffprobe_path,
    parse_url_host_port,
    safe_print,
    sanitize_for_path,
    set_gui_log_callback,
)

try:
    from utils.logger import get_logger
    logger = get_logger("pipeline.utils")
except ImportError:
    logger = logging.getLogger("pipeline.utils")


# Exception classes that are safe to retry automatically.
RETRYABLE_NETWORK = (
    ConnectionError,
    TimeoutError,
    OSError,
)

_requests_retryable = None


def _get_requests_retryable() -> tuple:
    """Return retryable requests exceptions lazily."""
    global _requests_retryable
    if _requests_retryable is None:
        try:
            import requests.exceptions

            _requests_retryable = (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            )
        except ImportError:
            _requests_retryable = ()
    return _requests_retryable


def retry_api_call(
    func,
    *args,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    retryable_exceptions: Optional[tuple] = None,
    context: str = "API",
    **kwargs,
):
    """
    Retry a network/API call with exponential backoff and jitter.

    Non-retryable exceptions are raised immediately.
    """
    if retryable_exceptions is None:
        retryable_exceptions = RETRYABLE_NETWORK + _get_requests_retryable()

    last_exc = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except retryable_exceptions as e:
            last_exc = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                delay = delay * (0.5 + random.random())
                logger.warning(
                    f"[{context}] retry {attempt + 1}/{max_retries} after {delay:.1f}s: "
                    f"{type(e).__name__}"
                )
                time.sleep(delay)
            else:
                logger.error(f"[{context}] failed after {max_retries} attempts: {e}")
        except Exception as e:
            logger.error(f"[{context}] fatal error without retry: {e}")
            raise

    raise last_exc


def ensure_dir(path: str) -> str:
    """Create a directory if missing and return the same path."""
    os.makedirs(path, exist_ok=True)
    return path


__all__ = [
    "ensure_dir",
    "get_ffmpeg_path",
    "get_ffprobe_path",
    "parse_url_host_port",
    "retry_api_call",
    "safe_print",
    "sanitize_for_path",
    "set_gui_log_callback",
]
