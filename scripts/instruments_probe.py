"""Phase 1.1: instrument probe.

Fetches the full equity instrument list, finds QQQ-related entries, and
saves complete metadata for inspection. The BNP code for QQQ must be
discovered here — never assumed in application code.

Usage: python scripts/instruments_probe.py [query]   (default query: QQQ)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.clients.cortex.auth import AuthenticationManager  # noqa: E402
from app.config import get_settings  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "instruments"


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "QQQ"
    settings = get_settings()
    auth = AuthenticationManager(settings)

    with httpx.Client(
        verify=settings.bnp_verify_tls, proxy=settings.http_proxy, timeout=120.0
    ) as client:
        resp = client.get(
            f"{settings.bnp_base_url}/v1/instruments",
            params={"type": "equity"},
            headers={
                "Authorization": f"Bearer {auth.get_token()}",
                "Accept": "application/json",
            },
        )
    resp.raise_for_status()
    instruments = resp.json()
    print(f"total equity instruments: {len(instruments)}")
    if instruments:
        print(f"record keys: {sorted(instruments[0].keys())}")
        print(f"sample record: {json.dumps(instruments[0], ensure_ascii=False)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "instruments_equity_full.json").write_text(
        json.dumps(instruments, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    q = query.lower()
    matches = [inst for inst in instruments if q in json.dumps(inst, ensure_ascii=False).lower()]
    print(f"\n'{query}' matches: {len(matches)}")
    for inst in matches[:50]:
        print(json.dumps(inst, ensure_ascii=False))

    (OUT_DIR / f"instruments_match_{query}.json").write_text(
        json.dumps(matches, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\nsaved: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
