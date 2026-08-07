"""Convert internal decimal-domain results into stable public API contracts."""

from __future__ import annotations

import math
from collections import Counter

from app.clients.cortex.errors import CortexError, ErrorCode
from app.domain.disclosures import DISCLOSURES, LARGE_SURFACE_POINT_WARNING
from app.domain.observations import QualityFlag
from app.domain.requests import VolatilityRequest
from app.domain.responses import (
    ActivityEvent,
    CompareResponse,
    CompareSummary,
    Methodology,
    SeriesPoint,
    SourceInfo,
    SurfaceApiPoint,
    SurfaceApiSnapshot,
    SurfaceQualitySummary,
    SurfaceResponse,
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


def _percent(value: float | None) -> float | None:
    return None if value is None else value * 100.0


def _raw_percent(value: float | None) -> float | str | None:
    if value is None:
        return None
    if math.isfinite(value):
        return value * 100.0
    if math.isnan(value):
        return "NaN"
    return "Infinity" if value > 0 else "-Infinity"


def _source_info(client, request: VolatilityRequest, fetch_results, warmup_from) -> SourceInfo:
    statuses = list(dict.fromkeys(result.cache_status for result in fetch_results))
    cache_status = statuses[0] if len(statuses) == 1 else "mixed"
    request_ids = list(dict.fromkeys(result.correlation_id for result in fetch_results))
    return SourceInfo(
        provider="Cortex DataHub",
        apiVersion=client.api_version,
        instrumentCode=request.code,
        retrievedAt=max(result.retrieved_at for result in fetch_results),
        cacheStatus=cache_status,
        requestId=request_ids[0],
        requestIds=request_ids,
        warmupFrom=warmup_from,
    )


def _fetch_activity(fetch_results) -> list[ActivityEvent]:
    statuses = {result.cache_status for result in fetch_results}
    events = [
        ActivityEvent(
            code="REQUEST_VALIDATED",
            stage="validation",
            message="请求字段和坐标组合已通过本地严格校验。",
        )
    ]
    if "fixture" in statuses:
        events.append(
            ActivityEvent(
                code="FIXTURE_LOADED",
                stage="fetch",
                message="已加载脱敏离线 fixture；未调用 live API。",
            )
        )
    if "hit" in statuses:
        events.append(
            ActivityEvent(code="CACHE_HIT", stage="fetch", message="已使用校验通过的本地缓存。")
        )
    if "live" in statuses:
        events.extend(
            [
                ActivityEvent(
                    code="UPSTREAM_FETCH_STARTED",
                    stage="fetch",
                    message="已向数据源发起数据请求。",
                ),
                ActivityEvent(
                    code="UPSTREAM_FETCH_COMPLETED",
                    stage="fetch",
                    message="数据源数据请求已完成。",
                ),
            ]
        )
    events.extend(
        [
            ActivityEvent(
                code="SCHEMA_VALIDATED",
                stage="schema",
                message="上游响应已通过结构校验。",
            ),
            ActivityEvent(
                code="COORDINATES_RESOLVED",
                stage="normalization",
                message="返回坐标已按精确匹配规则标准化。",
            ),
        ]
    )
    return events


def build_compare_response(
    *, request_id: str, client, request: VolatilityRequest, execution: CompareExecution
) -> CompareResponse:
    analytics = execution.analytics
    if not execution.load.observations:
        # Methodology is read off the first observation, so an empty window would raise an
        # IndexError and surface as a 500. It is an ordinary "nothing here" answer instead.
        raise CortexError(ErrorCode.NO_DATA, "该日期区间内没有可用观测")
    first_observation = execution.load.observations[0]
    quality, quality_events = build_quality_contract(analytics.series)
    series = [
        SeriesPoint(
            date=point.date,
            spot=point.spot,
            forward=point.forward,
            rawImpliedVol=_raw_percent(point.raw_implied_vol),
            impliedVol=_percent(point.implied_vol),
            realizedVol=_percent(point.realized_vol),
            ivMinusRv=_percent(point.iv_minus_rv),
            ivDividedByRv=point.iv_divided_by_rv,
            qualityFlags=point.quality_flags,
        )
        for point in analytics.series
    ]
    raw_summary = analytics.summary
    summary = CompareSummary(
        latestMarketDate=raw_summary["latestMarketDate"],
        latestIvDate=raw_summary["latestIvDate"],
        latestIv=_percent(raw_summary["latestIv"]),
        latestComparableDate=raw_summary["latestComparableDate"],
        latestComparableIv=_percent(raw_summary["latestComparableIv"]),
        latestComparableRv=_percent(raw_summary["latestComparableRv"]),
        latestComparableSpread=_percent(raw_summary["latestComparableSpread"]),
        latestRv=_percent(raw_summary["latestRv"]),
        latestSpread=_percent(raw_summary["latestSpread"]),
        spreadPercentile=raw_summary["spreadPercentile"],
        spreadZScore=raw_summary["spreadZScore"],
        correlation=raw_summary["correlation"],
        observationCount=raw_summary["observationCount"],
    )
    activity = _fetch_activity(execution.load.fetch_results)
    activity.extend(quality_events)
    if not execution.load.forward_tail_complete:
        activity.append(
            ActivityEvent(
                code="FORWARD_RV_INCOMPLETE",
                stage="analytics",
                message="Forward RV 所需的未来有效价格不足，受影响窗口保持为空。",
                suggestedAction="等待更多市场日期可用，或缩短 RV window 后重试。",
            )
        )
    activity.append(
        ActivityEvent(
            code="ANALYTICS_COMPLETED",
            stage="analytics",
            message=f"已完成 {len(series)} 个展示日期的 IV/RV 分析。",
            affectedObservations=len(series),
        )
    )
    methodology = Methodology(
        maturity=first_observation.target_maturity,
        strikeConvention=first_observation.strike_rule,
        strike=first_observation.target_strike,
        ivLabel=iv_label(
            first_observation.target_maturity,
            first_observation.strike_rule,
            first_observation.target_strike,
        ),
        rvLabel=rv_label(execution.window_sessions, execution.alignment),
        rvWindowSessions=execution.window_sessions,
        rvAlignment=execution.alignment,
        rvFormula="stdev(log(S_t/S_t-1), ddof=1) × sqrt(252)",
        annualization=252,
        volUnits="percent",
        spotNote=(
            "Spot 为数据源原始未复权价格；RV 是 price-return RV，未做分红或公司行动调整。"
        ),
        corporateActionAdjustment="none",
    )
    return CompareResponse(
        requestId=request_id,
        series=series,
        summary=summary,
        methodology=methodology,
        source=_source_info(client, request, execution.load.fetch_results, analytics.warmup_from),
        dataQuality=quality,
        activity=activity,
        disclosures=list(DISCLOSURES),
    )


def build_surface_response(
    *,
    request_id: str,
    client,
    request: VolatilityRequest,
    snapshots: list[StandardSurfaceObservation],
    fetch_result,
) -> SurfaceResponse:
    point_flags: Counter[str] = Counter()
    snapshot_flags: Counter[str] = Counter()
    invalid_count = 0
    suspicious_count = 0
    usable_count = 0
    api_snapshots = []
    for snapshot in snapshots:
        snapshot_flags.update(flag.value for flag in snapshot.quality_flags if flag.value != "OK")
        api_points = []
        for point in snapshot.points:
            flags = [flag.value for flag in point.quality_flags]
            non_ok = set(flags) - {"OK"}
            point_flags.update(non_ok)
            invalid_count += bool(non_ok & _INVALID_IV_FLAGS)
            suspicious_count += QualityFlag.SUSPICIOUS_IV_EXTREME.value in non_ok
            usable_count += point.implied_vol is not None
            api_points.append(
                SurfaceApiPoint(
                    maturity=point.maturity,
                    strike=point.strike,
                    maturityIndex=point.maturity_index,
                    strikeIndex=point.strike_index,
                    rawImpliedVol=_raw_percent(point.raw_implied_vol),
                    impliedVol=_percent(point.implied_vol),
                    qualityFlags=flags,
                )
            )
        api_snapshots.append(
            SurfaceApiSnapshot(
                date=snapshot.date,
                spot=snapshot.spot,
                maturities=snapshot.maturities,
                strikes=snapshot.strikes,
                forwardCurve=snapshot.forward_curve,
                discountFactors=snapshot.discount_factors,
                points=api_points,
                sourceTime=snapshot.source_time,
                sourceTimezone=snapshot.source_timezone,
                sourceTimestamp=snapshot.source_timestamp,
                qualityFlags=[flag.value for flag in snapshot.quality_flags],
            )
        )
    counts = point_flags + snapshot_flags
    warning = None
    if invalid_count:
        warning = (
            f"数据源返回 {invalid_count} 个无效 IV surface 点；原值已保留，effective IV 已置空。"
        )
    point_count = sum(len(snapshot.points) for snapshot in snapshots)
    quality = SurfaceQualitySummary(
        status="WARNINGS" if counts else "OK",
        snapshotCount=len(snapshots),
        pointCount=point_count,
        usableIvCount=usable_count,
        invalidIvCount=invalid_count,
        suspiciousIvCount=suspicious_count,
        flagCounts=dict(sorted(counts.items())),
        warningBanner=warning,
        analyticsExclusionPolicy=(
            "rawImpliedVol 保留上游原值；非正或非有限 IV 的 impliedVol 置空，"
            "后续 smile/term-structure 统计必须排除。"
        ),
    )
    activity = _fetch_activity([fetch_result])
    if invalid_count:
        activity.append(
            ActivityEvent(
                code="INVALID_POINTS_EXCLUDED",
                stage="normalization",
                message=warning or "无效 surface 点已置空。",
                affectedObservations=invalid_count,
                suggestedAction="检查受影响日期和坐标，或改用另一组期限/strike 约定后重试。",
            )
        )
    if point_count > LARGE_SURFACE_POINT_WARNING:
        activity.append(
            ActivityEvent(
                code="LARGE_SURFACE_RESULT",
                stage="normalization",
                message=(f"Surface 包含 {point_count} 个点；结果未截断，浏览器处理可能较慢。"),
                affectedObservations=point_count,
                suggestedAction="缩小日期、expiry 或 strike 范围后重试。",
            )
        )
    activity.append(
        ActivityEvent(
            code="SURFACE_NORMALIZED",
            stage="normalization",
            message=f"已标准化 {len(snapshots)} 个日期的完整 volatility surface。",
            affectedObservations=len(snapshots),
        )
    )
    return SurfaceResponse(
        requestId=request_id,
        snapshots=api_snapshots,
        source=_source_info(client, request, [fetch_result], request.start_date),
        dataQuality=quality,
        activity=activity,
        disclosures=list(DISCLOSURES),
    )
