"""Raw surface entries -> standardized observations.

Matrix access is coordinate-based only: locate the target maturity/strike
in the returned axes, verify dimensions, then index. Never use fixed
positions like matrix[0][0] without coordinate verification.

Verified orientation (probe, 2026-08-06): rows = maturities, cols = strikes.
"""

from __future__ import annotations

from datetime import date as date_type

from app.clients.cortex.errors import CortexError, ErrorCode
from app.clients.cortex.models import SurfaceEntry
from app.domain.observations import QualityFlag, StandardObservation
from app.domain.requests import ImpliedVolRequest

_STRIKE_TOL = 1e-9


def _find_maturity_index(maturities: list[str], target: str) -> tuple[int | None, list[QualityFlag]]:
    matches = [i for i, m in enumerate(maturities) if m.upper() == target.upper()]
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, [QualityFlag.MATURITY_MISMATCH]
    return None, [QualityFlag.MATURITY_MISMATCH]


def _find_strike_index(strikes: list[str], target: float) -> tuple[int | None, list[QualityFlag]]:
    matches = []
    for i, s in enumerate(strikes):
        try:
            if abs(float(s) - target) < _STRIKE_TOL:
                matches.append(i)
        except ValueError:
            continue
    if len(matches) == 1:
        return matches[0], []
    return None, [QualityFlag.STRIKE_MISMATCH]


def parse_surface(payload: list, request: ImpliedVolRequest) -> list[StandardObservation]:
    if not isinstance(payload, list):
        raise CortexError(ErrorCode.SCHEMA_CHANGED, "implied-volatility 响应不是数组")
    if not payload:
        raise CortexError(ErrorCode.NO_DATA, "implied-volatility 返回空结果")

    target_maturity = request.low_maturity or ""
    target_strike = request.low_strike if request.low_strike is not None else float("nan")

    observations: list[StandardObservation] = []
    seen_dates: set[str] = set()
    prev_date: date_type | None = None

    for raw in payload:
        entry = SurfaceEntry.model_validate(raw)
        flags: list[QualityFlag] = []

        # duplicate / ordering checks
        if entry.date in seen_dates:
            flags.append(QualityFlag.DUPLICATE_DATE)
        seen_dates.add(entry.date)
        cur_date = date_type.fromisoformat(entry.date)
        if prev_date is not None and cur_date <= prev_date:
            flags.append(QualityFlag.NON_MONOTONIC_DATE)
        prev_date = cur_date

        # spot
        if entry.spot is None or entry.spot <= 0:
            flags.append(QualityFlag.MISSING_SPOT)

        # coordinate resolution
        mi, mf = _find_maturity_index(entry.maturities, target_maturity)
        flags.extend(mf)
        si, sf = _find_strike_index(entry.strikes, target_strike)
        flags.extend(sf)

        # matrix dimension verification (rows=maturities, cols=strikes)
        implied_vol = None
        if entry.matrix:
            rows = len(entry.matrix)
            cols = len(entry.matrix[0]) if rows else 0
            if rows != len(entry.maturities) or cols != len(entry.strikes) or any(
                len(r) != cols for r in entry.matrix
            ):
                raise CortexError(
                    ErrorCode.SCHEMA_CHANGED,
                    f"matrix 维度异常: {rows}x{cols}, 轴为 {len(entry.maturities)}x{len(entry.strikes)}",
                )
            if mi is not None and si is not None:
                implied_vol = entry.matrix[mi][si]
        if implied_vol is None:
            flags.append(QualityFlag.MISSING_IV)
        elif implied_vol <= 0:
            flags.append(QualityFlag.MISSING_IV)  # non-positive IV is not usable

        # forward / discount factor aligned with maturity axis
        forward = entry.forwardCurve[mi] if mi is not None and mi < len(entry.forwardCurve) else None
        if forward is None:
            flags.append(QualityFlag.MISSING_FORWARD)
        discount = entry.zcCurve[mi] if mi is not None and mi < len(entry.zcCurve) else None

        # snapshot time (observed null on production)
        source_ts = None
        if entry.time:
            source_ts = f"{entry.date}T{entry.time}{entry.timeZone or ''}"
        else:
            flags.append(QualityFlag.SNAPSHOT_TIME_MISSING)

        if not flags:
            flags = [QualityFlag.OK]

        observations.append(
            StandardObservation(
                date=cur_date,
                instrument_code=request.code,
                spot=entry.spot,
                target_maturity=target_maturity,
                returned_maturity=entry.maturities[mi] if mi is not None else None,
                strike_rule=request.strike_rule,
                target_strike=target_strike,
                returned_strike=float(entry.strikes[si]) if si is not None else None,
                forward=forward,
                discount_factor=discount,
                implied_vol=implied_vol,
                source_timestamp=source_ts,
                quality_flags=flags,
            )
        )

    return observations
