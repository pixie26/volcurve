"""Normalized error taxonomy.

These codes are the only error surface shown to the browser; upstream BNP
responses, tokens, headers and stack traces must never leak into them.
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    ENTITLEMENT_DENIED = "ENTITLEMENT_DENIED"
    INSTRUMENT_NOT_FOUND = "INSTRUMENT_NOT_FOUND"
    INVALID_REQUEST = "INVALID_REQUEST"
    UPSTREAM_RATE_LIMITED = "UPSTREAM_RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    NO_DATA = "NO_DATA"
    SCHEMA_CHANGED = "SCHEMA_CHANGED"
    CALCULATION_FAILED = "CALCULATION_FAILED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


class CortexError(Exception):
    """Upstream call failed; carries a normalized, redacted code + message."""

    def __init__(self, code: ErrorCode, message: str, *, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def to_dict(self) -> dict:
        return {"error": self.code.value, "message": self.message}
