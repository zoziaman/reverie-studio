import io
import os
import sys


def configure_utf8_stdio():
    """Windows 콘솔 인코딩을 UTF-8로 맞춘다.

    pytest 캡처 스트림 위에서는 re-wrap을 하지 않는다.
    """
    if sys.platform != "win32":
        return
    if os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules:
        return

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        if type(stream).__module__.startswith("_pytest."):
            continue

        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
                continue
        except Exception:
            pass

        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            continue

        try:
            setattr(sys, name, io.TextIOWrapper(buffer, encoding="utf-8", errors="replace"))
        except Exception:
            pass
