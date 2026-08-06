"""Atomic storage and cache-state regression tests."""

from datetime import UTC, date, datetime

import pytest

from app.clients.cortex.client import CortexClient
from app.clients.cortex.errors import CortexError, ErrorCode
from app.domain.requests import ImpliedVolRequest
from app.storage.catalog import Catalog
from app.storage.normalized_store import NormalizedStore
from app.storage.raw_store import RawStore


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
    client = CortexClient.__new__(CortexClient)
    client._mode = "live"
    client.api_version = "1.60.0"
    client._catalog = Catalog(tmp_path / "catalog.duckdb")
    client._raw = RawStore(tmp_path / "raw")
    client._normalized = NormalizedStore(tmp_path / "normalized")
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

    client = CortexClient.__new__(CortexClient)
    client._mode = "live"
    client.api_version = "1.60.0"
    client._catalog = Catalog(tmp_path / "catalog.duckdb")
    client._raw = RawStore(tmp_path / "raw")
    client._normalized = NormalizedStore(tmp_path / "normalized")
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

    client = CortexClient.__new__(CortexClient)
    client._mode = "live"
    client.api_version = "1.60.0"
    client._catalog = RecordingCatalog(tmp_path / "catalog.duckdb")
    client._raw = RawStore(tmp_path / "raw")
    client._normalized = NormalizedStore(tmp_path / "normalized")
    client._request_with_retry = lambda *_args, **_kwargs: payload

    client.get_implied_volatility(_request())

    assert client._catalog.statuses == [
        "FETCHED",
        "SCHEMA_VALIDATED",
        "NORMALIZED",
        "COMPLETED",
    ]
    client._catalog.close()
