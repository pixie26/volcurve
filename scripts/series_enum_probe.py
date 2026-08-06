"""Enumerate /v1/series-capable instrument types and their real codes.

The /v1/series request schema (SeriesRange) is just {code, startDate, endDate}
with no enum; valid `code` values are discovered via /v1/instruments?type=<t>.
Series-capable types: quantVault, irs, swaption, commoVol, fxVol.

For each type this probe:
  - GET /v1/instruments?type=<t>
  - report count, record keys, a few example codes
  - quantVault: parse the pipe-delimited `description` field
    (Model Type | Model | Asset Class | Classification | Asset | Region |
     Country | Fields) and aggregate unique values -> the real "enum" of what
     BNP proprietary models / asset classes are available.

Usage: python scripts/series_enum_probe.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.clients.cortex.auth import AuthenticationManager  # noqa: E402
from app.config import get_settings  # noqa: E402

OUT_DIR = ROOT / "data" / "raw" / "instruments"
SERIES_TYPES = ["quantVault", "irs", "swaption", "commoVol", "fxVol"]


def fetch(client: httpx.Client, token: str, base: str, itype: str) -> list:
    resp = client.get(
        f"{base}/v1/instruments",
        params={"type": itype},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    if resp.status_code == 403:
        print(f"  [{itype}] 403 - entitlement denied (no access to this type)")
        return []
    if resp.status_code == 404:
        print(f"  [{itype}] 404 - no data")
        return []
    resp.raise_for_status()
    return resp.json()


def summarize_quantvault(instruments: list) -> None:
    """description = 'Model Type | Model | Asset Class | Classification | Asset | Region | Country | Fields'."""
    fields = [
        "modelType",
        "model",
        "assetClass",
        "classification",
        "asset",
        "region",
        "country",
        "fields",
    ]
    buckets: dict[str, Counter] = {f: Counter() for f in fields}
    n_desc = 0
    for inst in instruments:
        desc = inst.get("description") or ""
        parts = [p.strip() for p in desc.split("|")]
        if len(parts) >= len(fields):
            n_desc += 1
            for name, val in zip(fields, parts, strict=False):
                if val:
                    buckets[name][val] += 1
    print(f"  descriptions parsed: {n_desc}/{len(instruments)}")
    for name in fields:
        c = buckets[name]
        if c:
            top = ", ".join(f"{v}({n})" for v, n in c.most_common(12))
            print(f"  {name:14s}: {len(c):4d} unique | {top}")


def main() -> int:
    settings = get_settings()
    settings.require_credentials()
    auth = AuthenticationManager(settings)
    token = auth.get_token()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(
        verify=settings.bnp_verify_tls, proxy=settings.http_proxy, timeout=120.0
    ) as client:
        for itype in SERIES_TYPES:
            print(f"\n=== type={itype} ===")
            instruments = fetch(client, token, settings.bnp_base_url, itype)
            if not instruments:
                continue
            print(f"  count: {len(instruments)}")
            print(f"  keys : {sorted(instruments[0].keys())}")
            codes = [i.get("code") for i in instruments if i.get("code")]
            print("  sample codes:")
            for c in codes[:6]:
                print(f"    {c}")
            (OUT_DIR / f"instruments_{itype}_full.json").write_text(
                json.dumps(instruments, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            if itype == "quantVault":
                summarize_quantvault(instruments)
    print(f"\nsaved under: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
