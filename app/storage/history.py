"""Revision-aware historical time-series library.

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
