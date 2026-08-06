"""Series-level data-quality checks (spot path, calendar gaps, jumps).

Findings are attached as flags; values are never silently corrected.
"""

from __future__ import annotations

from datetime import date

from app.domain.disclosures import RETURN_OUTLIER_THRESHOLD_LOG
from app.domain.observations import QualityFlag

_MAX_CALENDAR_GAP = 7  # days between consecutive observations


def spot_series_flags(
    dates: list[date], spots: list[float | None]
) -> dict[date, list[QualityFlag]]:
    import math

    flags: dict[date, list[QualityFlag]] = {d: [] for d in dates}
    prev_date: date | None = None
    prev_spot: float | None = None
    for d, s in zip(dates, spots, strict=True):
        if s is None or s <= 0:
            flags[d].append(QualityFlag.MISSING_SPOT)
        if prev_date is not None and (d - prev_date).days > _MAX_CALENDAR_GAP:
            flags[d].append(QualityFlag.STALE_DATA)
        if prev_spot and s and abs(math.log(s / prev_spot)) > RETURN_OUTLIER_THRESHOLD_LOG:
            # A price jump is not evidence of a corporate action. Keep this as
            # a warning only; values are never adjusted automatically.
            flags[d].append(QualityFlag.RETURN_OUTLIER)
        prev_date, prev_spot = d, s
    return flags
