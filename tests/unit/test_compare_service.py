"""Phase A service tests for hidden fetch ranges and forward extension."""

from datetime import UTC, date, datetime

from app.clients.cortex.client import FetchResult
from app.domain.observations import QualityFlag, StandardObservation
from app.domain.requests import ImpliedVolRequest
from app.services.compare import execute_compare, load_compare_observations


def _request() -> ImpliedVolRequest:
    return ImpliedVolRequest(
        code="US_QQQ",
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 6),
        low_strike=100,
        high_strike=100,
        low_maturity="3M",
        high_maturity="3M",
    )


def _observation(business_date: date, spot: float) -> StandardObservation:
    return StandardObservation(
        date=business_date,
        instrument_code="US_QQQ",
        spot=spot,
        target_maturity="3M",
        returned_maturity="3M",
        strike_rule="relative_to_forward",
        target_strike=100,
        returned_strike=100,
        forward=spot + 1,
        discount_factor=0.99,
        raw_implied_vol=0.2,
        implied_vol=0.2,
        quality_flags=[QualityFlag.OK],
    )


class FakeClient:
    def __init__(self, observations: list[StandardObservation]) -> None:
        self.observations = observations
        self.requests: list[ImpliedVolRequest] = []

    def get_implied_volatility(self, request, *, force_refresh=False):
        self.requests.append(request)
        selected = [
            observation
            for observation in self.observations
            if request.start_date <= observation.date <= request.end_date
        ]
        result = FetchResult([], "fixture", f"fetch-{len(self.requests)}", datetime.now(UTC))
        return selected, result


def _holiday_heavy_observations() -> list[StandardObservation]:
    # The initial calendar estimate ends on Jan 21.  It has only one valid
    # price from the final display date onward, so the service must append.
    dates_and_spots = [
        (date(2025, 1, 2), 100.0),
        (date(2025, 1, 3), 101.0),
        (date(2025, 1, 6), 102.0),
        (date(2025, 1, 22), 103.0),
        (date(2025, 1, 23), 105.0),
        (date(2025, 1, 24), 104.0),
    ]
    return [_observation(business_date, spot) for business_date, spot in dates_and_spots]


def test_forward_range_extends_until_window_plus_one_valid_prices():
    client = FakeClient(_holiday_heavy_observations())
    loaded = load_compare_observations(
        client,
        _request(),
        window_sessions=3,
        alignment="forward",
        available_through=date(2025, 1, 31),
    )

    assert len(client.requests) == 2
    assert client.requests[0].start_date == date(2025, 1, 2)
    assert client.requests[0].end_date == date(2025, 1, 21)
    assert client.requests[1].start_date == date(2025, 1, 22)
    assert loaded.extension_requests == 1
    assert loaded.forward_tail_observations == 4
    assert loaded.forward_tail_complete is True


def test_forward_extension_makes_last_displayed_historical_rv_available():
    client = FakeClient(_holiday_heavy_observations())
    execution = execute_compare(
        client,
        _request(),
        window_sessions=3,
        alignment="forward",
        available_through=date(2025, 1, 31),
    )

    assert execution.analytics.series[-1].date == date(2025, 1, 6)
    assert execution.analytics.series[-1].realized_vol is not None
    assert execution.analytics.summary["latestComparableDate"] == date(2025, 1, 6)


def test_forward_extension_stops_at_known_availability_cap():
    client = FakeClient(_holiday_heavy_observations()[:3])
    loaded = load_compare_observations(
        client,
        _request(),
        window_sessions=3,
        alignment="forward",
        available_through=date(2025, 1, 21),
    )

    assert len(client.requests) == 1
    assert loaded.extension_requests == 0
    assert loaded.forward_tail_observations == 1
    assert loaded.forward_tail_complete is False


def test_forward_extension_expands_until_cap_when_appends_add_no_valid_prices():
    client = FakeClient(_holiday_heavy_observations()[:3])
    loaded = load_compare_observations(
        client,
        _request(),
        window_sessions=3,
        alignment="forward",
        available_through=date(2025, 2, 28),
    )

    assert len(client.requests) > 2
    assert loaded.extension_requests == len(client.requests) - 1
    assert loaded.requested_range.end == date(2025, 2, 28)
    assert loaded.forward_tail_complete is False
