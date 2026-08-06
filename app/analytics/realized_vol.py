"""Realized volatility from close-to-close log returns.

Confirmed convention (calculation_spec):
- return: r_t = log(S_t / S_{t-1})
- std: sample standard deviation, ddof=1, demeaned (== Excel STDEV.S)
- annualization: sqrt(252)
- trailing RV at index i uses r_{i-w+1..i}  (w returns, w+1 prices)
- forward  RV at index i uses r_{i+1..i+w}  (tail w sessions are null)
- missing values stay null — never zero-filled.
"""

from __future__ import annotations

import math
from statistics import stdev

WINDOW_SESSIONS: dict[str, int] = {
    "1W": 5,
    "1M": 21,
    "2M": 42,
    "3M": 63,
    "6M": 126,
    "1Y": 252,
}
MIN_WINDOW = 2
MAX_WINDOW = 756


def resolve_window(window: str | int) -> int:
    if isinstance(window, int):
        sessions = window
    else:
        key = window.strip().upper()
        if key not in WINDOW_SESSIONS:
            raise ValueError(f"unknown window {window!r}; use one of {sorted(WINDOW_SESSIONS)} or sessions int")
        sessions = WINDOW_SESSIONS[key]
    if not (MIN_WINDOW <= sessions <= MAX_WINDOW):
        raise ValueError(f"window must be within [{MIN_WINDOW}, {MAX_WINDOW}] sessions")
    return sessions


def calculate_log_returns(spots: list[float | None]) -> list[float | None]:
    """returns[i] = log(S_i / S_{i-1}); returns[0] is None; None if either price missing."""
    out: list[float | None] = [None]
    for prev, cur in zip(spots, spots[1:]):
        if prev is None or cur is None or prev <= 0 or cur <= 0:
            out.append(None)
        else:
            out.append(math.log(cur / prev))
    return out


def _window_std(values: list[float | None]) -> float | None:
    if any(v is None for v in values):
        return None
    return stdev(values)  # ddof=1, demeaned — matches Excel STDEV.S


def calculate_trailing_realized_vol(
    spots: list[float | None], window: int, annualization: int = 252
) -> list[float | None]:
    """rv[i] = stdev(r_{i-w+1..i}) * sqrt(ann); first w sessions are None."""
    returns = calculate_log_returns(spots)
    factor = math.sqrt(annualization)
    out: list[float | None] = []
    for i in range(len(spots)):
        if i < window:
            out.append(None)
            continue
        windowed = returns[i - window + 1 : i + 1]
        std = _window_std(windowed)
        out.append(None if std is None else std * factor)
    return out


def calculate_forward_realized_vol(
    spots: list[float | None], window: int, annualization: int = 252
) -> list[float | None]:
    """rv[i] = stdev(r_{i+1..i+w}) * sqrt(ann); last w sessions are None (unrealized)."""
    returns = calculate_log_returns(spots)
    factor = math.sqrt(annualization)
    out: list[float | None] = []
    n = len(spots)
    for i in range(n):
        if i + window >= n:
            out.append(None)
            continue
        windowed = returns[i + 1 : i + window + 1]
        std = _window_std(windowed)
        out.append(None if std is None else std * factor)
    return out
