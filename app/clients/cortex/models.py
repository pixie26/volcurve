"""Pydantic models for validating raw Cortex API responses (schema guard)."""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class SurfaceEntry(BaseModel):
    """One date of an implied-volatility response.

    Fields verified against live API 2026-08-06 (probe C):
    - matrix orientation: rows = maturities, cols = strikes
    - implied vol units: decimal (0.229 = 22.9%)
    - zcCurve: discount factors (3M ≈ 0.9902), not zero rates
    - time/timeZone may be null
    """

    date: str
    time: str | None = None
    timeZone: str | None = None
    code: str | None = None
    maturityRule: str | None = None
    strikeRule: str | None = None
    volatilityConvention: str | None = None
    spot: float | None = None
    maturities: list[str] = []
    strikes: list[str] = []
    forwardCurve: list[float | None] = []
    zcCurve: list[float | None] = []
    matrix: list[list[float | None]] = []
    vector: list[float | None] | None = None

    @field_validator("date")
    @classmethod
    def date_format(cls, v: str) -> str:
        from datetime import date as date_type

        date_type.fromisoformat(v)  # raises if not ISO
        return v
