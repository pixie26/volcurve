"""Cortex DataHub client.

Responsibilities:
- HTTP stability: connect/read timeouts, 429 Retry-After, 5xx exponential
  backoff, bounded retries, per-request correlation ID;
- no retry on 400 / 403 / schema-invalid; 401 triggers one token refresh
  and one retry;
- short request cache: verified raw responses are reusable for eight hours;
- revision-aware historical library: exact percentage/delta series are stitched by date,
  while absolute/listed strike universes remain short-lived cache only;
- fixture mode (CORTEX_MODE=fixture): serve sanitized fixtures instead of
  calling BNP, so the app and tests run offline.
"""

from __future__ import annotations

import json
import logging
import math
import random
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from app.clients.cortex.auth import AuthenticationManager
from app.clients.cortex.errors import CortexError, ErrorCode
from app.clients.cortex.parser import (
    canonicalize_surface,
    normalize_surface,
    normalize_surface_snapshots,
)
from app.clients.cortex.serializers import (
    serialize_volatility_request,
    volatility_coordinate_hash,
    volatility_request_hash,
)
from app.config import Settings
from app.domain.disclosures import HTTP_MAX_RETRIES, HTTP_MAX_RETRY_AFTER_SECONDS
from app.domain.instruments import Instrument
from app.domain.observations import StandardObservation
from app.domain.requests import (
    FixedStrikeRequest,
    ListedMaturityMoneynessRequest,
    SlidingDeltaRequest,
    SlidingMoneynessRequest,
    VolatilityRequest,
)
from app.domain.surfaces import StandardSurfaceObservation
from app.security.redaction import redact, register_secret
from app.storage import cache as cache_policy_mod
from app.storage.catalog import Catalog
from app.storage.history import HistoricalStore
from app.storage.normalized_store import NormalizedStore
from app.storage.raw_store import RawStore

logger = logging.getLogger("cortex.client")

_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 120.0
_MAX_RETRIES = HTTP_MAX_RETRIES
_BACKOFF_BASE = 0.5
_MAX_RETRY_AFTER = float(HTTP_MAX_RETRY_AFTER_SECONDS)
_MAX_CONCURRENT_UPSTREAM_REQUESTS = 4
# Process-wide for the supported single-worker deployment. Every actual Cortex HTTP attempt
# (including Playground and instruments) must take one permit; cache/fixture paths never do.
_UPSTREAM_SEMAPHORE = threading.BoundedSemaphore(_MAX_CONCURRENT_UPSTREAM_REQUESTS)
_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


@dataclass
class FetchResult:
    payload: list
    # live | hit (exact raw cache) | cache (covering raw cache) | archive (stitched point
    # history) | stale (archive/raw fallback after a failed refresh) | fixture.
    cache_status: str
    correlation_id: str
    retrieved_at: datetime
    request_body: dict | None = None
    source_request_hash: str | None = None
    oldest_retrieved_at: datetime | None = None
    newest_retrieved_at: datetime | None = None
    source_request_ids: list[str] | None = None
    stale_reason: str | None = None
    refresh_attempted_at: datetime | None = None
    refresh_correlation_id: str | None = None


def load_api_version(project_root: Path) -> str:
    spec = project_root / "schemas" / "cortex-openapi.yaml"
    if spec.exists():
        for line in spec.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("version:"):
                return line.split(":", 1)[1].strip()
    return "1.60.0"


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Parse RFC Retry-After seconds or HTTP-date and cap blocking time."""
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        seconds = (retry_at - current).total_seconds()
    if not math.isfinite(seconds):
        return None
    return min(max(seconds, 0.0), _MAX_RETRY_AFTER)


def _within_requested_range(
    observations: list, request: VolatilityRequest, result: FetchResult
) -> list:
    """Trim the surplus a wider cached range carries, and only that.

    Only a covering-range reuse can hold dates outside the window: a live response and an
    exact-hash hit are already the right shape, and a fixture is a canned sample whose
    dates deliberately have nothing to do with the range asked for.
    """
    if result.cache_status != "cache":
        return observations
    return [
        observation
        for observation in observations
        if request.start_date <= observation.date <= request.end_date
    ]


class _InflightFetch:
    """The shared state of one upstream call several callers are waiting on.

    `waiters` is refcounted so the entry disappears the moment the burst is over: this
    coalesces concurrent duplicates without becoming a second, unexpiring cache layer
    that would outlive the freshness policy.
    """

    __slots__ = ("lock", "result", "waiters")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.result: FetchResult | None = None
        self.waiters = 0


class CortexClient:
    def __init__(
        self,
        settings: Settings,
        auth: AuthenticationManager | None = None,
        catalog: Catalog | None = None,
        raw_store: RawStore | None = None,
        normalized_store: NormalizedStore | None = None,
    ):
        self._settings = settings
        self._mode = settings.cortex_mode
        self._auth = auth or AuthenticationManager(settings)
        self._catalog = catalog or Catalog(settings.duckdb_path)
        self._raw = raw_store or RawStore(settings.raw_dir)
        self._normalized = normalized_store or NormalizedStore(settings.normalized_dir)
        self._history = HistoricalStore(settings.history_duckdb_path)
        # One entry per in-flight request hash: concurrent identical requests wait for the
        # first instead of each making the same upstream call.
        self._inflight: dict[str, _InflightFetch] = {}
        self._inflight_guard = threading.Lock()
        from app.config import PROJECT_ROOT

        self.api_version = load_api_version(PROJECT_ROOT)
        register_secret(settings.bnp_client_id)
        register_secret(settings.bnp_client_secret)

    # ------------------------------------------------------------------ public

    def get_instruments(self, instrument_type: str = "equity") -> list[Instrument]:
        instruments, _result = self.get_instruments_with_result(instrument_type)
        return instruments

    def get_instruments_with_result(
        self, instrument_type: str = "equity"
    ) -> tuple[list[Instrument], FetchResult]:
        if self._mode == "fixture":
            data = self._load_fixture("instruments_equity.json")
            cached = None
            result = FetchResult(data, "fixture", "fixture", datetime.now(UTC))
        else:
            endpoint = "instruments"
            request_hash = f"instruments_{instrument_type}_{self.api_version}"
            cached = self._try_cache(endpoint, request_hash)
            if cached is not None:
                data = cached.payload
                result = cached
            else:
                data = self._request_with_retry(
                    "GET",
                    "/v1/instruments",
                    params={"type": instrument_type},
                    correlation_id=request_hash,
                )
                retrieved_at = datetime.now(UTC)
                self._persist_fetched(
                    endpoint,
                    request_hash,
                    data,
                    "intraday",
                    instrument_type,
                    retrieved_at=retrieved_at,
                )
                result = FetchResult(data, "live", request_hash, retrieved_at, source_request_hash=request_hash)

        try:
            instruments = [Instrument.model_validate(item) for item in data]
        except Exception as exc:
            if self._mode != "fixture":
                self._record_state(
                    request_hash=request_hash,
                    endpoint="instruments",
                    instrument=instrument_type,
                    retrieved_at=result.retrieved_at,
                    status="INVALID_SCHEMA",
                    policy="intraday",
                    correlation_id=request_hash,
                    response_hash=RawStore.payload_hash(data),
                    error_code=ErrorCode.INVALID_SCHEMA.value,
                )
            raise CortexError(ErrorCode.INVALID_SCHEMA, "instruments 响应结构校验失败") from exc

        if self._mode != "fixture" and cached is None:
            try:
                self._normalized.save_instruments(data)
            except Exception as exc:
                self._record_state(
                    request_hash=request_hash,
                    endpoint=endpoint,
                    instrument=instrument_type,
                    retrieved_at=retrieved_at,
                    status="STORAGE_FAILED",
                    policy="intraday",
                    correlation_id=request_hash,
                    response_hash=RawStore.payload_hash(data),
                    error_code=ErrorCode.STORAGE_FAILED.value,
                )
                raise CortexError(ErrorCode.STORAGE_FAILED, "instruments 标准化存储失败") from exc
            self._record_state(
                request_hash=request_hash,
                endpoint=endpoint,
                instrument=instrument_type,
                retrieved_at=retrieved_at,
                status="COMPLETED",
                policy="intraday",
                correlation_id=request_hash,
                response_hash=RawStore.payload_hash(data),
                quality_status="OK",
            )
        return instruments, result

    @staticmethod
    def _history_eligible(request: VolatilityRequest) -> bool:
        """Long-lived history is only for exact percentage-moneyness or delta series."""
        if isinstance(request, SlidingMoneynessRequest):
            return (
                request.low_strike == request.high_strike
                and request.low_maturity == request.high_maturity
            )
        if isinstance(request, SlidingDeltaRequest):
            return (
                request.low_delta_strike is not None
                and request.low_delta_strike == request.high_delta_strike
                and request.low_maturity is not None
                and request.low_maturity == request.high_maturity
            )
        if isinstance(request, ListedMaturityMoneynessRequest):
            return (
                request.low_strike == request.high_strike
                and request.low_fixed_maturity is not None
                and request.low_fixed_maturity == request.high_fixed_maturity
            )
        # Absolute/fixed strikes can have very high cardinality and are deliberately
        # short-cache only, regardless of whether the maturity rule is fixed or listed.
        return not isinstance(request, FixedStrikeRequest) and False

    def _history_store(self) -> HistoricalStore | None:
        # A few low-level tests intentionally build a client with __new__.  Production
        # clients always own the store, while those tests can opt in explicitly.
        return getattr(self, "_history", None)

    def _load_history_result(
        self,
        request: VolatilityRequest,
        coordinate_hash: str,
        *,
        fresh_after: datetime | None,
        stale_error: CortexError | None = None,
    ) -> tuple[list[StandardObservation], FetchResult] | None:
        history = self._history_store()
        if history is None:
            return None
        loaded = history.load_series(
            coordinate_hash=coordinate_hash,
            start_date=request.start_date,
            end_date=request.end_date,
            fresh_after=fresh_after,
        )
        if loaded is None:
            return None
        stale = stale_error is not None
        source_ids = loaded.correlation_ids or ["historical-archive"]
        refresh_id = getattr(stale_error, "correlation_id", None) if stale_error else None
        result = FetchResult(
            payload=[],
            cache_status="stale" if stale else "archive",
            correlation_id=source_ids[0],
            retrieved_at=loaded.newest_retrieved_at,
            request_body=serialize_volatility_request(request),
            source_request_hash=None,
            oldest_retrieved_at=loaded.oldest_retrieved_at,
            newest_retrieved_at=loaded.newest_retrieved_at,
            source_request_ids=source_ids,
            stale_reason=(
                f"{stale_error.code.value}: {stale_error.message}" if stale_error else None
            ),
            refresh_attempted_at=datetime.now(UTC) if stale else None,
            refresh_correlation_id=refresh_id,
        )
        return loaded.observations, result

    def _archive_series(
        self,
        request: VolatilityRequest,
        *,
        request_hash: str,
        coordinate_hash: str,
        result: FetchResult,
        observations: list[StandardObservation],
    ) -> None:
        history = self._history_store()
        if history is None or result.source_request_hash != request_hash:
            return
        try:
            history.upsert_series(
                coordinate_hash=coordinate_hash,
                request_hash=request_hash,
                start_date=request.start_date,
                end_date=request.end_date,
                retrieved_at=result.retrieved_at,
                response_hash=RawStore.payload_hash(result.payload),
                correlation_id=result.correlation_id,
                observations=observations,
            )
        except Exception as exc:
            raise CortexError(ErrorCode.STORAGE_FAILED, "historical library 写入失败") from exc

    @staticmethod
    def _stale_fallback_allowed(exc: CortexError) -> bool:
        return exc.code in {
            ErrorCode.UPSTREAM_RATE_LIMITED,
            ErrorCode.UPSTREAM_UNAVAILABLE,
            ErrorCode.NO_DATA,
        }

    def get_implied_volatility(
        self, request: VolatilityRequest, *, force_refresh: bool = False
    ) -> tuple[list[StandardObservation], FetchResult]:
        request_hash = volatility_request_hash(request, self.api_version)
        coordinate_hash = volatility_coordinate_hash(request, self.api_version)
        eligible = self._mode != "fixture" and self._history_eligible(request)

        if eligible and not force_refresh:
            archived = self._load_history_result(
                request,
                coordinate_hash,
                fresh_after=cache_policy_mod.freshness_cutoff(),
            )
            if archived is not None:
                return archived

        try:
            request_hash, request_json, policy, result = self._fetch_implied_volatility(
                request, force_refresh=force_refresh
            )
        except CortexError as exc:
            if eligible and self._stale_fallback_allowed(exc):
                archived = self._load_history_result(
                    request, coordinate_hash, fresh_after=None, stale_error=exc
                )
                if archived is not None:
                    return archived
                raw_fallback = self._load_stale_raw_series(
                    request,
                    request_hash=request_hash,
                    coordinate_hash=coordinate_hash,
                    stale_error=exc,
                )
                if raw_fallback is not None:
                    return raw_fallback
            raise

        canonical = self._canonicalize_implied_volatility(
            request, request_hash, request_json, policy, result
        )
        try:
            observations = normalize_surface(canonical, request)
        except CortexError as exc:
            self._record_parse_failure(request, request_hash, request_json, policy, result, exc)
            raise
        observations = _within_requested_range(observations, request, result)
        if not observations:
            raise CortexError(ErrorCode.NO_DATA, "该日期区间内没有可用观测")
        self._finish_implied_volatility(
            request,
            request_hash,
            request_json,
            policy,
            result,
            observations,
            surface=False,
        )
        if eligible and result.cache_status in {"live", "hit"}:
            self._archive_series(
                request,
                request_hash=request_hash,
                coordinate_hash=coordinate_hash,
                result=result,
                observations=observations,
            )
            if result.cache_status == "live":
                self._compact_request_cache(
                    request,
                    request_hash=request_hash,
                    coordinate_hash=coordinate_hash,
                    retrieved_at=result.retrieved_at,
                )
                self._prune_expired_request_files(result.retrieved_at)
        return observations, result

    def get_implied_volatility_surface(
        self, request: VolatilityRequest, *, force_refresh: bool = False
    ) -> tuple[list[StandardSurfaceObservation], FetchResult]:
        """Return every requested coordinate without reducing ranges to one series."""
        request_hash, request_json, policy, result = self._fetch_implied_volatility(
            request, force_refresh=force_refresh
        )
        canonical = self._canonicalize_implied_volatility(
            request, request_hash, request_json, policy, result
        )
        try:
            observations = normalize_surface_snapshots(canonical, request)
        except CortexError as exc:
            self._record_parse_failure(request, request_hash, request_json, policy, result, exc)
            raise
        observations = _within_requested_range(observations, request, result)
        if not observations:
            raise CortexError(ErrorCode.NO_DATA, "该日期区间内没有可用 surface 观测")
        self._finish_implied_volatility(
            request,
            request_hash,
            request_json,
            policy,
            result,
            observations,
            surface=True,
        )
        if result.cache_status == "live":
            self._prune_expired_request_files(result.retrieved_at)
        return observations, result

    def _fetch_implied_volatility(
        self, request: VolatilityRequest, *, force_refresh: bool
    ) -> tuple[str, str, str, FetchResult]:
        request_hash = volatility_request_hash(request, self.api_version)
        coordinate_hash = volatility_coordinate_hash(request, self.api_version)
        wire_body = serialize_volatility_request(request)
        request_json = json.dumps(wire_body, sort_keys=True)
        policy = cache_policy_mod.cache_policy(request.end_date)
        if self._mode == "fixture":
            payload = self._load_volatility_fixture(request)
            result = FetchResult(payload, "fixture", "fixture", datetime.now(UTC))
        else:
            result = None
            if not force_refresh:
                result = self._best_cached_result(
                    request,
                    request_hash=request_hash,
                    coordinate_hash=coordinate_hash,
                    require_fresh=True,
                )
            if result is None:
                result = self._fetch_and_store(
                    request,
                    request_hash=request_hash,
                    coordinate_hash=coordinate_hash,
                    wire_body=wire_body,
                    request_json=request_json,
                    policy=policy,
                )

        # Authoritative serializer output for this effective fetch.  When the result
        # is cache/fixture it describes what this run needed, but was not sent upstream.
        result.request_body = wire_body
        return request_hash, request_json, policy, result

    def _fetch_and_store(
        self,
        request: VolatilityRequest,
        *,
        request_hash: str,
        coordinate_hash: str,
        wire_body: dict,
        request_json: str,
        policy: str,
    ) -> FetchResult:
        """Call upstream once per request hash, even under concurrent callers.

        Several indicators share one coordinate — realized vol, spot and forward all read
        the same carrier — so a single refresh used to fire the same request several times
        at once, each missing the cache because none had finished writing it yet.
        """
        state = self._join_inflight(request_hash)
        try:
            with state.lock:
                if state.result is not None:
                    # The caller we queued behind has just retrieved this exact request
                    # from upstream, so its payload answers us too — including when we
                    # asked for a forced refresh, since that payload is seconds old.
                    return state.result
                correlation_id = uuid.uuid4().hex[:12]
                try:
                    payload = self._request_with_retry(
                        "POST",
                        "/v1/implied-volatility",
                        json_body=wire_body,
                        correlation_id=correlation_id,
                    )
                except CortexError as exc:
                    exc.correlation_id = correlation_id
                    raise
                retrieved_at = datetime.now(UTC)
                self._persist_fetched(
                    "implied-volatility",
                    request_hash,
                    payload,
                    policy,
                    request.code,
                    start_end=(request.start_date, request.end_date),
                    request_json=request_json,
                    correlation_id=correlation_id,
                    retrieved_at=retrieved_at,
                    coordinate_hash=coordinate_hash,
                )
                state.result = FetchResult(
                    payload,
                    "live",
                    correlation_id,
                    retrieved_at,
                    source_request_hash=request_hash,
                )
                return state.result
        finally:
            self._leave_inflight(request_hash)

    def _join_inflight(self, request_hash: str) -> _InflightFetch:
        with self._inflight_guard:
            state = self._inflight.get(request_hash)
            if state is None:
                state = _InflightFetch()
                self._inflight[request_hash] = state
            state.waiters += 1
            return state

    def _leave_inflight(self, request_hash: str) -> None:
        with self._inflight_guard:
            state = self._inflight.get(request_hash)
            if state is None:
                return
            state.waiters -= 1
            if state.waiters <= 0:
                del self._inflight[request_hash]

    def _best_cached_result(
        self,
        request: VolatilityRequest,
        *,
        request_hash: str,
        coordinate_hash: str,
        require_fresh: bool,
    ) -> FetchResult | None:
        exact = self._try_cache(
            "implied-volatility", request_hash, require_fresh=require_fresh
        )
        covering = self._try_covering_cache(
            request, coordinate_hash, require_fresh=require_fresh
        )
        if exact is None:
            return covering
        if covering is None:
            return exact
        # Same timestamp => exact is cheaper to parse. Otherwise the newest BNP version
        # wins even when it came from a wider range.
        return covering if covering.retrieved_at > exact.retrieved_at else exact

    def _try_covering_cache(
        self,
        request: VolatilityRequest,
        coordinate_hash: str,
        *,
        require_fresh: bool = True,
    ) -> FetchResult | None:
        entry = self._catalog.find_covering(
            coordinate_hash=coordinate_hash,
            endpoint="implied-volatility",
            start_date=request.start_date,
            end_date=request.end_date,
        )
        if entry is None:
            return None
        if require_fresh and not cache_policy_mod.is_fresh(
            entry["retrieved_at"], entry["cache_policy"]
        ):
            return None
        try:
            payload = self._raw.load("implied-volatility", entry["request_hash"])
        except (OSError, EOFError, ValueError, json.JSONDecodeError):
            return None
        if payload is None or RawStore.payload_hash(payload) != entry["response_hash"]:
            return None
        return FetchResult(
            payload,
            "cache",
            entry["correlation_id"] or entry["request_hash"],
            entry["retrieved_at"],
            source_request_hash=entry["request_hash"],
        )

    def _load_stale_raw_series(
        self,
        request: VolatilityRequest,
        *,
        request_hash: str,
        coordinate_hash: str,
        stale_error: CortexError,
    ) -> tuple[list[StandardObservation], FetchResult] | None:
        cached = self._best_cached_result(
            request,
            request_hash=request_hash,
            coordinate_hash=coordinate_hash,
            require_fresh=False,
        )
        if cached is None:
            return None
        try:
            canonical = canonicalize_surface(cached.payload)
            observations = normalize_surface(canonical, request)
        except CortexError:
            return None
        observations = _within_requested_range(observations, request, cached)
        if not observations:
            return None
        source_ids = [cached.correlation_id]
        result = FetchResult(
            payload=cached.payload,
            cache_status="stale",
            correlation_id=cached.correlation_id,
            retrieved_at=cached.retrieved_at,
            request_body=serialize_volatility_request(request),
            source_request_hash=cached.source_request_hash,
            oldest_retrieved_at=cached.retrieved_at,
            newest_retrieved_at=cached.retrieved_at,
            source_request_ids=source_ids,
            stale_reason=f"{stale_error.code.value}: {stale_error.message}",
            refresh_attempted_at=datetime.now(UTC),
            refresh_correlation_id=getattr(stale_error, "correlation_id", None),
        )
        # Backfill the point library from an exact old request when upgrading an existing
        # installation.  Covering raw responses keep their original range metadata, so do
        # not invent a new coverage interval for the narrower request.
        if cached.source_request_hash == request_hash:
            try:
                self._archive_series(
                    request,
                    request_hash=request_hash,
                    coordinate_hash=coordinate_hash,
                    result=cached,
                    observations=observations,
                )
            except CortexError:
                pass
        return observations, result

    def _compact_request_cache(
        self,
        request: VolatilityRequest,
        *,
        request_hash: str,
        coordinate_hash: str,
        retrieved_at: datetime,
    ) -> None:
        superseded = self._catalog.find_superseded_requests(
            coordinate_hash=coordinate_hash,
            endpoint="implied-volatility",
            start_date=request.start_date,
            end_date=request.end_date,
            retrieved_at=retrieved_at,
            keep_request_hash=request_hash,
        )
        for old_hash in superseded:
            try:
                self._raw.delete("implied-volatility", old_hash)
                self._normalized.delete_request(old_hash)
                self._catalog.delete_request(old_hash)
            except Exception:
                logger.warning("cache compaction failed request=%s", old_hash)

    def _prune_expired_request_files(self, now: datetime) -> None:
        cutoff = cache_policy_mod.freshness_cutoff(now)
        history = self._history_store()
        for entry in self._catalog.list_expired_requests(
            endpoint="implied-volatility", cutoff=cutoff
        ):
            request_json = entry.get("request_json") or ""
            try:
                strike_rule = json.loads(request_json).get("strikeRule")
            except (TypeError, ValueError, json.JSONDecodeError):
                strike_rule = None
            archived = False
            if (
                history is not None
                and entry.get("coordinate_hash")
                and entry.get("start_date") is not None
                and entry.get("end_date") is not None
            ):
                archived = history.has_coverage(
                    coordinate_hash=entry["coordinate_hash"],
                    start_date=entry["start_date"],
                    end_date=entry["end_date"],
                )
            # Fixed/absolute strike universes are explicitly non-historical. Exact
            # percentage/delta request files may also be dropped once point history covers
            # them. Surface/range responses without durable history are retained for now.
            if strike_rule != "fixed" and not archived:
                continue
            old_hash = entry["request_hash"]
            try:
                self._raw.delete("implied-volatility", old_hash)
                self._normalized.delete_request(old_hash)
                self._catalog.delete_request(old_hash)
            except Exception:
                logger.warning("expired cache cleanup failed request=%s", old_hash)

    def _canonicalize_implied_volatility(
        self,
        request: VolatilityRequest,
        request_hash: str,
        request_json: str,
        policy: str,
        result: FetchResult,
    ):
        response_hash = RawStore.payload_hash(result.payload)
        try:
            canonical = canonicalize_surface(result.payload)
        except CortexError as exc:
            self._record_parse_failure(request, request_hash, request_json, policy, result, exc)
            raise

        if self._mode != "fixture" and result.source_request_hash == request_hash:
            self._record_state(
                request_hash=request_hash,
                endpoint="implied-volatility",
                instrument=request.code,
                start_end=(request.start_date, request.end_date),
                request_json=request_json,
                retrieved_at=result.retrieved_at,
                status="SCHEMA_VALIDATED",
                policy=policy,
                correlation_id=result.correlation_id,
                response_hash=response_hash,
            )

        return canonical

    def _record_parse_failure(
        self,
        request: VolatilityRequest,
        request_hash: str,
        request_json: str,
        policy: str,
        result: FetchResult,
        exc: CortexError,
    ) -> None:
        if self._mode == "fixture" or result.source_request_hash != request_hash:
            return
        state = (
            "INVALID_SCHEMA"
            if exc.code in {ErrorCode.INVALID_SCHEMA, ErrorCode.SCHEMA_CHANGED}
            else "PARSE_FAILED"
        )
        self._record_state(
            request_hash=request_hash,
            endpoint="implied-volatility",
            instrument=request.code,
            start_end=(request.start_date, request.end_date),
            request_json=request_json,
            retrieved_at=result.retrieved_at,
            status=state,
            policy=policy,
            correlation_id=result.correlation_id,
            response_hash=RawStore.payload_hash(result.payload),
            error_code=exc.code.value,
        )

    def _finish_implied_volatility(
        self,
        request: VolatilityRequest,
        request_hash: str,
        request_json: str,
        policy: str,
        result: FetchResult,
        observations: list[StandardObservation] | list[StandardSurfaceObservation],
        *,
        surface: bool,
    ) -> None:
        response_hash = RawStore.payload_hash(result.payload)

        if self._mode != "fixture" and result.source_request_hash == request_hash:
            self._record_state(
                request_hash=request_hash,
                endpoint="implied-volatility",
                instrument=request.code,
                start_end=(request.start_date, request.end_date),
                request_json=request_json,
                retrieved_at=result.retrieved_at,
                status="NORMALIZED",
                policy=policy,
                correlation_id=result.correlation_id,
                response_hash=response_hash,
            )

        if self._mode != "fixture" and result.source_request_hash == request_hash:
            try:
                if surface:
                    self._normalized.save_implied_vol_surface(request_hash, observations)
                else:
                    self._normalized.save_implied_vol(request_hash, observations)
            except Exception as exc:
                self._record_state(
                    request_hash=request_hash,
                    endpoint="implied-volatility",
                    instrument=request.code,
                    start_end=(request.start_date, request.end_date),
                    request_json=request_json,
                    retrieved_at=result.retrieved_at,
                    status="STORAGE_FAILED",
                    policy=policy,
                    correlation_id=result.correlation_id,
                    response_hash=response_hash,
                    error_code=ErrorCode.STORAGE_FAILED.value,
                )
                raise CortexError(
                    ErrorCode.STORAGE_FAILED, "implied-volatility 标准化存储失败"
                ) from exc
        quality = "OK"
        for observation in observations:
            if any(flag.value != "OK" for flag in observation.quality_flags):
                quality = "WARNINGS"
                break
            if surface and any(
                flag.value != "OK" for point in observation.points for flag in point.quality_flags
            ):
                quality = "WARNINGS"
                break
        if self._mode != "fixture" and result.source_request_hash == request_hash:
            self._record_state(
                request_hash=request_hash,
                endpoint="implied-volatility",
                instrument=request.code,
                start_end=(request.start_date, request.end_date),
                request_json=request_json,
                retrieved_at=result.retrieved_at,
                status="COMPLETED",
                policy=policy,
                correlation_id=result.correlation_id,
                response_hash=response_hash,
                quality_status=quality,
            )

    def get_curves(self, *_args, **_kwargs):
        """Skeleton only — not part of the phase-1 UI (plan section 8.1)."""
        raise NotImplementedError("get_curves 不在第一阶段页面范围")

    # ----------------------------------------------------------------- cache

    def _try_cache(
        self, endpoint: str, request_hash: str, *, require_fresh: bool = True
    ) -> FetchResult | None:
        entry = self._catalog.get(request_hash)
        if entry is None or str(entry["status"]).upper() != "COMPLETED":
            return None
        if require_fresh and not cache_policy_mod.is_fresh(
            entry["retrieved_at"], entry["cache_policy"]
        ):
            return None
        try:
            payload = self._raw.load(endpoint, request_hash)
        except (OSError, EOFError, ValueError, json.JSONDecodeError):
            self._mark_corrupted_cache(entry)
            return None
        if payload is None:
            return None
        if RawStore.payload_hash(payload) != entry["response_hash"]:
            self._mark_corrupted_cache(entry)
            return None
        return FetchResult(
            payload,
            "hit",
            entry["correlation_id"],
            entry["retrieved_at"],
            source_request_hash=request_hash,
        )

    def _mark_corrupted_cache(self, entry: dict) -> None:
        self._record_state(
            request_hash=entry["request_hash"],
            endpoint=entry["endpoint"],
            instrument=entry["instrument"],
            start_end=(entry["start_date"], entry["end_date"]),
            request_json=entry["request_json"] or "",
            response_hash=entry["response_hash"] or "",
            retrieved_at=entry["retrieved_at"],
            status="CORRUPTED_RAW_CACHE",
            policy=entry["cache_policy"],
            correlation_id=entry["correlation_id"] or "",
            quality_status=entry["quality_status"] or "UNKNOWN",
            error_code=ErrorCode.CORRUPTED_RAW_CACHE.value,
        )

    def _persist_fetched(
        self,
        endpoint: str,
        request_hash: str,
        payload: object,
        policy: str,
        instrument: str | None,
        start_end: tuple | None = None,
        request_json: str = "",
        correlation_id: str = "",
        retrieved_at: datetime | None = None,
        coordinate_hash: str | None = None,
    ) -> None:
        retrieved_at = retrieved_at or datetime.now(UTC)
        response_hash = RawStore.payload_hash(payload)
        try:
            self._raw.save(endpoint, request_hash, payload)
        except Exception as exc:
            self._record_state(
                request_hash=request_hash,
                endpoint=endpoint,
                instrument=instrument,
                start_end=start_end,
                request_json=request_json,
                response_hash=response_hash,
                retrieved_at=retrieved_at,
                status="STORAGE_FAILED",
                policy=policy,
                correlation_id=correlation_id,
                error_code=ErrorCode.STORAGE_FAILED.value,
                coordinate_hash=coordinate_hash,
            )
            raise CortexError(ErrorCode.STORAGE_FAILED, "raw response 写入失败") from exc
        self._record_state(
            request_hash=request_hash,
            endpoint=endpoint,
            instrument=instrument,
            start_end=start_end,
            request_json=request_json,
            response_hash=response_hash,
            retrieved_at=retrieved_at,
            status="FETCHED",
            policy=policy,
            correlation_id=correlation_id,
            coordinate_hash=coordinate_hash,
        )

    def _record_state(
        self,
        *,
        request_hash: str,
        endpoint: str,
        instrument: str | None,
        retrieved_at: datetime,
        status: str,
        policy: str,
        correlation_id: str,
        response_hash: str,
        start_end: tuple | None = None,
        request_json: str = "",
        quality_status: str = "UNKNOWN",
        error_code: str | None = None,
        coordinate_hash: str | None = None,
    ) -> None:
        self._catalog.upsert(
            request_hash=request_hash,
            endpoint=endpoint,
            api_version=self.api_version,
            instrument=instrument,
            start_date=start_end[0] if start_end else None,
            end_date=start_end[1] if start_end else None,
            request_json=request_json,
            response_hash=response_hash,
            retrieved_at=retrieved_at,
            status=status,
            cache_policy=policy,
            correlation_id=correlation_id,
            quality_status=quality_status,
            error_code=error_code,
            coordinate_hash=coordinate_hash,
        )

    # ------------------------------------------------------------------ http

    def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        correlation_id: str,
    ) -> list:
        attempt = 0
        refreshed_once = False
        last_error: CortexError | None = None

        while attempt <= _MAX_RETRIES:
            attempt += 1
            try:
                return self._request_once_limited(
                    method, path, params=params, json_body=json_body, correlation_id=correlation_id
                )
            except CortexError as exc:
                last_error = exc
                if exc.code == ErrorCode.AUTHENTICATION_FAILED and not refreshed_once:
                    refreshed_once = True
                    self._auth.invalidate()
                    continue
                if exc.code == ErrorCode.UPSTREAM_RATE_LIMITED and attempt <= _MAX_RETRIES:
                    time.sleep(self._retry_after(exc) or self._backoff(attempt))
                    continue
                if exc.code == ErrorCode.UPSTREAM_UNAVAILABLE and attempt <= _MAX_RETRIES:
                    time.sleep(self._backoff(attempt))
                    continue
                raise
        raise last_error or CortexError(ErrorCode.UPSTREAM_UNAVAILABLE, "上游调用失败")

    def _request_once_limited(
        self,
        method: str,
        path: str,
        *,
        params: dict | None,
        json_body: dict | None,
        correlation_id: str,
    ) -> list:
        """Take one process-wide permit for exactly one real Cortex HTTP attempt.

        Retries release the permit before backoff and re-enter the queue on the next
        attempt. Cache hits and fixture responses never call this method, while the Raw
        API Playground and instrument lookup share the same cap through _request_with_retry.
        """
        with _UPSTREAM_SEMAPHORE:
            return self._single_request(
                method,
                path,
                params=params,
                json_body=json_body,
                correlation_id=correlation_id,
            )

    def _single_request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None,
        json_body: dict | None,
        correlation_id: str,
    ) -> list:
        token = self._auth.get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-Correlation-ID": correlation_id,
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        url = f"{self._settings.bnp_base_url}{path}"
        timeout = httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
        try:
            with httpx.Client(
                verify=self._settings.bnp_verify_tls,
                proxy=self._settings.http_proxy,
                timeout=timeout,
            ) as client:
                response = client.request(
                    method, url, params=params, json=json_body, headers=headers
                )
        except httpx.TimeoutException as exc:
            logger.warning("cortex timeout cid=%s", correlation_id)
            raise CortexError(ErrorCode.UPSTREAM_UNAVAILABLE, "上游请求超时") from exc
        except httpx.HTTPError as exc:
            logger.warning("cortex http error cid=%s: %s", correlation_id, redact(str(exc)))
            raise CortexError(ErrorCode.UPSTREAM_UNAVAILABLE, "上游连接失败") from exc

        return self._handle_response(response, correlation_id)

    def _handle_response(self, response: httpx.Response, correlation_id: str) -> list:
        status = response.status_code
        if status == 200:
            try:
                data = response.json()
            except ValueError as exc:
                raise CortexError(
                    ErrorCode.SCHEMA_CHANGED, "响应不是合法 JSON", status=status
                ) from exc
            if not isinstance(data, list):
                raise CortexError(ErrorCode.SCHEMA_CHANGED, "响应顶层不是数组", status=status)
            return data

        upstream_payload = None
        try:
            candidate = response.json()
            if isinstance(candidate, dict):
                upstream_payload = candidate
        except ValueError:
            upstream_payload = None

        def upstream_text(*keys: str) -> str | None:
            if upstream_payload is None:
                return None
            for key in keys:
                value = upstream_payload.get(key)
                if isinstance(value, str):
                    value = value.strip()
                    if value:
                        return redact(value[:1000])
            return None

        upstream_code = upstream_text("code", "errorCode", "error")
        upstream_message = upstream_text("message", "errorMessage")
        upstream_suggested_action = upstream_text(
            "suggestedAction", "suggested_action", "suggestion"
        )

        def fail(code: ErrorCode, message: str) -> None:
            raise CortexError(
                code,
                message,
                status=status,
                upstream_code=upstream_code,
                upstream_message=upstream_message,
                upstream_suggested_action=upstream_suggested_action,
            )

        logger.warning(
            "cortex upstream status=%s cid=%s code=%r message=%r",
            status,
            correlation_id,
            upstream_code,
            upstream_message,
        )
        if status == 400:
            fail(ErrorCode.INVALID_REQUEST, "上游拒绝请求参数(400)")
        if status == 401:
            fail(ErrorCode.AUTHENTICATION_FAILED, "token 失效(401)")
        if status == 403:
            fail(ErrorCode.ENTITLEMENT_DENIED, "无该数据访问权限(403)")
        if status == 404:
            fail(ErrorCode.NO_DATA, "上游无此数据(404)")
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            exc = CortexError(
                ErrorCode.UPSTREAM_RATE_LIMITED,
                "上游限流(429)",
                status=status,
                upstream_code=upstream_code,
                upstream_message=upstream_message,
                upstream_suggested_action=upstream_suggested_action,
            )
            exc.retry_after = parse_retry_after(retry_after)
            raise exc
        if status >= 500:
            fail(ErrorCode.UPSTREAM_UNAVAILABLE, f"上游服务异常({status})")
        fail(ErrorCode.UPSTREAM_UNAVAILABLE, f"上游返回非预期状态({status})")

    # ----------------------------------------------------------------- misc

    @staticmethod
    def _backoff(attempt: int) -> float:
        base = min(_BACKOFF_BASE * (2 ** (attempt - 1)), 30.0)
        return min(base + random.uniform(0.0, base * 0.25), 30.0)

    @staticmethod
    def _retry_after(exc: CortexError) -> float | None:
        return getattr(exc, "retry_after", None)

    @staticmethod
    def _load_fixture(name: str):
        path = _FIXTURE_DIR / name
        if not path.exists():
            raise CortexError(ErrorCode.CONFIGURATION_ERROR, f"fixture 缺失: {name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_volatility_fixture(self, request: VolatilityRequest):
        """Select a sanitized fixture whose metadata matches the requested mode."""
        from app.domain.requests import (
            FixedStrikeRequest,
            ListedMaturityMoneynessRequest,
            SlidingDeltaRequest,
            SlidingMoneynessRequest,
        )

        if isinstance(request, SlidingDeltaRequest):
            return self._load_fixture("schema/sliding_delta.json")
        if isinstance(request, FixedStrikeRequest):
            return self._load_fixture("schema/fixed_strike.json")
        if isinstance(request, ListedMaturityMoneynessRequest):
            return self._load_fixture("schema/listed_moneyness.json")
        if (
            isinstance(request, SlidingMoneynessRequest)
            and request.strike_rule == "relative_to_forward"
        ):
            return self._load_fixture("schema/sliding_moneyness.json")
        return self._load_fixture("implied_vol_surface.json")

# VOLCURVE_ERROR_PROVENANCE_V1_9
