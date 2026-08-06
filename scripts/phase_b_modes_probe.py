"""Controlled Gate B live probes for every equity volatility request combination.

The script never prints or stores credentials, tokens, headers, raw response
bodies, or individual market values.  It writes only a structural validation
report under gitignored ``data/normalized/phase_b_probe``.

Usage:
    python scripts/phase_b_modes_probe.py
    python scripts/phase_b_modes_probe.py --code US_QQQ --start 2026-07-28 --end 2026-08-05
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.clients.cortex.auth import AuthenticationManager  # noqa: E402
from app.clients.cortex.client import load_api_version  # noqa: E402
from app.clients.cortex.parser import parse_surface_snapshots  # noqa: E402
from app.clients.cortex.serializers import serialize_volatility_request  # noqa: E402
from app.config import PROJECT_ROOT, get_settings  # noqa: E402
from app.domain.requests import (  # noqa: E402
    FixedStrikeRequest,
    ListedMaturityMoneynessRequest,
    SlidingDeltaRequest,
    SlidingMoneynessRequest,
)


def _arguments() -> argparse.Namespace:
    yesterday = date.today() - timedelta(days=1)
    parser = argparse.ArgumentParser(description="Run sanitized Phase B Cortex live probes")
    parser.add_argument("--code", default="US_QQQ")
    parser.add_argument("--start", type=date.fromisoformat, default=yesterday - timedelta(days=10))
    parser.add_argument("--end", type=date.fromisoformat, default=yesterday)
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "data" / "normalized" / "phase_b_probe" / "report.json",
    )
    return parser.parse_args()


def _requests(code: str, start: date, end: date):
    common = {"code": code, "start_date": start, "end_date": end}
    return [
        (
            "sliding_kf",
            SlidingMoneynessRequest(
                **common,
                strike_rule="relative_to_forward",
                low_strike=100,
                high_strike=100,
                low_maturity="3M",
                high_maturity="3M",
            ),
        ),
        (
            "sliding_ks",
            SlidingMoneynessRequest(
                **common,
                strike_rule="relative_to_spot_ref",
                low_strike=100,
                high_strike=100,
                low_maturity="3M",
                high_maturity="3M",
            ),
        ),
        (
            "sliding_delta",
            SlidingDeltaRequest(
                **common,
                low_delta_strike="p25.0",
                high_delta_strike="p25.0",
                low_maturity="3M",
                high_maturity="3M",
            ),
        ),
        ("fixed_absolute", FixedStrikeRequest(**common, maturity_rule="fixed")),
        ("listed_absolute", FixedStrikeRequest(**common, maturity_rule="listed")),
        (
            "fixed_moneyness",
            ListedMaturityMoneynessRequest(
                **common,
                maturity_rule="fixed",
                strike_rule="relative_to_forward",
                low_strike=100,
                high_strike=100,
            ),
        ),
        (
            "listed_moneyness",
            ListedMaturityMoneynessRequest(
                **common,
                maturity_rule="listed",
                strike_rule="relative_to_forward",
                low_strike=100,
                high_strike=100,
            ),
        ),
    ]


def _structural_summary(name, request, snapshots) -> dict:
    flag_counts: Counter[str] = Counter()
    point_count = 0
    usable_count = 0
    shapes = set()
    for snapshot in snapshots:
        shapes.add((len(snapshot.maturities), len(snapshot.strikes)))
        flag_counts.update(flag.value for flag in snapshot.quality_flags if flag.value != "OK")
        for point in snapshot.points:
            point_count += 1
            usable_count += point.implied_vol is not None
            flag_counts.update(flag.value for flag in point.quality_flags if flag.value != "OK")
    return {
        "mode": name,
        "status": "PASS",
        "wireFields": sorted(serialize_volatility_request(request)),
        "observationDates": len(snapshots),
        "surfaceShapes": [list(shape) for shape in sorted(shapes)],
        "pointCount": point_count,
        "usableIvCount": usable_count,
        "qualityFlagCounts": dict(sorted(flag_counts.items())),
    }


def main() -> int:
    args = _arguments()
    settings = get_settings()
    if settings.cortex_mode != "live":
        print("BLOCKED: CORTEX_MODE must be live for Gate B probes.")
        return 2
    if not settings.credentials_configured:
        print("BLOCKED: BNP_CLIENT_ID/BNP_CLIENT_SECRET are not configured.")
        return 2
    if args.end < args.start:
        print("INVALID: --end must be >= --start")
        return 2

    auth = AuthenticationManager(settings)
    results = []
    try:
        token = auth.get_token()
        with httpx.Client(
            verify=settings.bnp_verify_tls,
            proxy=settings.http_proxy,
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
        ) as client:
            for name, request in _requests(args.code, args.start, args.end):
                try:
                    response = client.post(
                        f"{settings.bnp_base_url}/v1/implied-volatility",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        json=serialize_volatility_request(request),
                    )
                    if response.status_code != 200:
                        results.append(
                            {
                                "mode": name,
                                "status": "FAIL",
                                "error": f"HTTP_{response.status_code}",
                            }
                        )
                        print(f"{name}: FAIL HTTP_{response.status_code}")
                        continue
                    payload = response.json()
                    snapshots = parse_surface_snapshots(payload, request)
                    summary = _structural_summary(name, request, snapshots)
                    results.append(summary)
                    print(f"{name}: PASS ({summary['observationDates']} dates)")
                except Exception as exc:  # normalized below without body/headers/paths
                    results.append({"mode": name, "status": "FAIL", "error": type(exc).__name__})
                    print(f"{name}: FAIL {type(exc).__name__}")
    except Exception as exc:
        print(f"AUTH/CONNECTION BLOCKED: {type(exc).__name__}")
        return 2

    report = {
        "gate": "Phase B",
        "apiVersion": load_api_version(PROJECT_ROOT),
        "instrumentCode": args.code,
        "requestedStart": args.start.isoformat(),
        "requestedEnd": args.end.isoformat(),
        "rawPayloadStored": False,
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Sanitized structural report: {args.report}")
    return 0 if results and all(result["status"] == "PASS" for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
