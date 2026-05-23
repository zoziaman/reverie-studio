from __future__ import annotations

import re
from typing import Any


_GEMINI_URL_KEY_RE = re.compile(r"([?&]key=)([^&\s]+)")
_GOOGLE_API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
_GOOGLE_ENV_ASSIGNMENT_RE = re.compile(
    r"\b((?:GEMINI|GOOGLE)_API_KEY\s*[:=]\s*)([^\s,;]+)",
    re.IGNORECASE,
)


def redact_sensitive_text(value: Any) -> str:
    """Return text with common Google/Gemini API key forms removed."""
    text = str(value or "")
    text = _GEMINI_URL_KEY_RE.sub(r"\1<redacted>", text)
    text = _GOOGLE_ENV_ASSIGNMENT_RE.sub(r"\1<redacted>", text)
    text = _GOOGLE_API_KEY_RE.sub("<redacted-google-api-key>", text)
    return text
