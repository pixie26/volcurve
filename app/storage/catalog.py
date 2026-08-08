"""DuckDB request catalog: cache index + retrieval metadata + quality status."""

from __future__ import annotations

import threading
from datetime import date, datetime
from pathlib import Path

import duckdb

_DDL = """
CREATE TABLE IF NOT EXISTS requests (
    request_hash   VARCHAR PRIMARY KEY,
    endpoint       VARCHAR NOT NULL,
    api_version    VARCHAR NOT NULL,
    instrument     VARCHAR,
    start_date     DATE,
    end_date       DATE,
    request_json   VARCHAR,
    response_hash  VARCHAR,
    retrieved_at   TIMESTAMPTZ NOT NULL,
    status         VARCHAR NOT NULL,
    cache_policy   VARCHAR NOT NULL,
    correlation_id VARCHAR,
    quality_status VARCHAR,
    error_code     VARCHAR
)
"""


class Catalog:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(_DDL)
            self._conn.execute("ALTER TABLE requests ADD COLUMN IF NOT EXISTS error_code VARCHAR")
            self._conn.execute(
                "ALTER TABLE requests ADD COLUMN IF NOT EXISTS coordinate_hash VARCHAR"
            )

    def get(self, request_hash: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT request_hash, endpoint, api_version, instrument, start_date,"
                "       end_date, request_json, response_hash, retrieved_at, status, cache_policy,"
                "       correlation_id, quality_status, error_code"
                " FROM requests WHERE request_hash = ?",
                [request_hash],
            ).fetchone()
        if row is None:
            return None
        keys = (
            "request_hash",
            "endpoint",
            "api_version",
            "instrument",
            "start_date",
            "end_date",
            "request_json",
            "response_hash",
            "retrieved_at",
            "status",
            "cache_policy",
            "correlation_id",
            "quality_status",
            "error_code",
        )
        return dict(zip(keys, row, strict=True))

    def upsert(
        self,
        *,
        request_hash: str,
        endpoint: str,
        api_version: str,
        instrument: str | None,
        start_date: date | None,
        end_date: date | None,
        request_json: str,
        response_hash: str,
        retrieved_at: datetime,
        status: str,
        cache_policy: str,
        correlation_id: str,
        quality_status: str,
        error_code: str | None = None,
        coordinate_hash: str | None = None,
    ) -> None:
        with self._lock:
            if coordinate_hash is None:
                # A row advances FETCHED -> SCHEMA_VALIDATED -> NORMALIZED -> COMPLETED, and
                # only the first write carries the coordinate. Since the coordinate is a pure
                # function of the request, keep whatever the row already knows rather than
                # letting a later transition blank it out.
                existing = self._conn.execute(
                    "SELECT coordinate_hash FROM requests WHERE request_hash = ?",
                    [request_hash],
                ).fetchone()
                if existing is not None:
                    coordinate_hash = existing[0]
            self._conn.execute(
                "INSERT OR REPLACE INTO requests ("
                "request_hash, endpoint, api_version, instrument, start_date, end_date, "
                "request_json, response_hash, retrieved_at, status, cache_policy, "
                "correlation_id, quality_status, error_code, coordinate_hash"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    request_hash,
                    endpoint,
                    api_version,
                    instrument,
                    start_date,
                    end_date,
                    request_json,
                    response_hash,
                    retrieved_at,
                    status,
                    cache_policy,
                    correlation_id,
                    quality_status,
                    error_code,
                    coordinate_hash,
                ],
            )

    def find_covering(
        self,
        *,
        coordinate_hash: str,
        endpoint: str,
        start_date: date,
        end_date: date,
    ) -> dict | None:
        """Find a completed response for the same coordinate whose range covers this one.

        Prefers the tightest covering range so the least surplus data has to be parsed.
        Freshness is still the caller's decision, exactly as for an exact-hash hit.
        """
        with self._lock:
            row = self._conn.execute(
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

    def close(self) -> None:
        with self._lock:
            self._conn.close()
