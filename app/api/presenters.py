"""Convert internal decimal-domain results into stable public API contracts."""

from __future__ import annotations

import math
from collections import Counter

from app.clients.cortex.errors import CortexError, ErrorCode
from app.clients.cortex.serializers import serialize_volatility_request
from app.domain.disclosures import DISCLOSURES, LARGE_SURFACE_POINT_WARNING
from app.domain.observations import QualityFlag
from app.domain.requests import VolatilityRequest
from app.domain.responses import (
    ActivityEvent,
    CompareResponse,
    CompareSummary,
    DataIssue,
    Methodology,
    RequestAudit,
    SeriesPoint,
    SourceInfo,
    SurfaceApiPoint,
    SurfaceApiSnapshot,
    SurfaceQualitySummary,
    SurfaceResponse,
    UpstreamRequestAudit,
    build_quality_contract,
    iv_label,
    rv_label,
)
from app.domain.surfaces import StandardSurfaceObservation
from app.services.compare import CompareExecution

_INVALID_IV_FLAGS = {
    QualityFlag.INVALID_IV_ZERO.value,
    QualityFlag.INVALID_IV_NEGATIVE.value,
    QualityFlag.INVALID_IV_NON_FINITE.value,
}


def build_compare_response(execution: CompareExecution) -> CompareResponse:
    request = execution.request
    observations = execution.load.observations
    quality_contract = build_quality_contract(observations)
    series = []
    if execution.analytics is not None:
        series = _series_points(execution.analytics.series)
    return CompareResponse(
        requestId=execution.request_id,
        summary=CompareSummary(
            instrument=request.code,
            startDate=request.start_date,
            endDate=request.end_date,
            ivLabel=iv_label(request),
            rvLabel=rv_label(request),
            observationCount=len(observations),
            analyticsPointCount=len(series),
        ),
        source=_source_info(execution),
        requestAudit=_request_audit(execution),
        series=series,
        dataQuality=quality_contract,
        methodology=_methodology(request),
        activity=execution.activity,
        disclosures=DISCLOSURES,
    )


def build_surface_response(
    *,
    request: VolatilityRequest,
    request_id: str,
    snapshots: list[StandardSurfaceObservation],
    source: SourceInfo,
    request_audit: RequestAudit,
    activity: list[ActivityEvent],
) -> SurfaceResponse:
    public_snapshots = [_surface_snapshot(snapshot) for snapshot in snapshots]
    total_points = sum(len(snapshot.points) for snapshot in snapshots)
    effective_points = sum(
        1
        for snapshot in snapshots
        for point in snapshot.points
        if point.implied_vol is not None
    )
    return SurfaceResponse(
        requestId=request_id,
        summary=SurfaceQualitySummary(
            snapshotCount=len(public_snapshots),
            pointCount=total_points,
            effectivePointCount=effective_points,
        ),
        source=source,
        requestAudit=request_audit,
        snapshots=public_snapshots,
        dataQuality=_surface_quality(snapshots),
        methodology=_methodology(request),
        activity=activity,
        disclosures=DISCLOSURES,
    )


def _surface_snapshot(snapshot: StandardSurfaceObservation) -> SurfaceApiSnapshot:
    points = [
        SurfaceApiPoint(
            maturity=point.maturity,
            strike=point.strike,
            forward=point.forward,
            discount=point.discount,
            rawImpliedVol=_finite_or_none(point.raw_implied_vol),
            impliedVol=_finite_or_none(point.implied_vol),
            qualityFlags=point.quality_flags,
        )
        for point in snapshot.points
    ]
    return SurfaceApiSnapshot(
        date=snapshot.date,
        instrument=snapshot.instrument,
        spot=snapshot.spot,
        points=points,
    )


def _surface_quality(snapshots: list[StandardSurfaceObservation]):
    flags = Counter(
        flag
        for snapshot in snapshots
        for point in snapshot.points
        for flag in point.quality_flags
    )
    issue_count = sum(flags.values())
    if issue_count == 0:
        return build_quality_contract([])

    issues = []
    for flag, count in flags.most_common():
        severity = "warning"
        if flag in _INVALID_IV_FLAGS:
            severity = "error"
        issues.append(
            DataIssue(
                code=flag,
                severity=severity,
                count=count,
                message=_quality_message(flag),
            )
        )
    return build_quality_contract([], issues=issues)


def _quality_message(flag: str) -> str:
    messages = {
        QualityFlag.INVALID_IV_ZERO.value: "IV 为 0，保留 raw 值但 effective IV 置空。",
        QualityFlag.INVALID_IV_NEGATIVE.value: "IV 为负，保留 raw 值但 effective IV 置空。",
        QualityFlag.INVALID_IV_NON_FINITE.value: "IV 非有限值，effective IV 置空。",
        QualityFlag.SUSPICIOUS_IV_GT_500_PCT.value: "IV 大于 500%，保留并标记 suspicious。",
    }
    return messages.get(flag, flag)


def _finite_or_none(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _series_points(series) -> list[SeriesPoint]:
    return [
        SeriesPoint(
            date=point.date,
            spot=point.spot,
            iv=point.iv,
            rv=point.rv,
            spread=point.spread,
            qualityFlags=point.quality_flags,
        )
        for point in series
    ]


def _source_info(execution: CompareExecution) -> SourceInfo:
    source = execution.load.source
    return SourceInfo(
        provider=source.provider,
        endpoint=source.endpoint,
        retrievedAt=source.retrieved_at,
        fromCache=source.from_cache,
        requestCount=source.request_count,
    )


def _request_audit(execution: CompareExecution) -> RequestAudit:
    request = execution.request
    wire = serialize_volatility_request(request)
    upstream = [
        UpstreamRequestAudit(
            endpoint=item.endpoint,
            body=item.body,
            retrievedAt=item.retrieved_at,
            requestId=item.request_id,
            correlationId=item.correlation_id,
            fromCache=item.from_cache,
        )
        for item in execution.load.upstream_requests
    ]
    return RequestAudit(
        requestedCoordinate=request.requested_coordinate,
        effectiveFetchRange=execution.load.effective_fetch_range,
        source=execution.load.source.provider,
        provider=execution.load.source.provider,
        api=execution.load.source.endpoint,
        retrievedAt=execution.load.source.retrieved_at,
        requestId=execution.request_id,
        wireRequest=wire,
        upstreamRequests=upstream,
    )


def _methodology(request: VolatilityRequest) -> Methodology:
    return Methodology(
        ivRule="effective IV is the provider value after invalid raw values are nulled; no fitting or smoothing",
        rvRule="close-to-close log-return realized volatility, ddof=1, annualized by sqrt(252)",
        missingDataRule="missing observations stay missing; no nearest-coordinate substitution",
        forwardRvRule="forward RV requires future sessions beyond the display end date",
        largeSurfaceWarning=LARGE_SURFACE_POINT_WARNING,
        requestRule=request.requested_coordinate,
    )
