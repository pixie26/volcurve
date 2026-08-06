"""Correctness-first orchestration for IV/RV compare queries.

The Cortex request range is not the same as the range shown to the user.
Trailing RV needs history before the display start.  Forward RV needs future
trading observations after the display end and may require more than the first
calendar estimate when holidays or closures reduce the returned session count.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from app.analytics.alignment import FetchRange, extend_forward_end, fetch_range
from app.analytics.engine import CompareResult, run_compare
from app.clients.cortex.client import FetchResult
from app.clients.cortex.errors import CortexError, ErrorCode
from app.domain.disclosures import FORWARD_MAX_EXTENSION_REQUESTS
from app.domain.observations import StandardObservation
from app.domain.requests import VolatilityRequest


class CompareDataClient(Protocol):
    def get_implied_volatility(
        self, request: VolatilityRequest, *, force_refresh: bool = False
    ) -> tuple[list[StandardObservation], FetchResult]: ...


@dataclass(frozen=True)
class ObservationLoadResult:
    observations: list[StandardObservation]
    fetch_results: list[FetchResult]
    requested_range: FetchRange
    extension_requests: int
    forward_tail_observations: int
    forward_tail_complete: bool


@dataclass(frozen=True)
class CompareExecution:
    analytics: CompareResult
    load: ObservationLoadResult
    window_sessions: int
    alignment: str


def _merge_observations(
    existing: list[StandardObservation], incoming: list[StandardObservation]
) -> list[StandardObservation]:
    """Merge append responses without accepting cross-request date conflicts."""
    by_date = {observation.date: observation for observation in existing}
    for observation in incoming:
        prior = by_date.get(observation.date)
        if prior is not None and prior.model_dump(mode="json") != observation.model_dump(
            mode="json"
        ):
            raise CortexError(
                ErrorCode.AMBIGUOUS_DUPLICATE_DATE,
                f"追加查询在同一业务日期返回冲突观测: {observation.date.isoformat()}",
            )
        by_date[observation.date] = observation
    return [by_date[business_date] for business_date in sorted(by_date)]


def _forward_tail_count(
    observations: list[StandardObservation], display_start: date, display_end: date
) -> int:
    """Count valid prices from the final displayed market observation onward."""
    displayed = [
        observation
        for observation in observations
        if display_start <= observation.date <= display_end
        and observation.spot is not None
        and observation.spot > 0
    ]
    if not displayed:
        return 0
    anchor = displayed[-1].date
    return sum(
        observation.date >= anchor and observation.spot is not None and observation.spot > 0
        for observation in observations
    )


def load_compare_observations(
    client: CompareDataClient,
    request: VolatilityRequest,
    *,
    window_sessions: int,
    alignment: str,
    available_through: date | None = None,
    force_refresh: bool = False,
) -> ObservationLoadResult:
    """Fetch the hidden RV range and extend an incomplete forward tail.

    ``request.start_date`` and ``request.end_date`` are the display range.  The
    returned observations may extend outside it, while analytics always slice
    the visible series back to those original dates.
    """
    display_start = request.start_date
    display_end = request.end_date
    availability_cap = available_through or datetime.now(UTC).date()
    if alignment == "forward" and availability_cap < display_start:
        raise ValueError("available_through must be >= display start")

    initial = fetch_range(
        display_start,
        display_end,
        window_sessions,
        alignment,
        available_through=availability_cap if alignment == "forward" else None,
    )
    ranged_request = request.model_copy(
        update={"start_date": initial.start, "end_date": initial.end}
    )
    observations, first_result = client.get_implied_volatility(
        ranged_request, force_refresh=force_refresh
    )
    fetch_results = [first_result]

    if alignment != "forward":
        return ObservationLoadResult(
            observations=observations,
            fetch_results=fetch_results,
            requested_range=initial,
            extension_requests=0,
            forward_tail_observations=0,
            forward_tail_complete=True,
        )

    current_end = initial.end
    extension_requests = 0
    no_progress_rounds = 0
    tail_count = _forward_tail_count(observations, display_start, display_end)
    required = window_sessions + 1

    while (
        tail_count < required
        and current_end < availability_cap
        and extension_requests < FORWARD_MAX_EXTENSION_REQUESTS
    ):
        previous_tail_count = tail_count
        estimated_missing = (required - tail_count) * (2**no_progress_rounds)
        next_end = extend_forward_end(current_end, estimated_missing, availability_cap)
        if next_end <= current_end:
            break
        append_request = request.model_copy(
            update={"start_date": current_end + timedelta(days=1), "end_date": next_end}
        )
        extension_requests += 1
        try:
            incoming, fetch_result = client.get_implied_volatility(
                append_request, force_refresh=force_refresh
            )
        except CortexError as exc:
            if exc.code != ErrorCode.NO_DATA:
                raise
        else:
            observations = _merge_observations(observations, incoming)
            fetch_results.append(fetch_result)
        current_end = next_end
        tail_count = _forward_tail_count(observations, display_start, display_end)
        if tail_count <= previous_tail_count:
            no_progress_rounds += 1
        else:
            no_progress_rounds = 0

    return ObservationLoadResult(
        observations=observations,
        fetch_results=fetch_results,
        requested_range=FetchRange(initial.start, current_end),
        extension_requests=extension_requests,
        forward_tail_observations=tail_count,
        forward_tail_complete=tail_count >= required,
    )


def execute_compare(
    client: CompareDataClient,
    request: VolatilityRequest,
    *,
    window_sessions: int,
    alignment: str,
    available_through: date | None = None,
    force_refresh: bool = False,
    annualization: int = 252,
) -> CompareExecution:
    """Load the correct hidden range, then calculate the visible comparison."""
    loaded = load_compare_observations(
        client,
        request,
        window_sessions=window_sessions,
        alignment=alignment,
        available_through=available_through,
        force_refresh=force_refresh,
    )
    analytics = run_compare(
        loaded.observations,
        display_from=request.start_date,
        display_to=request.end_date,
        window_sessions=window_sessions,
        alignment=alignment,
        annualization=annualization,
    )
    return CompareExecution(
        analytics=analytics,
        load=loaded,
        window_sessions=window_sessions,
        alignment=alignment,
    )
