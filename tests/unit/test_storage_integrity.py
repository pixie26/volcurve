from datetime import UTC, datetime

from app.storage.catalog import Catalog
from app.storage.integrity import audit_raw_cache
from app.storage.raw_store import RawStore


def _catalog_row(catalog, payload, *, response_hash):
    catalog.upsert(
        request_hash="abc",
        endpoint="implied-volatility",
        api_version="1.60.0",
        instrument="US_QQQ",
        start_date=None,
        end_date=None,
        request_json="{}",
        response_hash=response_hash,
        retrieved_at=datetime.now(UTC),
        status="COMPLETED",
        cache_policy="historical",
        correlation_id="test",
        quality_status="OK",
    )


def test_raw_integrity_passes_and_counts_orphans(tmp_path):
    raw_dir = tmp_path / "raw"
    db_path = tmp_path / "catalog.duckdb"
    store = RawStore(raw_dir)
    payload = [{"date": "2026-08-05", "value": 1}]
    store.save("implied-volatility", "abc", payload)
    store.save("implied-volatility", "orphan", payload)
    catalog = Catalog(db_path)
    _catalog_row(catalog, payload, response_hash=RawStore.payload_hash(payload))
    catalog.close()

    report = audit_raw_cache(db_path, raw_dir)

    assert report.passed
    assert report.checked_files == 1
    assert report.orphan_files == 1


def test_raw_integrity_detects_hash_mismatch(tmp_path):
    raw_dir = tmp_path / "raw"
    db_path = tmp_path / "catalog.duckdb"
    payload = [{"date": "2026-08-05", "value": 1}]
    RawStore(raw_dir).save("implied-volatility", "abc", payload)
    catalog = Catalog(db_path)
    _catalog_row(catalog, payload, response_hash="not-the-real-hash")
    catalog.close()

    report = audit_raw_cache(db_path, raw_dir)

    assert not report.passed
    assert report.hash_mismatches == 1
