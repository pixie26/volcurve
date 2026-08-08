"""Deep regression tests for Step 7 cache/history semantics."""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta

import pytest

from app.api.presenters import _source_info
from app.clients.cortex.client import CortexClient, FetchResult
from app.clients.cortex.errors import CortexError, ErrorCode
from app.clients.cortex.serializers import serialize_volatility_request, volatility_coordinate_hash
from app.domain.observations import QualityFlag, StandardObservation
from app.domain.requests import FixedStrikeRequest, SlidingDeltaRequest, SlidingMoneynessRequest
from app.storage import cache
from app.storage.catalog import Catalog
from app.storage.history import HistoricalStore
from app.storage.normalized_store import NormalizedStore
from app.storage.raw_store import RawStore


def obs(day: str, iv: float, *, strike_rule="relative_to_forward", strike=100.0):
    return StandardObservation(
        date=date.fromisoformat(day),
        instrument_code="US_QQQ",
        spot=500.0,
        target_maturity="3M",
        returned_maturity="3M",
        strike_rule=strike_rule,
        target_strike=strike,
        returned_strike=strike,
        forward=501.0,
        discount_factor=0.99,
        raw_implied_vol=iv,
        implied_vol=iv,
        quality_flags=[QualityFlag.OK],
    )


def request(start: str, end: str):
    return SlidingMoneynessRequest(
        code="US_QQQ",
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
        low_strike=100,
        high_strike=100,
        low_maturity="3M",
        high_maturity="3M",
    )


def bare_client(tmp_path, history=True):
    client = CortexClient.__new__(CortexClient)
    client._mode = "live"
    client.api_version = "1.60.0"
    client._catalog = Catalog(tmp_path / "catalog.duckdb")
    client._raw = RawStore(tmp_path / "raw")
    client._normalized = NormalizedStore(tmp_path / "normalized")
    client._history = HistoricalStore(tmp_path / "history.duckdb") if history else None
    client._inflight = {}
    client._inflight_guard = threading.Lock()
    return client


def payload(days_and_iv):
    return [
        {
            "date": day,
            "code": "US_QQQ",
            "maturityRule": "sliding",
            "strikeRule": "relative_to_forward",
            "volatilityConvention": "bsVol",
            "spot": 500.0,
            "maturities": ["3M"],
            "strikes": ["100.0"],
            "forwardCurve": [501.0],
            "zcCurve": [0.99],
            "matrix": [[iv]],
        }
        for day, iv in days_and_iv
    ]


def test_cache_freshness_is_rolling_eight_hours():
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    assert cache.is_fresh(now - timedelta(hours=7, minutes=59), "historical", now)
    assert not cache.is_fresh(now - timedelta(hours=8), "historical", now)
    assert not cache.is_fresh(now - timedelta(hours=8), "intraday", now)


def test_history_stitches_overlap_and_newer_points_win(tmp_path):
    store = HistoricalStore(tmp_path / "history.duckdb")
    t0 = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=1)
    store.upsert_series(
        coordinate_hash="coord",
        request_hash="old",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 1),
        retrieved_at=t0,
        response_hash="old-hash",
        correlation_id="old-cid",
        observations=[obs("2026-01-15", .20), obs("2026-02-15", .21), obs("2026-03-01", .22)],
    )
    store.upsert_series(
        coordinate_hash="coord",
        request_hash="new",
        start_date=date(2026, 2, 1),
        end_date=date(2026, 4, 1),
        retrieved_at=t1,
        response_hash="new-hash",
        correlation_id="new-cid",
        observations=[obs("2026-02-15", .25), obs("2026-03-01", .22), obs("2026-04-01", .23)],
    )
    loaded = store.load_series(
        coordinate_hash="coord",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 4, 1),
    )
    assert loaded is not None
    assert [(str(x.date), x.implied_vol) for x in loaded.observations] == [
        ("2026-01-15", .20),
        ("2026-02-15", .25),
        ("2026-03-01", .22),
        ("2026-04-01", .23),
    ]
    assert store.revision_types("coord") == ["CHANGED"]


def test_history_newer_fetch_removal_is_revision_not_old_value_resurrection(tmp_path):
    store = HistoricalStore(tmp_path / "history.duckdb")
    t0 = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=1)
    store.upsert_series(
        coordinate_hash="coord", request_hash="a",
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), retrieved_at=t0,
        response_hash="a", correlation_id="a", observations=[obs("2026-01-15", .20)],
    )
    store.upsert_series(
        coordinate_hash="coord", request_hash="b",
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), retrieved_at=t1,
        response_hash="b", correlation_id="b", observations=[],
    )
    assert store.point_count("coord") == 0
    assert store.revision_types("coord") == ["REMOVED"]


def test_late_older_write_never_rolls_history_back(tmp_path):
    store = HistoricalStore(tmp_path / "history.duckdb")
    newer = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    older = newer - timedelta(hours=2)
    store.upsert_series(
        coordinate_hash="coord", request_hash="new",
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), retrieved_at=newer,
        response_hash="new", correlation_id="new", observations=[obs("2026-01-15", .30)],
    )
    store.upsert_series(
        coordinate_hash="coord", request_hash="old",
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), retrieved_at=older,
        response_hash="old", correlation_id="old", observations=[obs("2026-01-15", .20)],
    )
    loaded = store.load_series(
        coordinate_hash="coord", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
    )
    assert loaded is not None and loaded.observations[0].implied_vol == .30
    assert store.revision_count("coord") == 0


def test_fresh_coverage_can_be_union_of_multiple_fetches(tmp_path):
    store = HistoricalStore(tmp_path / "history.duckdb")
    now = datetime.now(UTC)
    store.upsert_series(
        coordinate_hash="coord", request_hash="a",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 15), retrieved_at=now,
        response_hash="a", correlation_id="a", observations=[obs("2026-01-15", .20)],
    )
    store.upsert_series(
        coordinate_hash="coord", request_hash="b",
        start_date=date(2026, 2, 16), end_date=date(2026, 4, 1), retrieved_at=now,
        response_hash="b", correlation_id="b", observations=[obs("2026-03-15", .21)],
    )
    assert store.has_coverage(
        coordinate_hash="coord", start_date=date(2026, 1, 1), end_date=date(2026, 4, 1),
        fresh_after=now - timedelta(hours=8),
    )


def test_client_uses_point_stitching_without_third_upstream_request(tmp_path):
    client = bare_client(tmp_path)
    calls = []

    def fetch(*_args, **kwargs):
        body = kwargs["json_body"]
        calls.append((body["startDate"], body["endDate"]))
        if body["startDate"] == "2026-01-01":
            return payload([("2026-01-15", .20), ("2026-02-15", .21), ("2026-03-01", .22)])
        return payload([("2026-02-15", .25), ("2026-03-01", .22), ("2026-04-01", .23)])

    client._request_with_retry = fetch
    client.get_implied_volatility(request("2026-01-01", "2026-03-01"))
    client.get_implied_volatility(request("2026-02-01", "2026-04-01"), force_refresh=True)
    combined, result = client.get_implied_volatility(request("2026-01-01", "2026-04-01"))
    assert len(calls) == 2
    assert result.cache_status == "archive"
    assert [(str(x.date), x.implied_vol) for x in combined] == [
        ("2026-01-15", .20), ("2026-02-15", .25), ("2026-03-01", .22), ("2026-04-01", .23)
    ]


def test_delta_is_historical_but_absolute_strike_is_not():
    delta = SlidingDeltaRequest(
        code="US_QQQ", start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        low_delta_strike="p25.0", high_delta_strike="p25.0", low_maturity="3M", high_maturity="3M",
    )
    fixed = FixedStrikeRequest(
        code="US_QQQ", start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        maturity_rule="listed", low_fixed_strike=500, high_fixed_strike=500,
        low_fixed_maturity=date(2026, 3, 20), high_fixed_maturity=date(2026, 3, 20),
    )
    assert CortexClient._history_eligible(delta)
    assert not CortexClient._history_eligible(fixed)


def test_stale_archive_fallback_on_unavailable_and_no_data(tmp_path):
    for code in (ErrorCode.UPSTREAM_UNAVAILABLE, ErrorCode.NO_DATA):
        client = bare_client(tmp_path / code.value)
        req = request("2026-01-01", "2026-01-31")
        coord = volatility_coordinate_hash(req, client.api_version)
        old = datetime.now(UTC) - timedelta(hours=9)
        client._history.upsert_series(
            coordinate_hash=coord, request_hash="old", start_date=req.start_date, end_date=req.end_date,
            retrieved_at=old, response_hash="old", correlation_id="old-cid",
            observations=[obs("2026-01-15", .20)],
        )
        client._request_with_retry = lambda *_a, code=code, **_k: (_ for _ in ()).throw(
            CortexError(code, "refresh failed")
        )
        observations, result = client.get_implied_volatility(req)
        assert observations[0].implied_vol == .20
        assert result.cache_status == "stale"
        assert result.stale_reason.startswith(code.value)
        assert result.refresh_attempted_at is not None


def test_invalid_or_entitlement_errors_never_use_stale_archive(tmp_path):
    for code in (ErrorCode.INVALID_REQUEST, ErrorCode.ENTITLEMENT_DENIED, ErrorCode.INVALID_SCHEMA):
        client = bare_client(tmp_path / code.value)
        req = request("2026-01-01", "2026-01-31")
        coord = volatility_coordinate_hash(req, client.api_version)
        old = datetime.now(UTC) - timedelta(hours=9)
        client._history.upsert_series(
            coordinate_hash=coord, request_hash="old", start_date=req.start_date, end_date=req.end_date,
            retrieved_at=old, response_hash="old", correlation_id="old-cid",
            observations=[obs("2026-01-15", .20)],
        )
        client._request_with_retry = lambda *_a, code=code, **_k: (_ for _ in ()).throw(
            CortexError(code, "must surface")
        )
        with pytest.raises(CortexError) as raised:
            client.get_implied_volatility(req)
        assert raised.value.code == code


def test_new_wider_live_request_compacts_fully_covered_old_cache(tmp_path):
    client = bare_client(tmp_path)

    def fetch(*_args, **kwargs):
        body = kwargs["json_body"]
        if body["endDate"] == "2026-02-28":
            return payload([("2026-01-15", .20), ("2026-02-15", .21)])
        return payload([("2026-01-15", .20), ("2026-02-15", .22), ("2026-03-15", .23)])

    client._request_with_retry = fetch
    old_req = request("2026-01-01", "2026-02-28")
    wide_req = request("2026-01-01", "2026-03-31")
    client.get_implied_volatility(old_req)
    old_hash = old_req.request_hash(client.api_version)
    assert client._raw.exists("implied-volatility", old_hash)
    client.get_implied_volatility(wide_req, force_refresh=True)
    assert client._catalog.get(old_hash) is None
    assert not client._raw.exists("implied-volatility", old_hash)
    assert not (tmp_path / "normalized" / "implied_vol" / f"{old_hash}.parquet").exists()


def test_partial_overlap_does_not_delete_old_full_request_file(tmp_path):
    client = bare_client(tmp_path)

    def fetch(*_args, **kwargs):
        body = kwargs["json_body"]
        if body["startDate"] == "2026-01-01":
            return payload([("2026-01-15", .20), ("2026-02-15", .21)])
        return payload([("2026-02-15", .22), ("2026-03-15", .23)])

    client._request_with_retry = fetch
    old_req = request("2026-01-01", "2026-03-01")
    overlap = request("2026-02-01", "2026-04-01")
    client.get_implied_volatility(old_req)
    old_hash = old_req.request_hash(client.api_version)
    client.get_implied_volatility(overlap, force_refresh=True)
    assert client._catalog.get(old_hash) is not None
    assert client._raw.exists("implied-volatility", old_hash)


def test_source_info_exposes_stale_provenance():
    req = request("2026-01-01", "2026-01-31")
    old = datetime(2026, 8, 8, 1, 0, tzinfo=UTC)
    result = FetchResult(
        payload=[], cache_status="stale", correlation_id="old-cid", retrieved_at=old,
        oldest_retrieved_at=old, newest_retrieved_at=old,
        source_request_ids=["old-cid"], stale_reason="UPSTREAM_UNAVAILABLE: failed",
        refresh_attempted_at=old + timedelta(hours=9), refresh_correlation_id="refresh-cid",
    )
    info = _source_info(type("Client", (), {"api_version": "1.60.0"})(), req, [result], req.start_date)
    assert info.isStale is True
    assert info.staleReason.startswith("UPSTREAM_UNAVAILABLE")
    assert info.refreshRequestId == "refresh-cid"
    assert info.oldestRetrievedAt == old



def _complete_raw_cache(client, req, raw_payload, retrieved_at):
    request_hash = req.request_hash(client.api_version)
    coordinate_hash = volatility_coordinate_hash(req, client.api_version)
    body = serialize_volatility_request(req)
    response_hash = RawStore.payload_hash(raw_payload)
    client._raw.save("implied-volatility", request_hash, raw_payload)
    client._catalog.upsert(
        request_hash=request_hash,
        endpoint="implied-volatility",
        api_version=client.api_version,
        instrument=req.code,
        start_date=req.start_date,
        end_date=req.end_date,
        request_json=__import__("json").dumps(body, sort_keys=True),
        response_hash=response_hash,
        retrieved_at=retrieved_at,
        status="COMPLETED",
        cache_policy="historical",
        correlation_id=request_hash,
        quality_status="OK",
        coordinate_hash=coordinate_hash,
    )
    return request_hash


def test_newer_wider_raw_cache_beats_older_exact_cache(tmp_path):
    client = bare_client(tmp_path, history=False)
    narrow = request("2026-02-01", "2026-03-01")
    wide = request("2026-01-01", "2026-04-01")
    now = datetime.now(UTC)
    _complete_raw_cache(client, narrow, payload([("2026-02-15", .20)]), now - timedelta(hours=2))
    wide_hash = _complete_raw_cache(
        client,
        wide,
        payload([("2026-01-15", .19), ("2026-02-15", .25), ("2026-03-15", .23)]),
        now - timedelta(hours=1),
    )
    chosen = client._best_cached_result(
        narrow,
        request_hash=narrow.request_hash(client.api_version),
        coordinate_hash=volatility_coordinate_hash(narrow, client.api_version),
        require_fresh=True,
    )
    assert chosen is not None
    assert chosen.source_request_hash == wide_hash
    assert chosen.cache_status == "cache"


def test_cache_older_than_eight_hours_reaches_upstream(tmp_path):
    client = bare_client(tmp_path, history=False)
    req = request("2026-01-01", "2026-01-31")
    _complete_raw_cache(
        client,
        req,
        payload([("2026-01-15", .20)]),
        datetime.now(UTC) - timedelta(hours=8, minutes=1),
    )
    calls = []
    client._request_with_retry = lambda *_a, **_k: (
        calls.append(1) or payload([("2026-01-15", .21)])
    )
    observations, result = client.get_implied_volatility(req)
    assert calls == [1]
    assert result.cache_status == "live"
    assert observations[0].implied_vol == .21


def test_delta_series_is_actually_archived_and_reused(tmp_path):
    client = bare_client(tmp_path)
    req = SlidingDeltaRequest(
        code="US_QQQ",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        low_delta_strike="p25.0",
        high_delta_strike="p25.0",
        low_maturity="3M",
        high_maturity="3M",
    )
    delta_payload = [{
        "date": "2026-01-15",
        "code": "US_QQQ",
        "maturityRule": "sliding",
        "strikeRule": "delta",
        "volatilityConvention": "bsVol",
        "spot": 500.0,
        "maturities": ["3M"],
        "strikes": ["p25.0"],
        "forwardCurve": [501.0],
        "zcCurve": [0.99],
        "matrix": [[0.27]],
    }]
    calls = []
    client._request_with_retry = lambda *_a, **_k: calls.append(1) or delta_payload
    first, _ = client.get_implied_volatility(req)
    second, result = client.get_implied_volatility(req)
    assert len(calls) == 1
    assert first[0].implied_vol == second[0].implied_vol == .27
    assert result.cache_status == "archive"


def test_live_200_no_data_can_fall_back_to_stale_archive(tmp_path):
    client = bare_client(tmp_path)
    req = request("2026-01-01", "2026-01-31")
    coord = volatility_coordinate_hash(req, client.api_version)
    old = datetime.now(UTC) - timedelta(hours=9)
    client._history.upsert_series(
        coordinate_hash=coord,
        request_hash="old",
        start_date=req.start_date,
        end_date=req.end_date,
        retrieved_at=old,
        response_hash="old",
        correlation_id="old-cid",
        observations=[obs("2026-01-15", .20)],
        api_version=client.api_version,
        coordinate_json="{}",
    )
    client._request_with_retry = lambda *_a, **_k: []
    observations, result = client.get_implied_volatility(req)
    assert observations[0].implied_vol == .20
    assert result.cache_status == "stale"
    assert result.stale_reason.startswith("NO_DATA")
    assert result.refresh_correlation_id


def test_history_coordinate_hash_remains_self_describing_after_cache_compaction(tmp_path):
    client = bare_client(tmp_path)
    req = request("2026-01-01", "2026-01-31")
    client._request_with_retry = lambda *_a, **_k: payload([("2026-01-15", .20)])
    client.get_implied_volatility(req)
    coord = volatility_coordinate_hash(req, client.api_version)
    metadata = client._history.coordinate_metadata(coord)
    assert metadata is not None
    assert metadata["api_version"] == client.api_version
    wire = __import__("json").loads(metadata["coordinate_json"])
    assert "startDate" not in wire and "endDate" not in wire
    assert wire["code"] == "US_QQQ"
    assert wire["lowStrike"] == wire["highStrike"] == "100_0"


def test_expired_nonhistorical_relative_surface_cache_is_pruned(tmp_path):
    client = bare_client(tmp_path)
    surface = SlidingMoneynessRequest(
        code="US_QQQ",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        low_strike=95,
        high_strike=105,
        low_maturity="1M",
        high_maturity="3M",
    )
    old_hash = _complete_raw_cache(
        client,
        surface,
        payload([("2026-01-15", .20)]),
        datetime.now(UTC) - timedelta(hours=9),
    )
    assert client._raw.exists("implied-volatility", old_hash)
    client._prune_expired_request_files(datetime.now(UTC))
    assert client._catalog.get(old_hash) is None
    assert not client._raw.exists("implied-volatility", old_hash)


def test_expired_unmigrated_exact_series_raw_is_retained_for_upgrade_safety(tmp_path):
    client = bare_client(tmp_path)
    req = request("2026-01-01", "2026-01-31")
    old_hash = _complete_raw_cache(
        client,
        req,
        payload([("2026-01-15", .20)]),
        datetime.now(UTC) - timedelta(hours=9),
    )
    client._prune_expired_request_files(datetime.now(UTC))
    assert client._catalog.get(old_hash) is not None
    assert client._raw.exists("implied-volatility", old_hash)
