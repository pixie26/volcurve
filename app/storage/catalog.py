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
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO requests ("
                "request_hash, endpoint, api_version, instrument, start_date, end_date, "
                "request_json, response_hash, retrieved_at, status, cache_policy, "
                "correlation_id, quality_status, error_code"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                ],
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
