"""Gate 2: same request twice — live fetch then persistent cache.

Run 1 (force refresh): live API, normalized result A.
Run 2 (default):       persistent cache, normalized result B.
A and B must be identical. Also prints cache status of each run.

Usage: python scripts/cache_probe.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clients.cortex.client import CortexClient  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.domain.requests import ImpliedVolRequest  # noqa: E402
from app.storage.normalized_store import observations_to_frame  # noqa: E402


def main() -> int:
    settings = get_settings()
    client = CortexClient(settings)

    request = ImpliedVolRequest(
        code="US_QQQ",
        code_type="bnpp",
        maturity_rule="sliding",
        strike_rule="relative_to_forward",
        start_date=date(2026, 7, 30),
        end_date=date(2026, 8, 5),
        low_strike=100.0,
        high_strike=100.0,
        low_maturity="3M",
        high_maturity="3M",
    )

    obs_live, res_live = client.get_implied_volatility(request, force_refresh=True)
    frame_live = observations_to_frame(obs_live)
    print(f"run 1: cacheStatus={res_live.cache_status} rows={len(frame_live)}")

    obs_cache, res_cache = client.get_implied_volatility(request)
    frame_cache = observations_to_frame(obs_cache)
    print(f"run 2: cacheStatus={res_cache.cache_status} rows={len(frame_cache)}")

    identical = frame_live.equals(frame_cache)
    print(f"normalized identical: {identical}")
    if not identical:
        print(frame_live.compare(frame_cache))
        return 1
    if res_live.cache_status != "live" or res_cache.cache_status != "hit":
        print("FAIL: unexpected cache status sequence")
        return 1
    print("Gate 2 PASS (live -> cache, results identical)")
    print(frame_live.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
