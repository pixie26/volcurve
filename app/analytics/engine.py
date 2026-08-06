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
) -> CompareResult:
    if alignment not in ("trailing", "forward"):
        raise ValueError("alignment must be 'trailing' or 'forward'")

    dates = [o.date for o in observations]
    spots = [o.spot for o in observations]
    ivs = [o.implied_vol for o in observations]

    if alignment == "trailing":
        rvs = calculate_trailing_realized_vol(spots, window_sessions, annualization)
    else:
        rvs = calculate_forward_realized_vol(spots, window_sessions, annualization)

    extra_flags = spot_series_flags(dates, spots)

    series: list[SeriesEntry] = []
    for obs, rv in zip(observations, rvs):
        if not (display_from <= obs.date <= display_to):
            continue  # warm-up prefix / unrealized tail stay out of the display range
        flags = [f.value for f in obs.quality_flags if f != QualityFlag.OK]
        flags.extend(f.value for f in extra_flags.get(obs.date, []))
        if rv is None and QualityFlag.INSUFFICIENT_HISTORY.value not in flags:
            flags.append(QualityFlag.INSUFFICIENT_HISTORY.value)
        if not flags:
            flags = [QualityFlag.OK.value]
        series.append(
            SeriesEntry(
                date=obs.date,
                spot=obs.spot,
                forward=obs.forward,
                implied_vol=obs.implied_vol,
                realized_vol=rv,
                iv_minus_rv=stats.iv_minus_rv(obs.implied_vol, rv),
                iv_divided_by_rv=stats.iv_divided_by_rv(obs.implied_vol, rv),
                quality_flags=flags,
            )
        )

    spreads = [e.iv_minus_rv for e in series]
    valid_pairs = [(e.implied_vol, e.realized_vol) for e in series
                   if e.implied_vol is not None and e.realized_vol is not None]
    latest = next((e for e in reversed(series)
                   if e.implied_vol is not None or e.realized_vol is not None), None)
    latest_spread = latest.iv_minus_rv if latest else None

    summary = {
        "latestIv": latest.implied_vol if latest else None,
        "latestRv": latest.realized_vol if latest else None,
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
