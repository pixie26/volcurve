"""Pydantic models for validating raw Cortex API responses (schema guard)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SurfaceEntry(BaseModel):
    """One date of an implied-volatility response.

    Fields verified against live API 2026-08-06 (probe C):
    - matrix orientation: rows = maturities, cols = strikes
    - implied vol units: decimal (0.229 = 22.9%)
    - zcCurve: discount factors (3M ≈ 0.9902), not zero rates
    - time/timeZone may be null
    """

    model_config = ConfigDict(extra="allow")

    date: str
    time: str | None = None
    timeZone: str | None = None
    code: str | None = None
    maturityRule: str | None = None
    strikeRule: str | None = None
    volatilityConvention: str | None = None
    spot: float | None = None
    maturities: list[str] = Field(default_factory=list)
    strikes: list[str] = Field(default_factory=list)
    forwardCurve: list[float | None] = Field(default_factory=list)
    zcCurve: list[float | None] = Field(default_factory=list)
    matrix: list[list[float | None]] = Field(default_factory=list)
    vector: list[float | None] | None = None

    @field_validator("date")
    @classmethod
    def date_format(cls, v: str) -> str:
        from datetime import date as date_type

        date_type.fromisoformat(v)  # raises if not ISO
        return v
