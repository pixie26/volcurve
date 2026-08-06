"""Gate E: verify every COMPLETED catalog row against its raw payload hash."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import PROJECT_ROOT, get_settings  # noqa: E402
from app.storage.integrity import audit_raw_cache  # noqa: E402


def _arguments() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Audit catalogued raw Cortex payload hashes")
    parser.add_argument("--catalog", type=Path, default=settings.duckdb_path)
    parser.add_argument("--raw-dir", type=Path, default=settings.raw_dir)
    parser.add_argument(
        "--report",
        type=Path,
        default=(
            PROJECT_ROOT / "data" / "normalized" / "phase_e_validation" / "raw_hash_audit.json"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        report = audit_raw_cache(args.catalog, args.raw_dir)
    except FileNotFoundError:
        print("BLOCKED: raw catalog does not exist; run a live query first.")
        return 2

    report_path = args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    print(
        "raw hash audit: "
        f"checked={report.checked_files}, missing={report.missing_files}, "
        f"unreadable={report.unreadable_files}, mismatch={report.hash_mismatches}, "
        f"orphans={report.orphan_files}"
    )
    print(f"sanitized report: {report_path}")
    return 0 if report.passed and report.completed_rows > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
