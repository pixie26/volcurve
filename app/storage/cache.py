"""Cache policy.

- Completed historical ranges (end_date < today): permanent cache.
- Ranges touching today: short TTL, because the current session may update.
- API version bump invalidates everything (version is part of the hash).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

INTRADAY_TTL = timedelta(hours=6)


def cache_policy(end_date: date, today: date | None = None) -> str:
    today = today or date.today()
    return "historical" if end_date < today else "intraday"


def is_fresh(retrieved_at: datetime, policy: str, now: datetime | None = None) -> bool:
    if policy == "historical":
        return True
    now = now or datetime.now()
    return (now - retrieved_at) < INTRADAY_TTL
