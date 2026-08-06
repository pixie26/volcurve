"""Series-level data-quality checks (spot path, calendar gaps, jumps).

Findings are attached as flags; values are never silently corrected.
"""

from __future__ import annotations

from datetime import date

from app.domain.observations import QualityFlag

_JUMP_ABS_RETURN = 0.10  # |r| > 10% in one session: investigate, don't fix
_MAX_CALENDAR_GAP = 7  # days between consecutive observations


def spot_series_flags(
    dates: list[date], spots: list[float | None]
) -> dict[date, list[QualityFlag]]:
    import math

    flags: dict[date, list[QualityFlag]] = {d: [] for d in dates}
    prev_date: date | None = None
    prev_spot: float | None = None
    for d, s in zip(dates, spots):
        if s is None or s <= 0:
            flags[d].append(QualityFlag.MISSING_SPOT)
        if prev_date is not None and (d - prev_date).days > _MAX_CALENDAR_GAP:
            flags[d].append(QualityFlag.STALE_DATA)
        if prev_spot and s and abs(math.log(s / prev_spot)) > _JUMP_ABS_RETURN:
            flags[d].append(QualityFlag.POSSIBLE_CORPORATE_ACTION)
        prev_date, prev_spot = d, s
    return flags
