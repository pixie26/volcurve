"""Spread / ratio / percentile / z-score / correlation.

Percentile and z-score default to the *entire selected history*
(full-sample), per the agreed methodology. Null-safe: pairs with any
missing side are dropped; nothing is zero-filled.
"""

from __future__ import annotations

import math
from statistics import mean, stdev


def iv_minus_rv(iv: float | None, rv: float | None) -> float | None:
    if iv is None or rv is None:
        return None
    return iv - rv


def iv_divided_by_rv(iv: float | None, rv: float | None) -> float | None:
    if iv is None or rv is None or rv == 0:
        return None
    return iv / rv


def _valid(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None]


def percentile_rank(series: list[float | None], value: float | None) -> float | None:
    """Share (%) of valid observations <= value within the full series."""
    valid = _valid(series)
    if value is None or not valid:
        return None
    return 100.0 * sum(1 for v in valid if v <= value) / len(valid)


def zscore(series: list[float | None], value: float | None) -> float | None:
    """(value - mean) / stdev(ddof=1) over the full series."""
    valid = _valid(series)
    if value is None or len(valid) < 2:
        return None
    sd = stdev(valid)
    if sd == 0:
        return None
    return (value - mean(valid)) / sd


def correlation(xs: list[float | None], ys: list[float | None]) -> float | None:
    """Pearson correlation over paired valid observations (needs >= 3 pairs)."""
    pairs = [(x, y) for x, y in zip(xs, ys, strict=True) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    xvals = [p[0] for p in pairs]
    yvals = [p[1] for p in pairs]
    mx, my = mean(xvals), mean(yvals)
    cov = sum((x - mx) * (y - my) for x, y in pairs)
    vx = sum((x - mx) ** 2 for x in xvals)
    vy = sum((y - my) ** 2 for y in yvals)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)
