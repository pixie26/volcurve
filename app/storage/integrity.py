"""Read-only integrity audit for the licensed raw-response cache."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from app.storage.raw_store import RawStore


@dataclass(frozen=True)
class RawIntegrityReport:
    catalog_rows: int
    completed_rows: int
    checked_files: int
    missing_files: int
    unreadable_files: int
    hash_mismatches: int
    orphan_files: int

    @property
    def passed(self) -> bool:
        return not (self.missing_files or self.unreadable_files or self.hash_mismatches)


def audit_raw_cache(catalog_path: Path, raw_dir: Path) -> RawIntegrityReport:
    """Recompute every catalogued payload hash without modifying cache state."""
    if not catalog_path.is_file():
        raise FileNotFoundError(f"catalog not found: {catalog_path}")

    connection = duckdb.connect(str(catalog_path), read_only=True)
    try:
        rows = connection.execute(
            "SELECT request_hash, endpoint, response_hash, status FROM requests"
        ).fetchall()
    finally:
        connection.close()

    store = RawStore(raw_dir)
    completed = [row for row in rows if str(row[3]).upper() == "COMPLETED"]
    checked = missing = unreadable = mismatched = 0
    catalogued_paths: set[Path] = set()
    for request_hash, endpoint, expected_hash, _status in completed:
        path = raw_dir / str(endpoint) / f"{request_hash}.json.gz"
        catalogued_paths.add(path.resolve())
        if not path.is_file():
            missing += 1
            continue
        try:
            payload = store.load(str(endpoint), str(request_hash))
        except (OSError, EOFError, UnicodeDecodeError, ValueError):
            unreadable += 1
            continue
        checked += 1
        if payload is None or RawStore.payload_hash(payload) != expected_hash:
            mismatched += 1

    raw_files = (
        {path.resolve() for path in raw_dir.rglob("*.json.gz")} if raw_dir.exists() else set()
    )
    return RawIntegrityReport(
        catalog_rows=len(rows),
        completed_rows=len(completed),
        checked_files=checked,
        missing_files=missing,
        unreadable_files=unreadable,
        hash_mismatches=mismatched,
        orphan_files=len(raw_files - catalogued_paths),
    )
