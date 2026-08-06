"""Phase 1.2-1.5: QQQ implied-volatility probe.

Sends short-range requests to /v1/implied-volatility and answers:
- Request A: sliding 3M, K/S=100 (relative_to_spot_ref)
- Request B: sliding 3M, K/F=100 (relative_to_forward)
- Request C: non-square grid (2 maturities x N strikes) to determine
  matrix orientation and IV units unambiguously.

Raw responses are saved under data/raw/implied_volatility/.
Produces data/normalized/qqq_probe/qqq_probe.csv (Gate 1).

Usage: python scripts/qqq_probe.py
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.clients.cortex.auth import AuthenticationManager  # noqa: E402
from app.config import get_settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "implied_volatility"
OUT_DIR = ROOT / "data" / "normalized" / "qqq_probe"

QQQ_CODE = "US_QQQ"  # resolved by instruments_probe; codeType=bnpp
START = "2026-07-24"
END = "2026-08-05"


def post(client: httpx.Client, settings, token: str, body: dict) -> list:
    resp = client.post(
        f"{settings.bnp_base_url}/v1/implied-volatility",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=body,
    )
    if resp.status_code != 200:
        print(f"  !! status={resp.status_code} body[:400]={resp.text[:400]}")
        resp.raise_for_status()
    return resp.json()


def analyze_entry(entry: dict, label: str) -> None:
    mats = entry.get("maturities") or []
    strikes = entry.get("strikes") or []
    matrix = entry.get("matrix") or []
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    print(f"  [{label}] date={entry.get('date')} spot={entry.get('spot')}")
    print(f"    maturities({len(mats)})={mats}")
    print(f"    strikes({len(strikes)})={strikes}")
    print(f"    matrix: {rows} rows x {cols} cols")
    if rows:
        print(f"    matrix sample row0={matrix[0]}")
    fwd = entry.get("forwardCurve") or []
    zc = entry.get("zcCurve") or []
    print(f"    forwardCurve({len(fwd)})={fwd}")
    print(f"    zcCurve({len(zc)})={zc}")
    print(f"    time={entry.get('time')} timeZone={entry.get('timeZone')}")


def main() -> int:
    settings = get_settings()
    auth = AuthenticationManager(settings)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    base = {
        "code": QQQ_CODE,
        "codeType": "bnpp",
        "maturityRule": "sliding",
        "volatilityConvention": "bsVol",
        "layout": "matrix",
    }
    req_a = {
        **base,
        "strikeRule": "relative_to_spot_ref",
        "startDate": START,
        "endDate": END,
        "lowStrike": "100_0",
        "highStrike": "100_0",
        "lowMaturity": "3M",
        "highMaturity": "3M",
    }
    req_b = {**req_a, "strikeRule": "relative_to_forward"}
    req_c = {
        **base,
        "strikeRule": "relative_to_spot_ref",
        "startDate": "2026-08-04",
        "endDate": "2026-08-05",
        "lowStrike": "80_0",
        "highStrike": "120_0",
        "lowMaturity": "1M",
        "highMaturity": "6M",
    }

    with httpx.Client(
        verify=settings.bnp_verify_tls, proxy=settings.http_proxy, timeout=120.0
    ) as client:
        token = auth.get_token()
        print("== Request A: K/S=100, 3M sliding ==")
        data_a = post(client, settings, token, req_a)
        print("== Request B: K/F=100, 3M sliding ==")
        data_b = post(client, settings, token, req_b)
        print("== Request C: orientation grid 80-120 x 1M-6M ==")
        data_c = post(client, settings, token, req_c)

    (RAW_DIR / f"probe_A_ks_{START}_{END}.json").write_text(
        json.dumps(data_a, indent=1), encoding="utf-8"
    )
    (RAW_DIR / f"probe_B_kf_{START}_{END}.json").write_text(
        json.dumps(data_b, indent=1), encoding="utf-8"
    )
    (RAW_DIR / "probe_C_grid.json").write_text(
        json.dumps(data_c, indent=1), encoding="utf-8"
    )

    print(f"\nA entries: {len(data_a)}, B entries: {len(data_b)}, C entries: {len(data_c)}")
    if data_a:
        analyze_entry(data_a[-1], "A last")
    if data_b:
        analyze_entry(data_b[-1], "B last")
    if data_c:
        analyze_entry(data_c[-1], "C last")

    # ---- orientation / units summary on C ----
    if data_c:
        e = data_c[-1]
        mats, strikes, matrix = e["maturities"], e["strikes"], e["matrix"]
        rows, cols = len(matrix), len(matrix[0])
        if rows == len(mats) and cols == len(strikes):
            print("\nORIENTATION: matrix rows = maturities, cols = strikes")
        elif rows == len(strikes) and cols == len(mats):
            print("\nORIENTATION: matrix rows = strikes, cols = maturities")
        else:
            print(f"\nORIENTATION UNRESOLVED: {rows}x{cols} vs mats={len(mats)} strikes={len(strikes)}")
        flat = [v for row in matrix for v in row if v is not None]
        if flat:
            print(f"UNITS check: min={min(flat)} max={max(flat)} "
                  f"({'percent' if max(flat) > 3 else 'decimal'})")

    # ---- build qqq_probe.csv: join A and B by date ----
    def iv_of(entry):
        m = entry.get("matrix") or []
        return m[0][0] if m and m[0] else None  # single-point request: verify dims in output above

    def fwd_of(entry):
        f = entry.get("forwardCurve") or []
        return f[0] if f else None

    b_by_date = {e["date"]: e for e in data_b}
    rows_out = []
    for ea in data_a:
        d = ea["date"]
        eb = b_by_date.get(d)
        flags = []
        if iv_of(ea) is None:
            flags.append("MISSING_IV_KS")
        if eb is None or iv_of(eb) is None:
            flags.append("MISSING_IV_KF")
        if ea.get("spot") in (None, 0):
            flags.append("MISSING_SPOT")
        if not flags:
            flags.append("OK")
        rows_out.append(
            {
                "date": d,
                "instrument_code": QQQ_CODE,
                "spot": ea.get("spot"),
                "target_maturity": "3M",
                "returned_maturity": (ea.get("maturities") or [None])[0],
                "strike_rule_ks": "relative_to_spot_ref",
                "target_strike": 100,
                "returned_strike_ks": (ea.get("strikes") or [None])[0],
                "iv_ks_100": iv_of(ea),
                "iv_kf_100": iv_of(eb) if eb else None,
                "forward_3m": fwd_of(ea),
                "snapshot_time": f"{ea.get('time')} {ea.get('timeZone')}",
                "quality_flags": "|".join(flags),
            }
        )

    csv_path = OUT_DIR / "qqq_probe.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(rows_out)
    print(f"\nwrote {csv_path} ({len(rows_out)} rows)")
    for r in rows_out:
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
