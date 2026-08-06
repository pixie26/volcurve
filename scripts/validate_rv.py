"""Gate 3: independent RV recomputation vs analytics engine.

Independence: this script re-derives realized vol directly from the raw
API payload (entry['spot']) using only stdlib math/statistics — none of
app.analytics code is used for the reference values. Engine output is
then compared date-by-date with tolerance 1e-10.

Also verifies:
- IV in engine output equals raw matrix value at resolved coordinates
- trailing RV is null before the first full window (no-warmup view)
- forward RV tail is null
- no zero-filling anywhere

Writes data/normalized/validation/rv_recheck.csv for Excel cross-check
(Excel: STDEV.S(log returns) * SQRT(252)).

Usage: python scripts/validate_rv.py
"""

from __future__ import annotations

import csv
import math
import sys
from datetime import date
from pathlib import Path
from statistics import stdev

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.analytics.alignment import warmup_start  # noqa: E402
from app.analytics.engine import run_compare  # noqa: E402
from app.clients.cortex.client import CortexClient  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.domain.requests import ImpliedVolRequest  # noqa: E402

TOL = 1e-10
DISPLAY_FROM = date(2025, 8, 6)
DISPLAY_TO = date(2026, 8, 5)
WINDOW = 63


def independent_rv(dates: list[str], spots: list[float], window: int) -> list[float | None]:
    """Standalone reference implementation (stdlib only)."""
    rets = [None]
    for a, b in zip(spots, spots[1:]):
        rets.append(math.log(b / a))
    out: list[float | None] = []
    for i in range(len(spots)):
        if i < window:
            out.append(None)
        else:
            out.append(stdev(rets[i - window + 1 : i + 1]) * math.sqrt(252))
    return out


def main() -> int:
    settings = get_settings()
    client = CortexClient(settings)

    fetch_from = warmup_start(DISPLAY_FROM, WINDOW)
    request = ImpliedVolRequest(
        code="US_QQQ",
        code_type="bnpp",
        maturity_rule="sliding",
        strike_rule="relative_to_forward",
        start_date=fetch_from,
        end_date=DISPLAY_TO,
        low_strike=100.0,
        high_strike=100.0,
        low_maturity="3M",
        high_maturity="3M",
    )
    observations, fetch = client.get_implied_volatility(request)
    print(f"fetched {len(observations)} obs from {fetch_from} to {DISPLAY_TO} "
          f"(cacheStatus={fetch.cache_status})")

    # --- independent reference from the raw payload ---
    raw_by_date = {}
    for entry in fetch.payload:
        mi = entry["maturities"].index("3M")
        si = entry["strikes"].index("100.0")
        raw_by_date[entry["date"]] = {
            "spot": entry["spot"],
            "iv": entry["matrix"][mi][si],
            "forward": entry["forwardCurve"][mi],
        }
    all_dates = [o.date.isoformat() for o in observations]
    all_spots = [raw_by_date[d]["spot"] for d in all_dates]
    ref_rv = independent_rv(all_dates, all_spots, WINDOW)
    ref_rv_by_date = dict(zip(all_dates, ref_rv))

    # --- engine ---
    result = run_compare(
        observations,
        display_from=DISPLAY_FROM,
        display_to=DISPLAY_TO,
        window_sessions=WINDOW,
        alignment="trailing",
    )

    mismatches = []
    iv_mismatches = []
    out_rows = []
    for e in result.series:
        d = e.date.isoformat()
        ref = ref_rv_by_date.get(d)
        if e.realized_vol is None and ref is None:
            diff = 0.0
        elif e.realized_vol is None or ref is None:
            diff = float("inf")
        else:
            diff = abs(e.realized_vol - ref)
        if diff > TOL:
            mismatches.append((d, e.realized_vol, ref))
        raw_iv = raw_by_date[d]["iv"]
        if e.implied_vol != raw_iv:
            iv_mismatches.append((d, e.implied_vol, raw_iv))
        out_rows.append((d, raw_by_date[d]["spot"], raw_iv, e.realized_vol, ref, diff))

    # --- gate checks ---
    ok = True
    print(f"\ndisplay rows: {len(result.series)} ({DISPLAY_FROM}..{DISPLAY_TO})")
    if mismatches:
        ok = False
        print(f"FAIL: RV mismatches ({len(mismatches)}), first: {mismatches[0]}")
    else:
        print(f"PASS: RV matches independent recomputation (tol={TOL})")
    if iv_mismatches:
        ok = False
        print(f"FAIL: IV mismatches ({len(iv_mismatches)}), first: {iv_mismatches[0]}")
    else:
        print("PASS: IV equals raw matrix value at resolved coordinates")

    zero_filled = [r for r in out_rows if r[3] == 0.0]
    if zero_filled:
        ok = False
        print(f"FAIL: {len(zero_filled)} zero-filled RV values")
    else:
        print("PASS: no zero-filled values")

    # no-warmup view: trailing RV must be null for first WINDOW sessions
    no_warmup = run_compare(
        observations,
        display_from=observations[0].date,
        display_to=DISPLAY_TO,
        window_sessions=WINDOW,
        alignment="trailing",
    )
    head = no_warmup.series[:WINDOW]
    if all(s.realized_vol is None for s in head):
        print(f"PASS: first {WINDOW} sessions RV is null without warm-up data")
    else:
        ok = False
        print("FAIL: RV not null before first full window")

    fwd = run_compare(
        observations,
        display_from=DISPLAY_FROM,
        display_to=DISPLAY_TO,
        window_sessions=WINDOW,
        alignment="forward",
    )
    if all(s.realized_vol is None for s in fwd.series[-WINDOW:]):
        print(f"PASS: forward RV tail ({WINDOW} sessions) is null")
    else:
        ok = False
        print("FAIL: forward RV tail not null")

    # --- CSV for Excel cross-check ---
    out_dir = Path(__file__).resolve().parent.parent / "data" / "normalized" / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "rv_recheck.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "spot", "iv_raw", "rv_engine", "rv_independent", "abs_diff"])
        w.writerows(out_rows)
    print(f"\nwrote {csv_path}")
    print(f"sample: {out_rows[0]}\n        {out_rows[-1]}")
    print("\nGate 3 " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
