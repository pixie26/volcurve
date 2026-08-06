"""Fetch-range alignment: warm-up so RV is defined across the whole display range.

RV window counts *trading* sessions; the calendar contains weekends and
holidays, and w returns require w+1 prices. Rule (confirmed):
fetch_start = user_start - ceil(window * 7/5) - 10 calendar days.
The display range is always sliced back to exactly the user's dates.
"""

from __future__ import annotations

from datetime import date, timedelta


def warmup_start(user_start: date, window_sessions: int) -> date:
    buffer_days = -(-window_sessions * 7 // 5) + 10  # ceil(w*7/5) + 10
    return user_start - timedelta(days=buffer_days)
