"""Analytics engine: IV series + realized vol + spread statistics.

Input observations must cover the warm-up-extended range (see alignment.py)
in ascending date order. Output is sliced to the user's display range.
All vols are decimal units here (0.229 = 22.9%); presentation converts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.analytics import statistics as stats
from app.analytics.quality import spot_series_flags
from app.analytics.realized_vol import (
    calculate_forward_realized_vol,
    calculate_trailing_realized_vol,
)
from app.domain.observations import QualityFlag, StandardObservation


@dataclass
class SeriesEntry:
    date: date
    spot: float | None
    forward: float | None
    raw_implied_vol: float | None
    implied_vol: float | None
    realized_vol: float | None
    iv_minus_rv: float | None
    iv_divided_by_rv: float | None
    quality_flags: list[str] = field(default_factory=list)


@dataclass
class CompareResult:
    series: list[SeriesEntry]
    summary: dict
    warmup_from: date
    display_from: date
    display_to: date


def run_compare(
    observations: list[StandardObservation],
    *,
    display_from: date,
    display_to: date,
    window_sessions: int,
    alignment: str,  # "trailing" | "forward"
    annualization: int = 252,
    include_realized_vol: bool = True,
) -> CompareResult:
    if alignment not in ("trailing", "forward"):
        raise ValueError("alignment must be 'trailing' or 'forward'")

    dates = [o.date for o in observations]
    spots = [o.spot for o in observations]

    if not include_realized_vol:
        rvs = [None] * len(observations)
    elif alignment == "trailing":
        rvs = calculate_trailing_realized_vol(spots, window_sessions, annualization)
    else:
        rvs = calculate_forward_realized_vol(spots, window_sessions, annualization)

    extra_flags = spot_series_flags(dates, spots)

    series: list[SeriesEntry] = []
    for obs, rv in zip(observations, rvs, strict=True):
        if not (display_from <= obs.date <= display_to):
            continue  # warm-up prefix / unrealized tail stay out of the display range
        flags = [f.value for f in obs.quality_flags if f != QualityFlag.OK]
        flags.extend(f.value for f in extra_flags.get(obs.date, []))
        # Only a caller that asked for RV can be short of history for it.
        if include_realized_vol and rv is None and QualityFlag.INSUFFICIENT_HISTORY.value not in flags:
            flags.append(QualityFlag.INSUFFICIENT_HISTORY.value)
        if not flags:
            flags = [QualityFlag.OK.value]
        series.append(
            SeriesEntry(
                date=obs.date,
                spot=obs.spot,
                forward=obs.forward,
                raw_implied_vol=obs.raw_implied_vol,
                implied_vol=obs.implied_vol,
                realized_vol=rv,
                iv_minus_rv=stats.iv_minus_rv(obs.implied_vol, rv),
                iv_divided_by_rv=stats.iv_divided_by_rv(obs.implied_vol, rv),
                quality_flags=flags,
            )
        )

    spreads = [e.iv_minus_rv for e in series]
    valid_pairs = [
        (e.implied_vol, e.realized_vol)
        for e in series
        if e.implied_vol is not None and e.realized_vol is not None
    ]
    latest_market = series[-1] if series else None
    latest_iv = next((e for e in reversed(series) if e.implied_vol is not None), None)
    latest_comparable = next(
        (e for e in reversed(series) if e.implied_vol is not None and e.realized_vol is not None),
        None,
    )
    latest_spread = latest_comparable.iv_minus_rv if latest_comparable else None

    summary = {
        "latestMarketDate": latest_market.date if latest_market else None,
        "latestIvDate": latest_iv.date if latest_iv else None,
        "latestIv": latest_iv.implied_vol if latest_iv else None,
        "latestComparableDate": latest_comparable.date if latest_comparable else None,
        "latestComparableIv": latest_comparable.implied_vol if latest_comparable else None,
        "latestComparableRv": latest_comparable.realized_vol if latest_comparable else None,
        "latestComparableSpread": latest_spread,
        # Compatibility alias retained while the Phase-4 API is completed.
        "latestRv": latest_comparable.realized_vol if latest_comparable else None,
        "latestSpread": latest_spread,
        "spreadPercentile": stats.percentile_rank(spreads, latest_spread),
        "spreadZScore": stats.zscore(spreads, latest_spread),
        "correlation": stats.correlation(
            [e.implied_vol for e in series], [e.realized_vol for e in series]
        ),
        "observationCount": len(valid_pairs),
    }
    return CompareResult(
        series=series,
        summary=summary,
        warmup_from=dates[0] if dates else display_from,
        display_from=display_from,
        display_to=display_to,
    )
