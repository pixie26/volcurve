"""Cache freshness policy.

All successful cached responses are reusable for eight rolling hours.  Historical
volatility data is deliberately not treated as immutable because Cortex can revise
history.  The long-lived, revision-aware time-series library is separate from this
short request cache.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

CACHE_TTL = timedelta(hours=8)
# Compatibility name used by older tests/imports.
INTRADAY_TTL = CACHE_TTL


def cache_policy(end_date: date, today: date | None = None) -> str:
    today = today or date.today()
    return "historical" if end_date < today else "intraday"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def freshness_cutoff(now: datetime | None = None) -> datetime:
    current = _utc(now or datetime.now(UTC))
    return current - CACHE_TTL


def is_fresh(retrieved_at: datetime, policy: str, now: datetime | None = None) -> bool:
    # `policy` remains metadata (historical/intraday) for audit compatibility.  Both
    # classes share the same rolling TTL so old catalog rows migrate automatically.
    del policy
    current = _utc(now or datetime.now(UTC))
    return (current - _utc(retrieved_at)) < CACHE_TTL
