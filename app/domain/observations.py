"""Standardized observation model and data-quality flags."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel


class QualityFlag(str, Enum):
    OK = "OK"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    MISSING_SPOT = "MISSING_SPOT"
    MISSING_IV = "MISSING_IV"
    MISSING_FORWARD = "MISSING_FORWARD"
    MATURITY_MISMATCH = "MATURITY_MISMATCH"
    STRIKE_MISMATCH = "STRIKE_MISMATCH"
    DUPLICATE_IDENTICAL_REMOVED = "DUPLICATE_IDENTICAL_REMOVED"
    SOURCE_ORDER_CORRECTED = "SOURCE_ORDER_CORRECTED"
    INVALID_IV_ZERO = "INVALID_IV_ZERO"
    INVALID_IV_NEGATIVE = "INVALID_IV_NEGATIVE"
    INVALID_IV_NON_FINITE = "INVALID_IV_NON_FINITE"
    SUSPICIOUS_IV_EXTREME = "SUSPICIOUS_IV_EXTREME"
    RETURN_OUTLIER = "RETURN_OUTLIER"
    STALE_DATA = "STALE_DATA"
    SCHEMA_WARNING = "SCHEMA_WARNING"
    SNAPSHOT_TIME_MISSING = "SNAPSHOT_TIME_MISSING"


class StandardObservation(BaseModel):
    """One date's standardized implied-vol observation (plan section 7.4)."""

    date: date
    instrument_code: str
    spot: float | None
    target_maturity: str
    returned_maturity: str | None
    strike_rule: str
    target_strike: float | str
    returned_strike: float | str | None
    forward: float | None
    discount_factor: float | None  # zcCurve carries discount factors, not rates
    raw_implied_vol: float | None  # verbatim BNP value, retained for audit
    implied_vol: float | None  # usable decimal value; non-positive raw values become null
    source_time: str | None = None
    source_timezone: str | None = None
    source_timestamp: str | None = None
    quality_flags: list[QualityFlag]
