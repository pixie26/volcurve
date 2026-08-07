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
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from app.domain.disclosures import Disclosure
from app.domain.instruments import Instrument
from app.domain.observations import QualityFlag

if TYPE_CHECKING:
    from app.analytics.engine import SeriesEntry

STRIKE_RULE_LABELS = {
    "relative_to_forward": "K/F",
    "relative_to_spot_ref": "K/S",
    "fixed": "K",
    "delta": "Δ",
}

SPOT_NOTE = (
    "Spot 为数据源原始未复权价格；RV 是 price-return RV，未做分红或公司行动调整。"
    "大幅跳变只标记 RETURN_OUTLIER，不代表已确认公司行动。"
)


def iv_label(maturity: str, strike_rule: str, strike: float | str) -> str:
    convention = STRIKE_RULE_LABELS.get(strike_rule, strike_rule)
    if strike_rule == "fixed":
        assert isinstance(strike, (int, float))
        return f"{maturity} IV — K = {strike:g} (absolute)"
    if strike_rule == "delta":
        return f"{maturity} IV — Δ = {strike}"
    assert isinstance(strike, (int, float))
    return f"{maturity} IV — {convention} = {strike:g}%"


def rv_label(window_sessions: int, alignment: str) -> str:
    return f"RV {window_sessions} trading days ({alignment})"


class SeriesPoint(BaseModel):
    date: date
    spot: float | None
    forward: float | None
    rawImpliedVol: float | str | None  # percent; non-finite audit values use strings
    impliedVol: float | None  # percent
    realizedVol: float | None  # percent
    ivMinusRv: float | None  # vol points
    ivDividedByRv: float | None
    qualityFlags: list[str]


class CompareSummary(BaseModel):
    latestMarketDate: date | None
    latestIvDate: date | None
    latestIv: float | None
    latestComparableDate: date | None
    latestComparableIv: float | None
    latestComparableRv: float | None
    latestComparableSpread: float | None
    latestRv: float | None
    latestSpread: float | None
    spreadPercentile: float | None
    spreadZScore: float | None
    correlation: float | None
    observationCount: int


class Methodology(BaseModel):
    maturity: str
    strikeConvention: str
    strike: float | str
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
    requestIds: list[str]
    warmupFrom: date


class DataQualitySummary(BaseModel):
    status: Literal["OK", "WARNINGS"]
    observationCount: int
    usableIvCount: int
    invalidIvCount: int
    invalidIvDateFrom: date | None
    invalidIvDateTo: date | None
    suspiciousIvCount: int
    flagCounts: dict[str, int]
    warningBanner: str | None
    analyticsExclusionPolicy: str


class ActivityEvent(BaseModel):
    code: str
    stage: str
    message: str
    affectedObservations: int = 0
    suggestedAction: str | None = None


_INVALID_IV_FLAGS = {
    QualityFlag.INVALID_IV_ZERO.value,
    QualityFlag.INVALID_IV_NEGATIVE.value,
    QualityFlag.INVALID_IV_NON_FINITE.value,
}


def build_quality_contract(
    series: list[SeriesEntry],
) -> tuple[DataQualitySummary, list[ActivityEvent]]:
    """Build the user-visible quality summary and low-sensitivity activity event."""
    flag_counts: dict[str, int] = {}
    invalid_dates: list[date] = []
    usable_iv_count = 0
    suspicious_count = 0
    for point in series:
        usable_iv_count += point.implied_vol is not None
        point_flags = set(point.quality_flags) - {QualityFlag.OK.value}
        for flag in point_flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
        if point_flags & _INVALID_IV_FLAGS:
            invalid_dates.append(point.date)
        if QualityFlag.SUSPICIOUS_IV_EXTREME.value in point_flags:
            suspicious_count += 1

    invalid_count = len(invalid_dates)
    status = "WARNINGS" if flag_counts else "OK"
    warning = None
    events: list[ActivityEvent] = []
    if invalid_count:
        warning = f"数据源返回 {invalid_count} 个无效 IV 观测；原值已保留，这些点已从统计计算中排除。"
        events.append(
            ActivityEvent(
                code="INVALID_POINTS_EXCLUDED",
                stage="normalization",
                message=warning,
                affectedObservations=invalid_count,
                suggestedAction="检查受影响日期和坐标，或改用另一组期限/strike 约定后重试。",
            )
        )

    summary = DataQualitySummary(
        status=status,
        observationCount=len(series),
        usableIvCount=usable_iv_count,
        invalidIvCount=invalid_count,
        invalidIvDateFrom=min(invalid_dates) if invalid_dates else None,
        invalidIvDateTo=max(invalid_dates) if invalid_dates else None,
        suspiciousIvCount=suspicious_count,
        flagCounts=flag_counts,
        warningBanner=warning,
        analyticsExclusionPolicy=(
            "rawImpliedVol 保留上游原值；非正或非有限 IV 的 impliedVol 置空，"
            "不参与 spread、ratio、percentile、z-score 或 correlation。"
        ),
    )
    return summary, events



class UpstreamRequestAudit(BaseModel):
    method: str = "POST"
    endpoint: str = "/v1/implied-volatility"
    disposition: str
    sentToUpstream: bool
    correlationId: str
    body: dict[str, object]


class RequestAudit(BaseModel):
    userRequestBody: dict[str, object]
    upstreamRequests: list[UpstreamRequestAudit] = Field(default_factory=list)


class DataIssue(BaseModel):
    severity: Literal["warning", "info"]
    code: str
    instrumentCode: str
    date: date
    coordinate: str
    rawImpliedVol: float | str | None = None
    impliedVol: float | None = None
    realizedVol: float | None = None
    spot: float | None = None
    forward: float | None = None
    action: str


class CompareResponse(BaseModel):
    requestId: str
    series: list[SeriesPoint]
    summary: CompareSummary
    methodology: Methodology
    source: SourceInfo
    dataQuality: DataQualitySummary
    activity: list[ActivityEvent]
    disclosures: list[Disclosure]
    requestAudit: RequestAudit | None = None
    issues: list[DataIssue] = Field(default_factory=list)


class InstrumentSearchResponse(BaseModel):
    query: str
    instrumentType: str
    matchedCount: int
    returnedCount: int
    hasMore: bool
    instruments: list[Instrument]
    activity: list[ActivityEvent]


class SurfaceApiPoint(BaseModel):
    maturity: str
    strike: str
    maturityIndex: int
    strikeIndex: int
    rawImpliedVol: float | str | None
    impliedVol: float | None
    qualityFlags: list[str]


class SurfaceApiSnapshot(BaseModel):
    date: date
    spot: float | None
    maturities: list[str]
    strikes: list[str]
    forwardCurve: list[float | None]
    discountFactors: list[float | None]
    points: list[SurfaceApiPoint]
    sourceTime: str | None
    sourceTimezone: str | None
    sourceTimestamp: str | None
    qualityFlags: list[str]


class SurfaceQualitySummary(BaseModel):
    status: Literal["OK", "WARNINGS"]
    snapshotCount: int
    pointCount: int
    usableIvCount: int
    invalidIvCount: int
    suspiciousIvCount: int
    flagCounts: dict[str, int]
    warningBanner: str | None
    analyticsExclusionPolicy: str


class SurfaceResponse(BaseModel):
    requestId: str
    snapshots: list[SurfaceApiSnapshot]
    source: SourceInfo
    dataQuality: SurfaceQualitySummary
    activity: list[ActivityEvent]
    disclosures: list[Disclosure]


class ErrorResponse(BaseModel):
    requestId: str
    code: str
    message: str
    stage: str
    affectedObservations: int = 0
    suggestedAction: str
    suggestedActionSource: Literal["upstream", "local"] = "local"
    upstreamCode: str | None = None
    upstreamMessage: str | None = None
    upstreamSuggestedAction: str | None = None
