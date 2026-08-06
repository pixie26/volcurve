"""API response models and labels.

Labeling rules (agreed):
- IV: "3M IV — K/F = 100%" / "3M IV — K/S = 100%" / fixed: absolute strike;
  never a bare "100% strike".
- RV: "RV 63 trading days (trailing)".
- Spot: raw, unadjusted price (per user-confirmed BNP convention) — the
  frontend must always show this note.
- Vols are returned in PERCENT units (22.9 = 22.9%); conversion happens
  only at this API boundary. Storage keeps raw decimals.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

STRIKE_RULE_LABELS = {
    "relative_to_forward": "K/F",
    "relative_to_spot_ref": "K/S",
    "fixed": "K",
    "delta": "Δ",
}

SPOT_NOTE = "Spot 为原始价(未复权);RV 由未复权价格计算,分红除息日可能出现小幅失真(已标记 POSSIBLE_CORPORATE_ACTION)"


def iv_label(maturity: str, strike_rule: str, strike: float) -> str:
    convention = STRIKE_RULE_LABELS.get(strike_rule, strike_rule)
    if strike_rule == "fixed":
        return f"{maturity} IV — K = {strike:g} (absolute)"
    if strike_rule == "delta":
        return f"{maturity} IV — Δ = {strike:g}"
    return f"{maturity} IV — {convention} = {strike:g}%"


def rv_label(window_sessions: int, alignment: str) -> str:
    return f"RV {window_sessions} trading days ({alignment})"


class SeriesPoint(BaseModel):
    date: date
    spot: float | None
    forward: float | None
    impliedVol: float | None  # percent
    realizedVol: float | None  # percent
    ivMinusRv: float | None  # vol points
    ivDividedByRv: float | None
    qualityFlags: list[str]


class CompareSummary(BaseModel):
    latestIv: float | None
    latestRv: float | None
    latestSpread: float | None
    spreadPercentile: float | None
    spreadZScore: float | None
    correlation: float | None
    observationCount: int


class Methodology(BaseModel):
    maturity: str
    strikeConvention: str
    strike: float
    ivLabel: str
    rvLabel: str
    rvWindowSessions: int
    rvAlignment: str
    rvFormula: str
    annualization: int
    volUnits: str
    spotNote: str
    corporateActionAdjustment: str


class SourceInfo(BaseModel):
    provider: str
    apiVersion: str
    instrumentCode: str
    retrievedAt: datetime
    cacheStatus: str
    requestId: str
    warmupFrom: date


class CompareResponse(BaseModel):
    requestId: str
    series: list[SeriesPoint]
    summary: CompareSummary
    methodology: Methodology
    source: SourceInfo
