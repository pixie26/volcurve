from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"pattern not found in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# 8-hour cache policy. Historical responses are no longer permanent cache.
(ROOT / "app/storage/cache.py").write_text(
'''"""Cache freshness policy.

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
''',
    encoding="utf-8",
)

# ---------------------------------------------------------------------------
# Revision-aware point history. Only exact percentage/delta series are written here.
(ROOT / "app/storage/history.py").write_text(
'''"""Revision-aware historical time-series library.

This store is intentionally separate from request cache files.  It keeps the latest
known normalized observation per exact market coordinate/date, plus compact fetch
coverage and point-level revision deltas.  Overlapping successful fetches therefore
stitch naturally: newer points replace the overlap while untouched older dates remain.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from app.domain.observations import StandardObservation

_POINTS_DDL = """
CREATE TABLE IF NOT EXISTS historical_points (
    coordinate_hash   VARCHAR NOT NULL,
    observation_date  DATE NOT NULL,
    observation_json  VARCHAR NOT NULL,
    market_fingerprint VARCHAR NOT NULL,
    retrieved_at      TIMESTAMPTZ NOT NULL,
    request_hash      VARCHAR NOT NULL,
    response_hash     VARCHAR NOT NULL,
    correlation_id    VARCHAR,
    PRIMARY KEY (coordinate_hash, observation_date)
)
"""

_COVERAGE_DDL = """
CREATE TABLE IF NOT EXISTS historical_coverage (
    coordinate_hash VARCHAR NOT NULL,
    request_hash    VARCHAR NOT NULL,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    retrieved_at    TIMESTAMPTZ NOT NULL,
    response_hash   VARCHAR NOT NULL,
    correlation_id  VARCHAR,
    PRIMARY KEY (coordinate_hash, request_hash)
)
"""

_REVISIONS_DDL = """
CREATE TABLE IF NOT EXISTS historical_revisions (
    coordinate_hash  VARCHAR NOT NULL,
    observation_date DATE NOT NULL,
    change_type      VARCHAR NOT NULL,
    old_json         VARCHAR,
    new_json         VARCHAR,
    old_retrieved_at TIMESTAMPTZ,
    new_retrieved_at TIMESTAMPTZ NOT NULL,
    old_response_hash VARCHAR,
    new_response_hash VARCHAR NOT NULL,
    detected_at      TIMESTAMPTZ NOT NULL
)
"""


@dataclass(frozen=True)
class HistoricalLoad:
    observations: list[StandardObservation]
    oldest_retrieved_at: datetime
    newest_retrieved_at: datetime
    correlation_ids: list[str]


def _observation_json(observation: StandardObservation) -> str:
    return json.dumps(
        observation.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _market_fingerprint(observation: StandardObservation) -> str:
    # Derived effective-IV/quality fields are excluded so parser upgrades do not look like
    # upstream revisions.  These are the source/coordinate fields that describe the market
    # observation we actually received.
    payload = {
        "date": observation.date.isoformat(),
        "instrument_code": observation.instrument_code,
        "spot": observation.spot,
        "target_maturity": observation.target_maturity,
        "returned_maturity": observation.returned_maturity,
        "strike_rule": observation.strike_rule,
        "target_strike": observation.target_strike,
        "returned_strike": observation.returned_strike,
        "forward": observation.forward,
        "discount_factor": observation.discount_factor,
        "raw_implied_vol": observation.raw_implied_vol,
        "source_time": observation.source_time,
        "source_timezone": observation.source_timezone,
        "source_timestamp": observation.source_timestamp,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=True).encode()
    return hashlib.sha256(blob).hexdigest()


def _covers(intervals: list[tuple[date, date]], start: date, end: date) -> bool:
    if end < start:
        return False
    cursor = start
    for interval_start, interval_end in sorted(intervals):
        if interval_end < cursor:
            continue
        if interval_start > cursor:
            return False
        if interval_end >= end:
            return True
        cursor = interval_end + timedelta(days=1)
    return False


class HistoricalStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(_POINTS_DDL)
            self._conn.execute(_COVERAGE_DDL)
            self._conn.execute(_REVISIONS_DDL)

    def upsert_series(
        self,
        *,
        coordinate_hash: str,
        request_hash: str,
        start_date: date,
        end_date: date,
        retrieved_at: datetime,
        response_hash: str,
        correlation_id: str,
        observations: list[StandardObservation],
    ) -> None:
        incoming = {observation.date: observation for observation in observations}
        with self._lock:
            self._conn.execute("BEGIN TRANSACTION")
            try:
                rows = self._conn.execute(
                    "SELECT observation_date, observation_json, market_fingerprint, "
                    "retrieved_at, response_hash FROM historical_points "
                    "WHERE coordinate_hash = ? AND observation_date BETWEEN ? AND ?",
                    [coordinate_hash, start_date, end_date],
                ).fetchall()
                existing = {
                    row[0]: {
                        "json": row[1],
                        "fingerprint": row[2],
                        "retrieved_at": row[3],
                        "response_hash": row[4],
                    }
                    for row in rows
                }

                # A newer successful response that omits a date previously returned for the
                # same requested interval is itself a revision.  Do not keep the old point as
                # if Cortex had returned it again.
                for business_date, old in existing.items():
                    if business_date in incoming or old["retrieved_at"] > retrieved_at:
                        continue
                    self._conn.execute(
                        "INSERT INTO historical_revisions VALUES (?, ?, 'REMOVED', ?, NULL, ?, ?, ?, ?, ?)",
                        [
                            coordinate_hash,
                            business_date,
                            old["json"],
                            old["retrieved_at"],
                            retrieved_at,
                            old["response_hash"],
                            response_hash,
                            retrieved_at,
                        ],
                    )
                    self._conn.execute(
                        "DELETE FROM historical_points WHERE coordinate_hash = ? AND observation_date = ?",
                        [coordinate_hash, business_date],
                    )

                for business_date, observation in incoming.items():
                    encoded = _observation_json(observation)
                    fingerprint = _market_fingerprint(observation)
                    old = existing.get(business_date)
                    # A late-finishing older fetch must never roll a point backwards.
                    if old is not None and old["retrieved_at"] > retrieved_at:
                        continue
                    if old is not None and old["fingerprint"] != fingerprint:
                        self._conn.execute(
                            "INSERT INTO historical_revisions VALUES (?, ?, 'CHANGED', ?, ?, ?, ?, ?, ?, ?)",
                            [
                                coordinate_hash,
                                business_date,
                                old["json"],
                                encoded,
                                old["retrieved_at"],
                                retrieved_at,
                                old["response_hash"],
                                response_hash,
                                retrieved_at,
                            ],
                        )
                    self._conn.execute(
                        "INSERT OR REPLACE INTO historical_points VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            coordinate_hash,
                            business_date,
                            encoded,
                            fingerprint,
                            retrieved_at,
                            request_hash,
                            response_hash,
                            correlation_id,
                        ],
                    )

                prior = self._conn.execute(
                    "SELECT retrieved_at FROM historical_coverage WHERE coordinate_hash = ? AND request_hash = ?",
                    [coordinate_hash, request_hash],
                ).fetchone()
                if prior is None or prior[0] <= retrieved_at:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO historical_coverage VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [
                            coordinate_hash,
                            request_hash,
                            start_date,
                            end_date,
                            retrieved_at,
                            response_hash,
                            correlation_id,
                        ],
                    )
                # Coverage metadata obeys the same safe compaction rule as full request
                # files: a newer superset makes an older fully-contained interval redundant.
                self._conn.execute(
                    "DELETE FROM historical_coverage WHERE coordinate_hash = ? "
                    "AND request_hash <> ? AND start_date >= ? AND end_date <= ? "
                    "AND retrieved_at <= ?",
                    [coordinate_hash, request_hash, start_date, end_date, retrieved_at],
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def has_coverage(
        self,
        *,
        coordinate_hash: str,
        start_date: date,
        end_date: date,
        fresh_after: datetime | None = None,
    ) -> bool:
        with self._lock:
            sql = (
                "SELECT start_date, end_date FROM historical_coverage "
                "WHERE coordinate_hash = ? AND end_date >= ? AND start_date <= ?"
            )
            params: list[object] = [coordinate_hash, start_date, end_date]
            if fresh_after is not None:
                sql += " AND retrieved_at >= ?"
                params.append(fresh_after)
            intervals = self._conn.execute(sql, params).fetchall()
        return _covers(intervals, start_date, end_date)

    def load_series(
        self,
        *,
        coordinate_hash: str,
        start_date: date,
        end_date: date,
        fresh_after: datetime | None = None,
    ) -> HistoricalLoad | None:
        if not self.has_coverage(
            coordinate_hash=coordinate_hash,
            start_date=start_date,
            end_date=end_date,
            fresh_after=fresh_after,
        ):
            return None
        with self._lock:
            rows = self._conn.execute(
                "SELECT observation_json, retrieved_at, correlation_id "
                "FROM historical_points WHERE coordinate_hash = ? "
                "AND observation_date BETWEEN ? AND ? ORDER BY observation_date",
                [coordinate_hash, start_date, end_date],
            ).fetchall()
        if not rows:
            return None
        observations = [StandardObservation.model_validate(json.loads(row[0])) for row in rows]
        retrieved = [row[1] for row in rows]
        correlation_ids = list(dict.fromkeys(row[2] for row in rows if row[2]))
        return HistoricalLoad(
            observations=observations,
            oldest_retrieved_at=min(retrieved),
            newest_retrieved_at=max(retrieved),
            correlation_ids=correlation_ids,
        )

    def revision_count(self, coordinate_hash: str | None = None) -> int:
        with self._lock:
            if coordinate_hash is None:
                row = self._conn.execute("SELECT COUNT(*) FROM historical_revisions").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM historical_revisions WHERE coordinate_hash = ?",
                    [coordinate_hash],
                ).fetchone()
        return int(row[0])

    def revision_types(self, coordinate_hash: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT change_type FROM historical_revisions WHERE coordinate_hash = ? ORDER BY detected_at",
                [coordinate_hash],
            ).fetchall()
        return [row[0] for row in rows]

    def point_count(self, coordinate_hash: str | None = None) -> int:
        with self._lock:
            if coordinate_hash is None:
                row = self._conn.execute("SELECT COUNT(*) FROM historical_points").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM historical_points WHERE coordinate_hash = ?",
                    [coordinate_hash],
                ).fetchone()
        return int(row[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()
''',
    encoding="utf-8",
)

# ---------------------------------------------------------------------------
# Settings: explicit persistent history database path.
replace_once(
    "app/config.py",
    '        self.duckdb_path = DATA_DIR / "catalog.duckdb"\n',
    '        self.duckdb_path = DATA_DIR / "catalog.duckdb"\n        self.history_duckdb_path = DATA_DIR / "history.duckdb"\n',
)

# ---------------------------------------------------------------------------
# Catalog: newest covering response wins; add safe cache compaction primitives.
catalog_path = ROOT / "app/storage/catalog.py"
catalog = catalog_path.read_text(encoding="utf-8")
catalog = catalog.replace(
'''            row = self._conn.execute(
                "SELECT request_hash, retrieved_at, cache_policy, start_date, end_date"
                " FROM requests"
                " WHERE coordinate_hash = ? AND endpoint = ? AND status = 'COMPLETED'"
                "   AND start_date <= ? AND end_date >= ?"
                " ORDER BY (end_date - start_date) ASC LIMIT 1",
                [coordinate_hash, endpoint, start_date, end_date],
            ).fetchone()
        if row is None:
            return None
        keys = ("request_hash", "retrieved_at", "cache_policy", "start_date", "end_date")
        return dict(zip(keys, row, strict=True))
''',
'''            row = self._conn.execute(
                "SELECT request_hash, retrieved_at, cache_policy, start_date, end_date, "
                "response_hash, correlation_id"
                " FROM requests"
                " WHERE coordinate_hash = ? AND endpoint = ? AND status = 'COMPLETED'"
                "   AND start_date <= ? AND end_date >= ?"
                " ORDER BY retrieved_at DESC, "
                "CASE WHEN start_date = ? AND end_date = ? THEN 0 ELSE 1 END, "
                "(end_date - start_date) ASC LIMIT 1",
                [coordinate_hash, endpoint, start_date, end_date, start_date, end_date],
            ).fetchone()
        if row is None:
            return None
        keys = (
            "request_hash", "retrieved_at", "cache_policy", "start_date", "end_date",
            "response_hash", "correlation_id",
        )
        return dict(zip(keys, row, strict=True))
''',
)
if "ORDER BY retrieved_at DESC" not in catalog:
    raise RuntimeError("failed to update Catalog.find_covering")
insert = '''
    def find_superseded_requests(
        self,
        *,
        coordinate_hash: str,
        endpoint: str,
        start_date: date,
        end_date: date,
        retrieved_at: datetime,
        keep_request_hash: str,
    ) -> list[str]:
        """Older completed request files fully contained by a newer response."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT request_hash FROM requests WHERE coordinate_hash = ? AND endpoint = ? "
                "AND status = 'COMPLETED' AND request_hash <> ? "
                "AND start_date >= ? AND end_date <= ? AND retrieved_at <= ?",
                [
                    coordinate_hash,
                    endpoint,
                    keep_request_hash,
                    start_date,
                    end_date,
                    retrieved_at,
                ],
            ).fetchall()
        return [row[0] for row in rows]

    def list_expired_requests(self, *, endpoint: str, cutoff: datetime) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT request_hash, coordinate_hash, start_date, end_date, request_json "
                "FROM requests WHERE endpoint = ? AND status = 'COMPLETED' AND retrieved_at < ?",
                [endpoint, cutoff],
            ).fetchall()
        keys = ("request_hash", "coordinate_hash", "start_date", "end_date", "request_json")
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def delete_request(self, request_hash: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM requests WHERE request_hash = ?", [request_hash])

'''
marker = "    def close(self) -> None:\n"
if marker not in catalog:
    raise RuntimeError("catalog close marker missing")
catalog = catalog.replace(marker, insert + marker, 1)
catalog_path.write_text(catalog, encoding="utf-8")

# ---------------------------------------------------------------------------
# Cache-file deletion helpers.
replace_once(
    "app/storage/raw_store.py",
    '''    def exists(self, endpoint: str, request_hash: str) -> bool:
        return self._path(endpoint, request_hash).exists()

    @staticmethod
''',
    '''    def exists(self, endpoint: str, request_hash: str) -> bool:
        return self._path(endpoint, request_hash).exists()

    def delete(self, endpoint: str, request_hash: str) -> None:
        path = self._path(endpoint, request_hash)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
''',
)
replace_once(
    "app/storage/normalized_store.py",
    '''    def save_instruments(self, instruments: list[dict]) -> Path:
        out_dir = self._dir / "instruments"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "instruments.parquet"
        self._atomic_parquet(pd.DataFrame(instruments), path)
        return path

    @staticmethod
''',
    '''    def save_instruments(self, instruments: list[dict]) -> Path:
        out_dir = self._dir / "instruments"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "instruments.parquet"
        self._atomic_parquet(pd.DataFrame(instruments), path)
        return path

    def delete_request(self, request_hash: str) -> None:
        for directory in ("implied_vol", "implied_vol_surface"):
            path = self._dir / directory / f"{request_hash}.parquet"
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
''',
)

# ---------------------------------------------------------------------------
# Cortex client: 8h cache, point-history stitching, stale fallback, compaction.
client_path = ROOT / "app/clients/cortex/client.py"
client = client_path.read_text(encoding="utf-8")
client = client.replace(
'''- persistent cache: raw store (authoritative) + DuckDB catalog index;
  historical ranges are permanent, intraday ranges have a short TTL;
''',
'''- short request cache: verified raw responses are reusable for eight hours;
- revision-aware historical library: exact percentage/delta series are stitched by date,
  while absolute/listed strike universes remain short-lived cache only;
''',
)
client = client.replace(
"from app.domain.observations import StandardObservation\nfrom app.domain.requests import VolatilityRequest\n",
'''from app.domain.observations import StandardObservation
from app.domain.requests import (
    FixedStrikeRequest,
    ListedMaturityMoneynessRequest,
    SlidingDeltaRequest,
    SlidingMoneynessRequest,
    VolatilityRequest,
)
''',
)
client = client.replace(
"from app.storage.catalog import Catalog\n",
"from app.storage.catalog import Catalog\nfrom app.storage.history import HistoricalStore\n",
)
old_fetch = '''@dataclass
class FetchResult:
    payload: list
    # "live" (fetched now) | "hit" (exact-range cache) | "cache" (a wider stored range for
    # the same coordinate answered this one) | "fixture"
    cache_status: str
    correlation_id: str
    retrieved_at: datetime
    request_body: dict | None = None
'''
new_fetch = '''@dataclass
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
'''
if old_fetch not in client:
    raise RuntimeError("FetchResult block missing")
client = client.replace(old_fetch, new_fetch, 1)
client = client.replace(
'''        self._catalog = catalog or Catalog(settings.duckdb_path)
        self._raw = raw_store or RawStore(settings.raw_dir)
        self._normalized = normalized_store or NormalizedStore(settings.normalized_dir)
''',
'''        self._catalog = catalog or Catalog(settings.duckdb_path)
        self._raw = raw_store or RawStore(settings.raw_dir)
        self._normalized = normalized_store or NormalizedStore(settings.normalized_dir)
        self._history = HistoricalStore(settings.history_duckdb_path)
''',
1,
)

old_public = '''    def get_implied_volatility(
        self, request: VolatilityRequest, *, force_refresh: bool = False
    ) -> tuple[list[StandardObservation], FetchResult]:
        request_hash, request_json, policy, result = self._fetch_implied_volatility(
            request, force_refresh=force_refresh
        )
        canonical = self._canonicalize_implied_volatility(
            request, request_hash, request_json, policy, result
        )
        try:
            observations = _within_requested_range(
                normalize_surface(canonical, request), request, result
            )
        except CortexError as exc:
            self._record_parse_failure(request, request_hash, request_json, policy, result, exc)
            raise
        self._finish_implied_volatility(
            request,
            request_hash,
            request_json,
            policy,
            result,
            observations,
            surface=False,
        )
        return observations, result

    def get_implied_volatility_surface(
'''
new_public = '''    @staticmethod
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
'''
if old_public not in client:
    raise RuntimeError("get_implied_volatility block missing")
client = client.replace(old_public, new_public, 1)

# Surface: move range trim outside parser-failure catch, reject empty before persistence,
# and run cache-file pruning after a successful live response.
old_surface = '''        try:
            observations = _within_requested_range(
                normalize_surface_snapshots(canonical, request), request, result
            )
        except CortexError as exc:
            self._record_parse_failure(request, request_hash, request_json, policy, result, exc)
            raise
        self._finish_implied_volatility(
            request,
            request_hash,
            request_json,
            policy,
            result,
            observations,
            surface=True,
        )
        return observations, result
'''
new_surface = '''        try:
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
'''
if old_surface not in client:
    raise RuntimeError("surface normalization block missing")
client = client.replace(old_surface, new_surface, 1)

# Request-cache selection: compare exact and covering entries and take the newer version.
old_fetch_method = '''            result = None
            if not force_refresh:
                result = self._try_cache("implied-volatility", request_hash)
                if result is None:
                    result = self._try_covering_cache(request, coordinate_hash)
            if result is None:
'''
new_fetch_method = '''            result = None
            if not force_refresh:
                result = self._best_cached_result(
                    request,
                    request_hash=request_hash,
                    coordinate_hash=coordinate_hash,
                    require_fresh=True,
                )
            if result is None:
'''
if old_fetch_method not in client:
    raise RuntimeError("fetch cache block missing")
client = client.replace(old_fetch_method, new_fetch_method, 1)

# Attach request ownership and failed-refresh correlation IDs.
client = client.replace(
'''                payload = self._request_with_retry(
                    "POST",
                    "/v1/implied-volatility",
                    json_body=wire_body,
                    correlation_id=correlation_id,
                )
''',
'''                try:
                    payload = self._request_with_retry(
                        "POST",
                        "/v1/implied-volatility",
                        json_body=wire_body,
                        correlation_id=correlation_id,
                    )
                except CortexError as exc:
                    exc.correlation_id = correlation_id
                    raise
''',
1,
)
client = client.replace(
'''                state.result = FetchResult(payload, "live", correlation_id, retrieved_at)
''',
'''                state.result = FetchResult(
                    payload,
                    "live",
                    correlation_id,
                    retrieved_at,
                    source_request_hash=request_hash,
                )
''',
1,
)

# Replace covering-cache loader with verified/latest helpers and stale raw migration.
start = client.index("    def _try_covering_cache(\n")
end = client.index("    def _canonicalize_implied_volatility(\n", start)
new_cache_helpers = '''    def _best_cached_result(
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

'''
client = client[:start] + new_cache_helpers + client[end:]

# Persist parse/normalize state only for a raw response that belongs to the current exact
# request. A covering response must never manufacture a narrow COMPLETED catalog row.
client = client.replace(
'''        if self._mode != "fixture":
            self._record_state(
                request_hash=request_hash,
                endpoint="implied-volatility",
                instrument=request.code,
                start_end=(request.start_date, request.end_date),
                request_json=request_json,
                retrieved_at=result.retrieved_at,
                status="SCHEMA_VALIDATED",
''',
'''        if self._mode != "fixture" and result.source_request_hash == request_hash:
            self._record_state(
                request_hash=request_hash,
                endpoint="implied-volatility",
                instrument=request.code,
                start_end=(request.start_date, request.end_date),
                request_json=request_json,
                retrieved_at=result.retrieved_at,
                status="SCHEMA_VALIDATED",
''',
1,
)
client = client.replace(
'''        if self._mode == "fixture":
            return
        state = (
''',
'''        if self._mode == "fixture" or result.source_request_hash != request_hash:
            return
        state = (
''',
1,
)
# Two `if self._mode != fixture` blocks in _finish; constrain both within that method.
finish_start = client.index("    def _finish_implied_volatility(\n")
finish_end = client.index("    def get_curves(", finish_start)
finish = client[finish_start:finish_end]
finish = finish.replace(
'        if self._mode != "fixture":\n',
'        if self._mode != "fixture" and result.source_request_hash == request_hash:\n',
)
client = client[:finish_start] + finish + client[finish_end:]

# Exact cache loader now supports stale lookup and carries ownership metadata.
old_try = '''    def _try_cache(self, endpoint: str, request_hash: str) -> FetchResult | None:
        entry = self._catalog.get(request_hash)
        if entry is None or str(entry["status"]).upper() != "COMPLETED":
            return None
        if not cache_policy_mod.is_fresh(entry["retrieved_at"], entry["cache_policy"]):
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
        return FetchResult(payload, "hit", entry["correlation_id"], entry["retrieved_at"])
'''
new_try = '''    def _try_cache(
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
'''
if old_try not in client:
    raise RuntimeError("_try_cache block missing")
client = client.replace(old_try, new_try, 1)

# Instruments live result ownership (no behavior change beyond metadata).
client = client.replace(
'                result = FetchResult(data, "live", request_hash, retrieved_at)\n',
'                result = FetchResult(data, "live", request_hash, retrieved_at, source_request_hash=request_hash)\n',
1,
)
client_path.write_text(client, encoding="utf-8")

# ---------------------------------------------------------------------------
# Public API provenance for archive/stale data.
replace_once(
    "app/domain/responses.py",
'''class SourceInfo(BaseModel):
    provider: str
    apiVersion: str
    instrumentCode: str
    retrievedAt: datetime
    cacheStatus: str
    requestId: str
    requestIds: list[str]
    warmupFrom: date
''',
'''class SourceInfo(BaseModel):
    provider: str
    apiVersion: str
    instrumentCode: str
    retrievedAt: datetime
    cacheStatus: str
    requestId: str
    requestIds: list[str]
    warmupFrom: date
    isStale: bool = False
    oldestRetrievedAt: datetime | None = None
    newestRetrievedAt: datetime | None = None
    refreshAttemptedAt: datetime | None = None
    refreshRequestId: str | None = None
    staleReason: str | None = None
''',
)

presenter_path = ROOT / "app/api/presenters.py"
presenter = presenter_path.read_text(encoding="utf-8")
old_source = '''def _source_info(client, request: VolatilityRequest, fetch_results, warmup_from) -> SourceInfo:
    statuses = list(dict.fromkeys(result.cache_status for result in fetch_results))
    cache_status = statuses[0] if len(statuses) == 1 else "mixed"
    request_ids = list(dict.fromkeys(result.correlation_id for result in fetch_results))
    return SourceInfo(
        provider="Cortex DataHub",
        apiVersion=client.api_version,
        instrumentCode=request.code,
        retrievedAt=max(result.retrieved_at for result in fetch_results),
        cacheStatus=cache_status,
        requestId=request_ids[0],
        requestIds=request_ids,
        warmupFrom=warmup_from,
    )
'''
new_source = '''def _source_info(client, request: VolatilityRequest, fetch_results, warmup_from) -> SourceInfo:
    statuses = list(dict.fromkeys(result.cache_status for result in fetch_results))
    cache_status = statuses[0] if len(statuses) == 1 else "mixed"
    request_ids = []
    for result in fetch_results:
        request_ids.extend(result.source_request_ids or [result.correlation_id])
    request_ids = list(dict.fromkeys(request_ids)) or ["historical-archive"]
    oldest = min(
        result.oldest_retrieved_at or result.retrieved_at for result in fetch_results
    )
    newest = max(
        result.newest_retrieved_at or result.retrieved_at for result in fetch_results
    )
    refresh_times = [result.refresh_attempted_at for result in fetch_results if result.refresh_attempted_at]
    refresh_ids = [result.refresh_correlation_id for result in fetch_results if result.refresh_correlation_id]
    stale_reasons = list(
        dict.fromkeys(result.stale_reason for result in fetch_results if result.stale_reason)
    )
    return SourceInfo(
        provider="Cortex DataHub",
        apiVersion=client.api_version,
        instrumentCode=request.code,
        retrievedAt=newest,
        cacheStatus=cache_status,
        requestId=request_ids[0],
        requestIds=request_ids,
        warmupFrom=warmup_from,
        isStale="stale" in statuses,
        oldestRetrievedAt=oldest,
        newestRetrievedAt=newest,
        refreshAttemptedAt=max(refresh_times) if refresh_times else None,
        refreshRequestId=refresh_ids[-1] if refresh_ids else None,
        staleReason="; ".join(stale_reasons) if stale_reasons else None,
    )
'''
if old_source not in presenter:
    raise RuntimeError("presenter source block missing")
presenter = presenter.replace(old_source, new_source, 1)
presenter = presenter.replace(
'''    if "hit" in statuses:
        events.append(
            ActivityEvent(code="CACHE_HIT", stage="fetch", message="已使用校验通过的本地缓存。")
        )
''',
'''    if "hit" in statuses or "cache" in statuses:
        events.append(
            ActivityEvent(code="CACHE_HIT", stage="fetch", message="已使用校验通过的本地请求缓存。")
        )
    if "archive" in statuses:
        events.append(
            ActivityEvent(
                code="HISTORICAL_ARCHIVE_HIT",
                stage="fetch",
                message="本地历史点库已完整覆盖请求；未调用 live API。",
            )
        )
    if "stale" in statuses:
        events.append(
            ActivityEvent(
                code="STALE_ARCHIVE_FALLBACK",
                stage="fetch",
                message="最新 Cortex 刷新失败；正在显示最近一次成功保存的本地历史数据。",
                suggestedAction="数据已明确标记为 STALE；网络/上游恢复后重新刷新以确认最新值。",
            )
        )
''',
1,
)
# Stale fallback did attempt upstream even though the displayed data came from archive.
presenter = presenter.replace(
'''                sentToUpstream=disposition == "live",
                correlationId=result.correlation_id,
''',
'''                sentToUpstream=disposition in {"live", "stale"},
                correlationId=(result.refresh_correlation_id if disposition == "stale" and result.refresh_correlation_id else result.correlation_id),
''',
1,
)
presenter_path.write_text(presenter, encoding="utf-8")

# Connectivity beacon: stale fallback means current upstream refresh failed.
replace_once(
    "app/api/vol_compare.py",
'''    if any(result.cache_status == "live" for result in execution.load.fetch_results):
        mark_connectivity(True)
''',
'''    if any(result.cache_status == "stale" for result in execution.load.fetch_results):
        mark_connectivity(False)
    elif any(result.cache_status == "live" for result in execution.load.fetch_results):
        mark_connectivity(True)
''',
)

# ---------------------------------------------------------------------------
# Browser: prominent red stale warning and detailed provenance.
web_path = ROOT / "app/web/compare-builder.js"
web = web_path.read_text(encoding="utf-8")
old_warning = '''  function renderIndicatorWarnings(active) {
    const errors = active.filter((item) => item.status === "error");
    const invalid = active
      .filter((item) => item.type === "implied_vol")
      .reduce((count, item) => count + (item.response?.dataQuality?.invalidIvCount || 0), 0);
    const warning = $("timeseriesWarning");
    const messages = [];
    if (errors.length) messages.push(`${errors.length} 个激活指标加载失败；查看左侧指标卡的原始错误。`);
    if (invalid) messages.push(`${invalid} 个非正/无效 IV 点保留 raw value，但图中为空且不连接。`);
    if (!messages.length) {
      warning.classList.add("is-hidden");
      warning.textContent = "";
      return;
    }
    warning.textContent = messages.join(" ");
    warning.classList.remove("is-hidden");
  }
'''
new_warning = '''  function renderIndicatorWarnings(active) {
    const errors = active.filter((item) => item.status === "error");
    const stale = active.filter((item) => item.response?.source?.isStale);
    const invalid = active
      .filter((item) => item.type === "implied_vol")
      .reduce((count, item) => count + (item.response?.dataQuality?.invalidIvCount || 0), 0);
    const warning = $("timeseriesWarning");
    const messages = [];
    if (stale.length) {
      const sources = stale.map((item) => {
        const source = item.response.source;
        return `${indicatorLabel(item)}：${source.newestRetrievedAt || source.retrievedAt}`;
      });
      messages.push(`STALE DATA — 最新 Cortex 刷新失败，正在显示本地历史数据。最近成功获取：${sources.join("；")}`);
    }
    if (errors.length) messages.push(`${errors.length} 个激活指标加载失败；查看左侧指标卡的原始错误。`);
    if (invalid) messages.push(`${invalid} 个非正/无效 IV 点保留 raw value，但图中为空且不连接。`);
    warning.classList.toggle("is-stale", stale.length > 0);
    if (!messages.length) {
      warning.classList.add("is-hidden");
      warning.textContent = "";
      return;
    }
    warning.textContent = messages.join(" ");
    warning.classList.remove("is-hidden");
  }
'''
if old_warning not in web:
    raise RuntimeError("renderIndicatorWarnings block missing")
web = web.replace(old_warning, new_warning, 1)
web = web.replace(
'''        ["Source mode", String(data.source.cacheStatus || "unknown").toUpperCase()],
        ["Actual upstream calls", String(sentCount)],
        ["Provider", `${data.source.provider} · API ${data.source.apiVersion}`],
        ["Retrieved at", data.source.retrievedAt],
        ["Request ID", data.requestId],
''',
'''        ["Source mode", String(data.source.cacheStatus || "unknown").toUpperCase()],
        ["Data status", data.source.isStale ? "STALE — latest refresh failed" : "FRESH / locally confirmed"],
        ["Actual upstream calls", String(sentCount)],
        ["Provider", `${data.source.provider} · API ${data.source.apiVersion}`],
        ["Oldest contributing fetch", data.source.oldestRetrievedAt || data.source.retrievedAt],
        ["Newest contributing fetch", data.source.newestRetrievedAt || data.source.retrievedAt],
        ["Refresh attempted", data.source.refreshAttemptedAt || "—"],
        ["Refresh failure", data.source.staleReason || "—"],
        ["Request ID", data.requestId],
''',
1,
)
web_path.write_text(web, encoding="utf-8")

styles_path = ROOT / "app/web/styles.css"
styles = styles_path.read_text(encoding="utf-8")
styles = styles.replace(
'.warning-banner { color: #77400e; background: var(--orange-soft); border: 1px solid #edc494; }\n',
'.warning-banner { color: #77400e; background: var(--orange-soft); border: 1px solid #edc494; }\n.warning-banner.is-stale { color: #8f1f18; background: #fde8e6; border-color: #e7a8a2; font-weight: 750; }\n',
1,
)
styles_path.write_text(styles, encoding="utf-8")

# ---------------------------------------------------------------------------
# Documentation of the frozen Step 7 semantics.
phase_path = ROOT / "docs/phase_f_compare_indicator_builder_zh.md"
phase = phase_path.read_text(encoding="utf-8")
anchor = "## 当前已知 legacy UI 边界\n"
section = '''## Historical cache / library 语义（Step 7）

- 所有 request cache 的 freshness 为滚动 **8 小时**；历史日期不再永久视为 fresh。超过 8 小时后，下一次使用会尝试重新向 Cortex 获取，以发现历史修订。
- exact request 与 covering request 同时可用时，**retrieved_at 更新的 BNP 版本优先**；只有时间相同时才优先 exact / 更窄 payload。
- Time Series 的长期历史库按 `coordinate × observation date` 保存 latest-known point，可把多次重叠成功请求拼接：新区间覆盖 overlap，未重叠的旧日期继续保留。
- 长期历史库只收 **K/F 百分比、K/S 百分比与 Delta** 的精确单坐标序列；absolute/fixed strike（包括 listed strike discovery 的大 strike universe）只保留短期 request cache，不进入历史点库。
- 新版成功 response 若修改或删除旧 point，会写一条轻量 revision delta；日常图表使用 latest-known point，不保留整份旧大 payload 作为 revision archive。
- 新版 request 完全覆盖同坐标旧 request 时，旧 raw/parquet/catalog cache 可安全删除；过期 exact-series raw 在历史点库已完整覆盖后也可清理。
- refresh 因 timeout/429/5xx/`NO_DATA` 失败时，如果历史点库能完整覆盖请求，可显示 stale fallback；必须在图表上方红色标记 `STALE DATA`，并披露最近成功获取时间、刷新尝试时间和失败原因。400/401/403/schema/local-contract 错误不得用旧数据掩盖。
- Historical point stitching 的语义是“每个 observation date 的 latest-known BNP value”，不是单一 as-of snapshot；当前阶段不实现 mixed-version 回测快照。

'''
if anchor not in phase:
    raise RuntimeError("phase doc anchor missing")
phase_path.write_text(phase.replace(anchor, section + anchor, 1), encoding="utf-8")

runbook_path = ROOT / "docs/operations_runbook_zh.md"
runbook = runbook_path.read_text(encoding="utf-8")
runbook = runbook.replace(
'- `/app/data` 必须挂载持久卷；否则容器重建会丢失 raw 权威源与 catalog。\n',
'- `/app/data` 必须挂载持久卷；否则容器重建会丢失 request cache、catalog 与 `history.duckdb` 历史点库/修订记录。\n',
1,
)
runbook_path.write_text(runbook, encoding="utf-8")

# ---------------------------------------------------------------------------
# Deep regression tests.
(ROOT / "tests/unit/test_historical_archive.py").write_text(
'''"""Deep regression tests for Step 7 cache/history semantics."""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta

import pytest

from app.api.presenters import _source_info
from app.clients.cortex.client import CortexClient, FetchResult
from app.clients.cortex.errors import CortexError, ErrorCode
from app.clients.cortex.serializers import volatility_coordinate_hash
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
        client._request_with_retry = lambda *_a, **_k: (_ for _ in ()).throw(
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
        client._request_with_retry = lambda *_a, **_k: (_ for _ in ()).throw(
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
''',
    encoding="utf-8",
)

# Existing storage helper constructed with __new__: explicitly opt out of history so its
# original request-cache tests keep testing request cache rather than the new point store.
replace_once(
    "tests/unit/test_storage_and_cache.py",
'''    client._normalized = NormalizedStore(tmp_path / "normalized")
    client._inflight = {}
''',
'''    client._normalized = NormalizedStore(tmp_path / "normalized")
    client._history = None
    client._inflight = {}
''',
)

# Static browser regression for the red stale-data path.
web_test = ROOT / "tests/integration/test_phase_d_web.py"
web_test.write_text(
    web_test.read_text(encoding="utf-8")
    + '''\n\ndef test_stale_archive_is_prominent_in_time_series_ui():\n    with TestClient(app) as client:\n        javascript = client.get("/static/compare-builder.js").text\n        css = client.get("/static/styles.css").text\n\n    assert "STALE DATA — 最新 Cortex 刷新失败" in javascript\n    assert 'warning.classList.toggle("is-stale", stale.length > 0)' in javascript\n    assert ".warning-banner.is-stale" in css\n    assert "Oldest contributing fetch" in javascript\n    assert "Refresh failure" in javascript\n''',
    encoding="utf-8",
)

print("Step 7 patch applied")
