"""Cortex volatility payload validation and multi-mode normalization.

Matrix orientation is defined by OpenAPI 1.60.0 and confirmed by the existing
live sliding-moneyness probe: rows are maturities and columns are strikes.
Coordinates are always resolved from returned axes; no mode reads fields that
belong to another request combination and no nearest-coordinate substitution is
performed.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date as date_type

from pydantic import ValidationError

from app.clients.cortex.errors import CortexError, ErrorCode
from app.clients.cortex.models import SurfaceEntry
from app.domain.disclosures import SUSPICIOUS_IV_THRESHOLD_DECIMAL
from app.domain.observations import QualityFlag, StandardObservation
from app.domain.requests import (
    DELTA_CODES,
    DELTA_MATURITIES,
    SLIDING_MATURITIES,
    FixedStrikeRequest,
    SlidingDeltaRequest,
    SlidingMoneynessRequest,
    VolatilityRequest,
)
from app.domain.surfaces import StandardSurfaceObservation, SurfacePoint

_STRIKE_TOL = 1e-9


@dataclass(frozen=True)
class CanonicalSurface:
    """Schema-validated, date-ordered payload ready for normalization."""

    entries: list[SurfaceEntry]
    duplicate_dates: set[str]
    order_corrected: bool


def _without_ok(flags: list[QualityFlag]) -> list[QualityFlag]:
    return [flag for flag in flags if flag != QualityFlag.OK]


def _with_ok_if_empty(flags: list[QualityFlag]) -> list[QualityFlag]:
    deduplicated = list(dict.fromkeys(_without_ok(flags)))
    return deduplicated or [QualityFlag.OK]


def _delta_domain(value: str) -> str:
    return value.strip().lower().replace("_", ".")


def _float_axis(value: str, *, label: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise CortexError(ErrorCode.SCHEMA_CHANGED, f"{label} 轴包含非数值坐标: {value}") from exc
    if not math.isfinite(parsed):
        raise CortexError(ErrorCode.SCHEMA_CHANGED, f"{label} 轴包含非有限坐标: {value}")
    return parsed


def canonicalize_surface(payload: list) -> CanonicalSurface:
    """Validate top-level entries, sort dates, and resolve exact duplicates."""
    if not isinstance(payload, list):
        raise CortexError(ErrorCode.INVALID_SCHEMA, "implied-volatility 响应不是数组")
    if not payload:
        raise CortexError(ErrorCode.NO_DATA, "implied-volatility 返回空结果")

    try:
        entries = [SurfaceEntry.model_validate(raw) for raw in payload]
    except ValidationError as exc:
        raise CortexError(ErrorCode.INVALID_SCHEMA, "implied-volatility 响应结构校验失败") from exc

    source_dates = [entry.date for entry in entries]
    order_corrected = source_dates != sorted(source_dates)
    grouped: dict[str, list[SurfaceEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.date, []).append(entry)

    duplicate_dates: set[str] = set()
    canonical: list[SurfaceEntry] = []
    for business_date in sorted(grouped):
        candidates = grouped[business_date]
        if len(candidates) == 1:
            canonical.append(candidates[0])
            continue
        fingerprints = {
            json.dumps(item.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            for item in candidates
        }
        if len(fingerprints) != 1:
            raise CortexError(
                ErrorCode.AMBIGUOUS_DUPLICATE_DATE,
                f"同一业务日期存在冲突观测: {business_date}",
            )
        duplicate_dates.add(business_date)
        canonical.append(candidates[0])
    return CanonicalSurface(canonical, duplicate_dates, order_corrected)


def _entry_matrix(entry: SurfaceEntry, request: VolatilityRequest) -> list[list[float | None]]:
    rows_expected = len(entry.maturities)
    cols_expected = len(entry.strikes)
    if not rows_expected or not cols_expected:
        # Fixed/listed exact coordinates may be unavailable on part of an RV
        # warm-up range. BNP represents those dates with an empty axis and no
        # IV values; that is missing data, not a schema change. Non-empty values
        # with an empty axis remain structurally invalid.
        matrix_has_values = any(row for row in entry.matrix)
        vector_has_values = bool(entry.vector)
        if matrix_has_values or vector_has_values:
            raise CortexError(ErrorCode.SCHEMA_CHANGED, "空 surface 轴包含无法定位的 IV 值")
        return [[] for _ in entry.maturities]
    if request.layout == "matrix":
        matrix = entry.matrix
        rows = len(matrix)
        cols = len(matrix[0]) if rows else 0
        if (
            rows != rows_expected
            or cols != cols_expected
            or any(len(row) != cols for row in matrix)
        ):
            raise CortexError(
                ErrorCode.SCHEMA_CHANGED,
                f"matrix 维度异常: {rows}x{cols}, 轴为 {rows_expected}x{cols_expected}",
            )
        return matrix

    vector = entry.vector or []
    if len(vector) != rows_expected * cols_expected:
        raise CortexError(
            ErrorCode.SCHEMA_CHANGED,
            f"vector 长度异常: {len(vector)}, 轴要求 {rows_expected * cols_expected}",
        )
    return [
        vector[row_index * cols_expected : (row_index + 1) * cols_expected]
        for row_index in range(rows_expected)
    ]


def _validate_metadata(entry: SurfaceEntry, request: VolatilityRequest) -> None:
    checks = (
        ("code", entry.code, request.code),
        ("maturityRule", entry.maturityRule, request.maturity_rule),
        ("strikeRule", entry.strikeRule, request.strike_rule),
        ("volatilityConvention", entry.volatilityConvention, request.volatility_convention),
    )
    for field, returned, expected in checks:
        if returned is not None and returned != expected:
            raise CortexError(
                ErrorCode.PARSE_FAILED,
                f"响应 {field}={returned!r} 与请求 {expected!r} 不一致",
            )


def _validate_common_axes(entry: SurfaceEntry) -> None:
    if len(set(entry.maturities)) != len(entry.maturities):
        raise CortexError(ErrorCode.SCHEMA_CHANGED, "maturity 轴包含重复坐标")
    if len(set(entry.strikes)) != len(entry.strikes):
        raise CortexError(ErrorCode.SCHEMA_CHANGED, "strike 轴包含重复坐标")
    if len(entry.forwardCurve) != len(entry.maturities):
        raise CortexError(ErrorCode.SCHEMA_CHANGED, "forwardCurve 与 maturity 轴长度不一致")
    if entry.zcCurve and len(entry.zcCurve) != len(entry.maturities):
        raise CortexError(ErrorCode.SCHEMA_CHANGED, "zcCurve 与 maturity 轴长度不一致")


def _validate_returned_axes(entry: SurfaceEntry, request: VolatilityRequest) -> None:
    _validate_common_axes(entry)
    if isinstance(request, SlidingMoneynessRequest):
        for maturity in entry.maturities:
            if maturity not in SLIDING_MATURITIES:
                raise CortexError(ErrorCode.SCHEMA_CHANGED, f"未知 sliding maturity: {maturity}")
        for strike in entry.strikes:
            _float_axis(strike, label="moneyness")
        return

    if isinstance(request, SlidingDeltaRequest):
        for maturity in entry.maturities:
            if maturity not in DELTA_MATURITIES:
                raise CortexError(ErrorCode.SCHEMA_CHANGED, f"未知 delta maturity: {maturity}")
        for strike in entry.strikes:
            domain = _delta_domain(strike)
            if domain not in DELTA_CODES:
                raise CortexError(ErrorCode.SCHEMA_CHANGED, f"未知 delta strike: {strike}")
        return

    for maturity in entry.maturities:
        try:
            date_type.fromisoformat(maturity)
        except ValueError as exc:
            raise CortexError(
                ErrorCode.SCHEMA_CHANGED, f"fixed/listed maturity 不是日期: {maturity}"
            ) from exc

    for strike in entry.strikes:
        _float_axis(strike, label="strike")


def _normalize_iv(raw: float | None) -> tuple[float | None, list[QualityFlag]]:
    if raw is None:
        return None, [QualityFlag.MISSING_IV]
    if not math.isfinite(raw):
        return None, [QualityFlag.INVALID_IV_NON_FINITE]
    if raw == 0:
        return None, [QualityFlag.INVALID_IV_ZERO]
    if raw < 0:
        return None, [QualityFlag.INVALID_IV_NEGATIVE]
    flags = []
    if raw > SUSPICIOUS_IV_THRESHOLD_DECIMAL:
        flags.append(QualityFlag.SUSPICIOUS_IV_EXTREME)
    return raw, flags


def normalize_surface_snapshots(
    canonical: CanonicalSurface, request: VolatilityRequest
) -> list[StandardSurfaceObservation]:
    """Normalize all returned coordinates for every supported request mode."""
    observations: list[StandardSurfaceObservation] = []
    for entry in canonical.entries:
        _validate_metadata(entry, request)
        _validate_returned_axes(entry, request)
        matrix = _entry_matrix(entry, request)
        snapshot_flags: list[QualityFlag] = []
        if entry.date in canonical.duplicate_dates:
            snapshot_flags.append(QualityFlag.DUPLICATE_IDENTICAL_REMOVED)
        if canonical.order_corrected:
            snapshot_flags.append(QualityFlag.SOURCE_ORDER_CORRECTED)
        if entry.spot is None or entry.spot <= 0:
            snapshot_flags.append(QualityFlag.MISSING_SPOT)
        # `time` is not flagged when absent: the OpenAPI contract states it "is optional
        # and is present for intraday data", and this app only requests daily EOD
        # history. Flagging it marked every clean observation, which forced the quality
        # status to WARNINGS permanently and buried the flags that do mean something.
        # source_time/source_timezone stay on the observation as plain metadata.

        points: list[SurfacePoint] = []
        for maturity_index, maturity in enumerate(entry.maturities):
            for strike_index, strike in enumerate(entry.strikes):
                raw_iv = matrix[maturity_index][strike_index]
                implied_vol, flags = _normalize_iv(raw_iv)
                points.append(
                    SurfacePoint(
                        maturity=maturity,
                        strike=_delta_domain(strike)
                        if isinstance(request, SlidingDeltaRequest)
                        else strike,
                        maturity_index=maturity_index,
                        strike_index=strike_index,
                        raw_implied_vol=raw_iv,
                        implied_vol=implied_vol,
                        quality_flags=_with_ok_if_empty(flags),
                    )
                )

        if not points:
            snapshot_flags.append(QualityFlag.MISSING_IV)

        observations.append(
            StandardSurfaceObservation(
                date=date_type.fromisoformat(entry.date),
                instrument_code=request.code,
                maturity_rule=request.maturity_rule,
                strike_rule=request.strike_rule,
                volatility_convention=request.volatility_convention,
                spot=entry.spot,
                maturities=entry.maturities,
                strikes=[
                    _delta_domain(strike) if isinstance(request, SlidingDeltaRequest) else strike
                    for strike in entry.strikes
                ],
                forward_curve=entry.forwardCurve,
                discount_factors=entry.zcCurve,
                points=points,
                source_time=entry.time,
                source_timezone=entry.timeZone,
                # BNP timeZone format has not been live-confirmed; do not infer an instant.
                source_timestamp=None,
                quality_flags=_with_ok_if_empty(snapshot_flags),
            )
        )
    return observations


def parse_surface_snapshots(
    payload: list, request: VolatilityRequest
) -> list[StandardSurfaceObservation]:
    return normalize_surface_snapshots(canonicalize_surface(payload), request)


def exact_coordinate(request: VolatilityRequest) -> tuple[str, float | str]:
    """Validate and return the single coordinate required by compare endpoints."""
    if isinstance(request, SlidingMoneynessRequest):
        if (
            request.low_maturity != request.high_maturity
            or request.low_strike != request.high_strike
        ):
            raise CortexError(
                ErrorCode.INVALID_REQUEST, "compare series 需要单一 maturity 和 moneyness"
            )
        return request.low_maturity, request.low_strike
    if isinstance(request, SlidingDeltaRequest):
        if (
            request.low_maturity is None
            or request.low_maturity != request.high_maturity
            or request.low_delta_strike is None
            or request.low_delta_strike != request.high_delta_strike
        ):
            raise CortexError(
                ErrorCode.INVALID_REQUEST, "delta compare series 需要单一 maturity 和 delta"
            )
        return request.low_maturity, request.low_delta_strike
    if isinstance(request, FixedStrikeRequest):
        if (
            request.low_fixed_maturity is None
            or request.low_fixed_maturity != request.high_fixed_maturity
            or request.low_fixed_strike is None
            or request.low_fixed_strike != request.high_fixed_strike
        ):
            raise CortexError(
                ErrorCode.INVALID_REQUEST, "fixed compare series 需要单一 expiry 和 strike"
            )
        return request.low_fixed_maturity.isoformat(), request.low_fixed_strike
    if (
        request.low_fixed_maturity is None
        or request.low_fixed_maturity != request.high_fixed_maturity
        or request.low_strike != request.high_strike
    ):
        raise CortexError(
            ErrorCode.INVALID_REQUEST, "listed compare series 需要单一 expiry 和 moneyness"
        )
    return request.low_fixed_maturity.isoformat(), request.low_strike


def _point_for(
    snapshot: StandardSurfaceObservation, target_maturity: str, target_strike: float | str
) -> SurfacePoint | None:
    for point in snapshot.points:
        maturity_matches = point.maturity.upper() == target_maturity.upper()
        if isinstance(target_strike, str):
            strike_matches = _delta_domain(point.strike) == _delta_domain(target_strike)
        else:
            try:
                strike_matches = abs(float(point.strike) - target_strike) < _STRIKE_TOL
            except ValueError:
                strike_matches = False
        if maturity_matches and strike_matches:
            return point
    return None


def surface_snapshots_to_series(
    snapshots: list[StandardSurfaceObservation], request: VolatilityRequest
) -> list[StandardObservation]:
    """Select an exact coordinate for compare without nearest-neighbour fallback."""
    target_maturity, target_strike = exact_coordinate(request)
    observations: list[StandardObservation] = []
    for snapshot in snapshots:
        point = _point_for(snapshot, target_maturity, target_strike)
        flags = _without_ok(snapshot.quality_flags)
        maturity_index = None
        if target_maturity in snapshot.maturities:
            maturity_index = snapshot.maturities.index(target_maturity)
        else:
            flags.append(QualityFlag.MATURITY_MISMATCH)
        if point is None:
            flags.extend([QualityFlag.STRIKE_MISMATCH, QualityFlag.MISSING_IV])
        else:
            flags.extend(_without_ok(point.quality_flags))
        forward = (
            snapshot.forward_curve[maturity_index]
            if maturity_index is not None and maturity_index < len(snapshot.forward_curve)
            else None
        )
        if forward is None:
            flags.append(QualityFlag.MISSING_FORWARD)
        discount = (
            snapshot.discount_factors[maturity_index]
            if maturity_index is not None and maturity_index < len(snapshot.discount_factors)
            else None
        )
        returned_strike: float | str | None = None
        if point is not None:
            returned_strike = (
                point.strike if isinstance(target_strike, str) else float(point.strike)
            )
        observations.append(
            StandardObservation(
                date=snapshot.date,
                instrument_code=request.code,
                spot=snapshot.spot,
                target_maturity=target_maturity,
                returned_maturity=point.maturity if point is not None else None,
                strike_rule=request.strike_rule,
                target_strike=target_strike,
                returned_strike=returned_strike,
                forward=forward,
                discount_factor=discount,
                raw_implied_vol=point.raw_implied_vol if point is not None else None,
                implied_vol=point.implied_vol if point is not None else None,
                source_time=snapshot.source_time,
                source_timezone=snapshot.source_timezone,
                source_timestamp=snapshot.source_timestamp,
                quality_flags=_with_ok_if_empty(flags),
            )
        )
    return observations


def normalize_surface(
    canonical: CanonicalSurface, request: VolatilityRequest
) -> list[StandardObservation]:
    """Normalize a canonical payload and select an exact compare coordinate."""
    return surface_snapshots_to_series(normalize_surface_snapshots(canonical, request), request)


def parse_surface(payload: list, request: VolatilityRequest) -> list[StandardObservation]:
    """Parse an exact-coordinate series for any supported request mode."""
    return normalize_surface(canonicalize_surface(payload), request)
