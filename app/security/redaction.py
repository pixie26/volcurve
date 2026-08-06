"""Secret redaction helpers.

Applied to anything that may reach logs, error messages, or the browser:
client credentials and bearer tokens are replaced with a fixed mask.
"""

from __future__ import annotations

import re

_MASK = "[REDACTED]"
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\r\n\t\"']+")

_extra_secrets: list[str] = []


def register_secret(value: str | None) -> None:
    if value and value not in _extra_secrets:
        _extra_secrets.append(value)


def redact(text: str) -> str:
    out = _BEARER_RE.sub(f"Bearer {_MASK}", text)
    out = _WINDOWS_PATH_RE.sub(_MASK, out)
    for secret in _extra_secrets:
        out = out.replace(secret, _MASK)
    return out
