"""Normalized multi-coordinate volatility-surface contracts."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.domain.observations import QualityFlag


class SurfacePoint(BaseModel):
    maturity: str
    strike: str
    maturity_index: int
    strike_index: int
    raw_implied_vol: float | None
    implied_vol: float | None
    quality_flags: list[QualityFlag]


class StandardSurfaceObservation(BaseModel):
    date: date
    instrument_code: str
    maturity_rule: str
    strike_rule: str
    volatility_convention: str
    spot: float | None
    maturities: list[str]
    strikes: list[str]
    forward_curve: list[float | None]
    discount_factors: list[float | None]
    points: list[SurfacePoint]
    source_time: str | None = None
    source_timezone: str | None = None
    source_timestamp: str | None = None
    quality_flags: list[QualityFlag]
