"""Atomic storage and cache-state regression tests."""

import threading
import time
from datetime import UTC, date, datetime

import pytest

from app.clients.cortex.client import CortexClient
from app.clients.cortex.errors import CortexError, ErrorCode
from app.domain.requests import ImpliedVolRequest
from app.storage.catalog import Catalog
from app.storage.normalized_store import NormalizedStore
from app.storage.raw_store import RawStore


def _bare_client(tmp_path, *, mode="live"):
    """A client assembled without __init__ so the stores can be pointed at tmp_path."""
    client = CortexClient.__new__(CortexClient)
    client._mode = mode
    client.api_version = "1.60.0"
    client._catalog = Catalog(tmp_path / "catalog.duckdb")
    client._raw = RawStore(tmp_path / "raw")
    client._normalized = NormalizedStore(tmp_path / "normalized")
    client._inflight = {}
    client._inflight_guard = threading.Lock()
    return client


def _request() -> ImpliedVolRequest:
    return ImpliedVolRequest(
        code="US_QQQ",
        start_date=date(2020, 1, 2),
        end_date=date(2020, 1, 20),
        low_strike=100,
        high_strike=100,
        low_maturity="3M",
        high_maturity="3M",
    )


def test_raw_store_atomic_round_trip(tmp_path):
    store = RawStore(tmp_path / "raw")
    payload = [{"date": "2025-01-01", "value": 1}]
    path = store.save("implied-volatility", "abc", payload)
    assert store.load("implied-volatility", "abc") == payload
    assert not list(path.parent.glob("*.tmp"))


def test_catalog_persists_state_and_error_code(tmp_path):
    catalog = Catalog(tmp_path / "catalog.duckdb")
    now = datetime.now(UTC)
    catalog.upsert(
        request_hash="abc",
        endpoint="implied-volatility",
        api_version="1.60.0",
        instrument="US_QQQ",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 2),
        request_json="{}",
        response_hash="hash",
        retrieved_at=now,
        status="PARSE_FAILED",
        cache_policy="historical",
        correlation_id="cid",
        quality_status="UNKNOWN",
        error_code="AMBIGUOUS_DUPLICATE_DATE",
    )
    row = catalog.get("abc")
    assert row["status"] == "PARSE_FAILED"
    assert row["error_code"] == "AMBIGUOUS_DUPLICATE_DATE"
    catalog.close()


def test_failed_parse_never_becomes_completed_cache(tmp_path):
    payload = [
        {
            "date": "2020-01-02",
            "spot": 100.0,
            "maturities": ["3M"],
            "strikes": ["100.0"],
            "forwardCurve": [101.0],
            "zcCurve": [0.99],
            "matrix": [[0.2]],
        },
        {
            "date": "2020-01-02",
            "spot": 101.0,
            "maturities": ["3M"],
            "strikes": ["100.0"],
            "forwardCurve": [101.0],
            "zcCurve": [0.99],
            "matrix": [[0.2]],
        },
    ]
    client = _bare_client(tmp_path)
    client._request_with_retry = lambda *_args, **_kwargs: payload

    request = _request()
    with pytest.raises(CortexError) as exc_info:
        client.get_implied_volatility(request)
    assert exc_info.value.code == ErrorCode.AMBIGUOUS_DUPLICATE_DATE
    row = client._catalog.get(request.request_hash("1.60.0"))
    assert row["status"] == "PARSE_FAILED"
    assert row["error_code"] == "AMBIGUOUS_DUPLICATE_DATE"
    assert client._raw.exists("implied-volatility", request.request_hash("1.60.0"))
    client._catalog.close()


def test_successful_pipeline_completes_then_hits_verified_cache(tmp_path):
    payload = [
        {
            "date": "2020-01-02",
            "spot": 100.0,
            "maturities": ["3M"],
            "strikes": ["100.0"],
            "forwardCurve": [101.0],
            "zcCurve": [0.99],
            "matrix": [[0.2]],
        }
    ]
    calls = 0

    def fetch(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return payload

    client = _bare_client(tmp_path)
    client._request_with_retry = fetch

    request = _request()
    observations, first = client.get_implied_volatility(request)
    cached_observations, second = client.get_implied_volatility(request)
    row = client._catalog.get(request.request_hash("1.60.0"))

    assert observations == cached_observations
    assert first.cache_status == "live"
    assert second.cache_status == "hit"
    assert calls == 1
    assert row["status"] == "COMPLETED"
    assert row["error_code"] is None
    assert (
        tmp_path / "normalized" / "implied_vol" / f"{request.request_hash('1.60.0')}.parquet"
    ).exists()
    client._catalog.close()


def test_successful_pipeline_records_all_correctness_states(tmp_path):
    payload = [
        {
            "date": "2020-01-02",
            "spot": 100.0,
            "maturities": ["3M"],
            "strikes": ["100.0"],
            "forwardCurve": [101.0],
            "zcCurve": [0.99],
            "matrix": [[0.2]],
        }
    ]

    class RecordingCatalog(Catalog):
        def __init__(self, path):
            self.statuses = []
            super().__init__(path)

        def upsert(self, **kwargs):
            self.statuses.append(kwargs["status"])
            return super().upsert(**kwargs)

    client = _bare_client(tmp_path)
    client._catalog = RecordingCatalog(tmp_path / "catalog.duckdb")
    client._request_with_retry = lambda *_args, **_kwargs: payload

    client.get_implied_volatility(_request())

    assert client._catalog.statuses == [
        "FETCHED",
        "SCHEMA_VALIDATED",
        "NORMALIZED",
        "COMPLETED",
    ]
    client._catalog.close()


def _covering_payload(dates):
    return [
        {
            "date": day,
            "code": "US_QQQ",
            "maturityRule": "sliding",
            "strikeRule": "relative_to_forward",
            "volatilityConvention": "bsVol",
            "spot": 100.0,
            "maturities": ["3M"],
            "strikes": ["100.0"],
            "forwardCurve": [101.0],
            "zcCurve": [0.99],
            "matrix": [[0.2]],
        }
        for day in dates
    ]


def _ranged_request(start, end):
    return ImpliedVolRequest(
        code="US_QQQ",
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
        low_strike=100.0,
        high_strike=100.0,
        low_maturity="3M",
        high_maturity="3M",
        strike_rule="relative_to_forward",
    )


def test_a_narrower_range_is_served_from_a_stored_wider_one(tmp_path):
    """Fetching two years then six months of it must not call upstream twice."""
    calls = []
    client = _bare_client(tmp_path)
    client._request_with_retry = lambda *args, **kwargs: (
        calls.append(kwargs.get("json_body")) or _covering_payload(
            ["2024-01-02", "2024-06-03", "2025-01-02", "2025-06-02"]
        )
    )

    wide, _ = client.get_implied_volatility(_ranged_request("2024-01-01", "2025-12-31"))
    assert len(calls) == 1
    assert len(wide) == 4

    narrow, result = client.get_implied_volatility(_ranged_request("2025-01-01", "2025-12-31"))
    assert len(calls) == 1, "the covering range should have answered this"
    assert result.cache_status == "cache"
    # Only the requested window comes back, not the surplus the wider entry holds.
    assert [str(observation.date) for observation in narrow] == ["2025-01-02", "2025-06-02"]


def test_a_range_reaching_outside_the_stored_one_still_fetches(tmp_path):
    calls = []
    client = _bare_client(tmp_path)
    client._request_with_retry = lambda *args, **kwargs: (
        calls.append(kwargs.get("json_body")) or _covering_payload(["2025-01-02"])
    )

    client.get_implied_volatility(_ranged_request("2025-01-01", "2025-06-30"))
    assert len(calls) == 1
    # Reaching past the stored end date is not covered, so it must go upstream.
    client.get_implied_volatility(_ranged_request("2025-01-01", "2025-12-31"))
    assert len(calls) == 2


def test_a_different_coordinate_is_never_served_from_another_ones_range(tmp_path):
    calls = []
    client = _bare_client(tmp_path)
    client._request_with_retry = lambda *args, **kwargs: (
        calls.append(kwargs.get("json_body")) or _covering_payload(["2025-01-02"])
    )

    client.get_implied_volatility(_ranged_request("2025-01-01", "2025-12-31"))
    assert len(calls) == 1

    other = _ranged_request("2025-02-01", "2025-11-30").model_copy(update={"low_strike": 95.0, "high_strike": 95.0})
    try:
        client.get_implied_volatility(other)
    except CortexError:
        pass  # the stub payload does not carry that strike; the point is that it fetched
    assert len(calls) == 2, "a different strike must not reuse another coordinate's range"


def test_concurrent_identical_requests_make_one_upstream_call(tmp_path):
    """Realized vol, spot and forward share one carrier and refresh together."""
    calls = []
    # Released only once all three callers are about to ask, so the requests genuinely
    # overlap instead of the second and third arriving after the first already finished.
    ready = threading.Barrier(3)
    client = _bare_client(tmp_path)

    def slow_fetch(*args, **kwargs):
        calls.append(kwargs.get("json_body"))
        time.sleep(0.3)  # hold the call open while the other two are queued behind it
        return _covering_payload(["2025-01-02"])

    client._request_with_retry = slow_fetch
    request = _ranged_request("2025-01-01", "2025-12-31")

    errors = []

    def run():
        try:
            ready.wait(timeout=5)
            client.get_implied_volatility(request)
        except Exception as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert len(calls) == 1, f"expected one upstream call, got {len(calls)}"


def test_force_refresh_bypasses_a_covering_range(tmp_path):
    """The escape hatch for upstream restating history the wider entry already holds."""
    calls = []
    client = _bare_client(tmp_path)
    client._request_with_retry = lambda *args, **kwargs: (
        calls.append(kwargs.get("json_body")) or _covering_payload(["2025-01-02", "2025-06-02"])
    )

    client.get_implied_volatility(_ranged_request("2024-01-01", "2025-12-31"))
    assert len(calls) == 1

    narrow = _ranged_request("2025-01-01", "2025-12-31")
    _, cached = client.get_implied_volatility(narrow)
    assert len(calls) == 1
    assert cached.cache_status == "cache"

    _, fresh = client.get_implied_volatility(narrow, force_refresh=True)
    assert len(calls) == 2, "force_refresh must reach upstream even when a range covers it"
    assert fresh.cache_status == "live"
