from __future__ import annotations

import re
from typing import Any


_GEMINI_URL_KEY_RE = re.compile(r"([?&]key=)([^&\s]+)")
_GOOGLE_API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
_GOOGLE_ENV_ASSIGNMENT_RE = re.compile(
    r"\b((?:GEMINI|GOOGLE)_API_KEY\s*[:=]\s*)([^\s,;]+)",
    re.IGNORECASE,
)
_GENERIC_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b([A-Z0-9_]*(?:API[_-]?KEY|ACCESS[_-]?KEY|TOKEN|SECRET|PASSWORD|WEBHOOK(?:_URL)?)[A-Z0-9_]*\s*[:=]\s*)([^\s,;]+)",
    re.IGNORECASE,
)
_TOKEN_PATTERNS = (
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "<redacted-openai-key>"),
    (re.compile(r"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), "<redacted-github-token>"),
    (re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"), "<redacted-aws-access-key>"),
    (re.compile(r"(?:sk|rk)_live_[A-Za-z0-9]{16,}"), "<redacted-stripe-live-key>"),
    (re.compile(r"hf_[A-Za-z0-9]{20,}"), "<redacted-huggingface-token>"),
    (re.compile(r"npm_[A-Za-z0-9]{20,}"), "<redacted-npm-token>"),
    (re.compile(r"ya29\.[A-Za-z0-9_-]+"), "<redacted-google-oauth-token>"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"), "<redacted-slack-token>"),
    (
        re.compile(r"https://discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]{40,}"),
        "<redacted-discord-webhook>",
    ),
    (re.compile(r"bot[0-9]{6,}:[A-Za-z0-9_-]{30,}"), "<redacted-telegram-bot-token>"),
)


def redact_sensitive_text(value: Any) -> str:
    """Return text with public-release credential tokens removed."""
    text = str(value or "")
    text = _GEMINI_URL_KEY_RE.sub(r"\1<redacted>", text)
    text = _GOOGLE_ENV_ASSIGNMENT_RE.sub(r"\1<redacted>", text)
    text = _GOOGLE_API_KEY_RE.sub("<redacted-google-api-key>", text)
    for pattern, replacement in _TOKEN_PATTERNS:
        text = pattern.sub(replacement, text)
    text = _GENERIC_SECRET_ASSIGNMENT_RE.sub(r"\1<redacted>", text)
    return text
