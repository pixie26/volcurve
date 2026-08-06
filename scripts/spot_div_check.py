"""Dividend-adjustment check: is the BNP `spot` field raw or div-adjusted?

Method:
  1. Pull 2y of QQQ daily spot from BNP /v1/implied-volatility responses.
     We request a minimal grid (narrow strikes / short maturities) because
     only the per-date `spot` field matters; spot is independent of the grid.
     The range is chunked by quarter to stay within any single-request cap.
  2. Fetch the same window from Yahoo Finance v8 chart API (no extra dep -
     httpx only): raw `close` (unadjusted) + `adjclose` (split+div adjusted)
     + dividend events.
  3. Align on calendar date. Compute two ratios over time:
        ratio_raw = BNP_spot / Yahoo_close
        ratio_adj = BNP_spot / Yahoo_adjclose
     and their OLS slope (drift per year).

Decision rule (QQQ has no stock split in this window, so split normalization
is a non-confound):
  - ratio_raw flat (~0 slope) AND ratio_adj slopes DOWN toward today
    => BNP spot is RAW (not div-adjusted).  [a priori expectation]
  - ratio_adj flat AND ratio_raw slopes UP toward today
    => BNP spot is DIV-ADJUSTED.

A priori: option strikes are nominal, so the reference spot used for IV
calibration should be the raw traded price; this check confirms empirically.

Usage:  python scripts/spot_div_check.py
Output: data/normalized/spot_div_check/qqq_spot_div_check.csv  (gitignored)
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import pandas as pd  # noqa: E402

from app.clients.cortex.auth import AuthenticationManager  # noqa: E402
from app.clients.cortex.client import CortexClient  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.domain.requests import ImpliedVolRequest  # noqa: E402

QQQ_CODE = "US_QQQ"  # probe-confirmed BNP code (ric=QQQ.OQ)
YEARS = 2
CHUNK_DAYS = 90  # quarterly chunks
OUT_DIR = ROOT / "data" / "normalized" / "spot_div_check"
YAHOO_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def quarter_chunks(start: date, end: date) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=CHUNK_DAYS), end)
        chunks.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return chunks


def fetch_bnp_spots(start: date, end: date) -> dict[str, float | None]:
    """Return {date_str: spot} over [start, end]. None where BNP omits spot."""
    settings = get_settings()
    settings.require_credentials()
    auth = AuthenticationManager(settings)
    client = CortexClient(settings, auth=auth)

    spots: dict[str, float | None] = {}
    for c_start, c_end in quarter_chunks(start, end):
        req = ImpliedVolRequest(
            code=QQQ_CODE,
            code_type="bnpp",
            maturity_rule="sliding",
            strike_rule="relative_to_forward",
            low_strike=95.0,
            high_strike=105.0,
            low_maturity="1M",
            high_maturity="2M",
            start_date=c_start,
            end_date=c_end,
            layout="matrix",
        )
        _observations, result = client.get_implied_volatility(req)
        n = 0
        for entry in result.payload:
            d = entry.get("date")
            s = entry.get("spot")
            if d is None:
                continue
            spots[d] = float(s) if s is not None else None
            n += 1
        print(f"  BNP {c_start}..{c_end}: {n} days (cache={result.cache_status})")
        time.sleep(0.3)
    return spots


def fetch_yahoo(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Yahoo v8 chart: raw close + adjclose + dividends. httpx only."""
    period1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    period2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 86400
    params = {"period1": period1, "period2": period2, "interval": "1d", "events": "div,split"}
    headers = {"User-Agent": YAHOO_UA}
    last_err = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{symbol}"
        try:
            r = httpx.get(url, params=params, headers=headers, timeout=30.0)
            if r.status_code != 200:
                last_err = f"{host} HTTP {r.status_code}"
                continue
            data = r.json()
            res = data["chart"]["result"][0]
            ts = res["timestamp"]
            closes = res["indicators"]["quote"][0]["close"]
            adjcloses = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
            divs = res.get("events", {}).get("dividends", {})
            rows = []
            for t, c, a in zip(ts, closes, adjcloses or [None] * len(ts)):
                d = datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()
                rows.append({"date": d, "close": c, "adjclose": a})
            df = pd.DataFrame(rows).dropna(subset=["close"])
            total_div = sum(v.get("amount", 0) for v in divs.values())
            print(f"  Yahoo {symbol}: {len(df)} days, {len(divs)} dividends, total=${total_div:.2f}")
            return df
        except Exception as exc:  # noqa: BLE001
            last_err = f"{host}: {exc}"
    raise RuntimeError(f"Yahoo fetch failed: {last_err}")


def ols_slope_per_year(series: pd.Series) -> float:
    """OLS slope of `series` (indexed by row order) converted to per-year."""
    s = series.dropna()
    if len(s) < 5:
        return float("nan")
    x = (s.index - s.index[0]).to_series().astype(float)  # row-index distance
    y = s.values
    slope = (len(x) * (x * y).sum() - x.sum() * y.sum()) / (
        len(x) * (x * x).sum() - x.sum() ** 2
    )
    # avg trading days spanned per row step
    return float(slope) * 252.0


def main() -> int:
    end = date.today()
    start = end - timedelta(days=365 * YEARS)
    print(f"=== QQQ spot dividend-adjustment check: {start} .. {end} ===")

    print("\n[1/3] BNP spot (2y, quarterly chunks):")
    bnp = fetch_bnp_spots(start, end)
    present = {d: s for d, s in bnp.items() if s is not None}
    missing = [d for d, s in bnp.items() if s is None]
    print(f"  BNP days with spot: {len(present)}; spot empty: {len(missing)}")
    if missing:
        print(f"  empty-spot sample: {missing[:5]}")

    print("\n[2/3] Yahoo Finance:")
    yh = fetch_yahoo("QQQ", start, end)

    print("\n[3/3] Comparison:")
    bnp_df = pd.DataFrame(
        [{"date": d, "bnp_spot": s} for d, s in present.items()]
    )
    bnp_df["date"] = pd.to_datetime(bnp_df["date"])
    yh["date"] = pd.to_datetime(yh["date"])
    m = bnp_df.merge(yh, on="date", how="inner").sort_values("date").reset_index(drop=True)
    if m.empty:
        print("  !! no overlapping dates - abort")
        return 1
    m["ratio_raw"] = m["bnp_spot"] / m["close"]
    m["ratio_adj"] = m["bnp_spot"] / m["adjclose"]

    slope_raw = ols_slope_per_year(m["ratio_raw"])
    slope_adj = ols_slope_per_year(m["ratio_adj"])
    corr_raw = m["bnp_spot"].corr(m["close"])
    corr_adj = m["bnp_spot"].corr(m["adjclose"])

    print(f"  overlap days      : {len(m)}")
    print(f"  date range        : {m['date'].min().date()} .. {m['date'].max().date()}")
    print(f"  BNP spot range    : {m['bnp_spot'].min():.2f} .. {m['bnp_spot'].max():.2f}")
    print(f"  ratio_raw  mean={m['ratio_raw'].mean():.5f}  std={m['ratio_raw'].std():.5f}")
    print(f"  ratio_adj  mean={m['ratio_adj'].mean():.5f}  std={m['ratio_adj'].std():.5f}")
    print(f"  slope_raw (per yr): {slope_raw:+.5f}")
    print(f"  slope_adj (per yr): {slope_adj:+.5f}")
    print(f"  corr(BNP,close)   : {corr_raw:.6f}")
    print(f"  corr(BNP,adjclose): {corr_adj:.6f}")

    # Decision: which ratio is flatter (closer to 0 slope)?
    print("\n  --- conclusion ---")
    if abs(slope_raw) < abs(slope_adj):
        print("  ratio_raw is flatter than ratio_adj.")
        print("  => BNP spot tracks RAW close (NOT dividend-adjusted).")
    elif abs(slope_adj) < abs(slope_raw):
        print("  ratio_adj is flatter than ratio_raw.")
        print("  => BNP spot tracks DIV-ADJUSTED close.")
    else:
        print("  slopes too close to call; inspect CSV.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "qqq_spot_div_check.csv"
    m.to_csv(out, index=False)
    print(f"\n  CSV saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
