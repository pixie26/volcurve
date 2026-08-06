"""Fetch-range alignment for trailing and forward realized volatility.

RV window counts *trading* sessions; the calendar contains weekends and
holidays, and w returns require w+1 prices. Rule (confirmed):
fetch_start = user_start - ceil(window * 7/5) - 10 calendar days.
The display range is always sliced back to exactly the user's dates.  Forward
ranges are initially estimated from calendar days and may then be extended by
the compare service when the response contains too few trading observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.disclosures import RV_BUFFER_EXTRA_CALENDAR_DAYS


@dataclass(frozen=True)
class FetchRange:
    start: date
    end: date


def warmup_start(user_start: date, window_sessions: int) -> date:
    return user_start - timedelta(days=calendar_buffer_days(window_sessions))


def calendar_buffer_days(session_count: int) -> int:
    """Convert a trading-session requirement into a conservative calendar buffer."""
    if session_count < 1:
        raise ValueError("session_count must be >= 1")
    return -(-session_count * 7 // 5) + RV_BUFFER_EXTRA_CALENDAR_DAYS


def fetch_range(
    display_start: date,
    display_end: date,
    window_sessions: int,
    alignment: str,
    *,
    available_through: date | None = None,
) -> FetchRange:
    """Return the initial upstream range required by the RV alignment.

    Forward RV needs observations after the display range. Callers may extend
    this range again if holidays leave fewer than ``window + 1`` prices.
    """
    if display_end < display_start:
        raise ValueError("display_end must be >= display_start")
    if window_sessions < 2:
        raise ValueError("window_sessions must be >= 2")
    buffer_days = calendar_buffer_days(window_sessions)
    if alignment == "trailing":
        return FetchRange(warmup_start(display_start, window_sessions), display_end)
    if alignment == "forward":
        end = display_end + timedelta(days=buffer_days)
        if available_through is not None:
            end = min(end, available_through)
        return FetchRange(display_start, end)
    raise ValueError("alignment must be 'trailing' or 'forward'")


def extend_forward_end(current_end: date, missing_sessions: int, available_through: date) -> date:
    """Return the next bounded end date for an incomplete forward tail."""
    if current_end >= available_through:
        return current_end
    return min(
        current_end + timedelta(days=calendar_buffer_days(max(missing_sessions, 1))),
        available_through,
    )
