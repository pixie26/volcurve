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
    DUPLICATE_DATE = "DUPLICATE_DATE"
    NON_MONOTONIC_DATE = "NON_MONOTONIC_DATE"
    POSSIBLE_CORPORATE_ACTION = "POSSIBLE_CORPORATE_ACTION"
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
    target_strike: float
    returned_strike: float | None
    forward: float | None
    discount_factor: float | None  # zcCurve carries discount factors, not rates
    implied_vol: float | None  # decimal units (0.229 = 22.9%)
    source_timestamp: str | None
    quality_flags: list[QualityFlag]
