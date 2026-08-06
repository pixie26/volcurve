"""Generate sanitized fixtures from live probe responses.

Fixtures keep the exact response *structure* but with dates shifted to
2020 and values deterministically perturbed, so no real licensed market
data enters the repository.

Usage: python scripts/make_fixtures.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
FIX = ROOT / "tests" / "fixtures"

DATE_SHIFT = date(2020, 1, 2).toordinal() - date(2026, 7, 24).toordinal()


def shift_date(iso: str) -> str:
    return date.fromordinal(date.fromisoformat(iso).toordinal() + DATE_SHIFT).isoformat()


def perturb(value: float, seed: int) -> float:
    """Deterministic +/- few % perturbation, keeps magnitude plausible."""
    factor = 1.0 + ((seed % 7) - 3) * 0.01
    return round(value * factor, 8)


def make_implied_vol_fixture() -> None:
    raw_path = RAW / "implied_volatility" / "probe_A_ks_2026-07-24_2026-08-05.json"
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    for i, entry in enumerate(payload):
        entry["date"] = shift_date(entry["date"])
        entry["code"] = "US_QQQ"
        entry["spot"] = perturb(entry["spot"], i)
        entry["forwardCurve"] = [perturb(v, i + j + 1) for j, v in enumerate(entry["forwardCurve"])]
        entry["zcCurve"] = [perturb(v, i + j + 2) for j, v in enumerate(entry["zcCurve"])]
        entry["matrix"] = [
            [perturb(v, i + j + k + 3) for k, v in enumerate(row)]
            for j, row in enumerate(entry["matrix"])
        ]
        entry["time"] = None
        entry["timeZone"] = None
    (FIX / "implied_vol_surface.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"implied_vol_surface.json: {len(payload)} entries (sanitized)")


def make_instruments_fixture() -> None:
    raw_path = RAW / "instruments" / "instruments_match_QQQ.json"
    matches = json.loads(raw_path.read_text(encoding="utf-8"))
    keep = [m for m in matches if m.get("code") in ("US_QQQ", "US_QQQM", "US_QQQE")]
    for i, inst in enumerate(keep):
        inst["isin"] = f"XX000000{i:04d}"
        inst["sedol"] = f"FICT{i:03d}"
    (FIX / "instruments_equity.json").write_text(
        json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"instruments_equity.json: {len(keep)} instruments (identifiers masked)")


def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    make_implied_vol_fixture()
    make_instruments_fixture()
    return 0


if __name__ == "__main__":
    sys.exit(main())
