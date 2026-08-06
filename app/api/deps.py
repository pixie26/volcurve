"""Shared dependencies: singleton CortexClient and a last-connectivity beacon.

The ready check reads the beacon instead of forcing a token fetch, per
the agreed rule that health checks must not acquire tokens.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from app.clients.cortex.client import CortexClient
from app.config import Settings, get_settings

_last_connectivity: dict[str, float | bool | None] = {"connected": None, "at": 0.0}
_lock = threading.Lock()


def mark_connectivity(ok: bool) -> None:
    with _lock:
        _last_connectivity["connected"] = ok
        _last_connectivity["at"] = time.time()


def connectivity_status() -> dict:
    with _lock:
        connected = _last_connectivity["connected"]
        ts = float(_last_connectivity["at"])
    if connected is None or ts == 0.0:
        return {"connected": None, "since": None}
    return {"connected": connected, "since": datetime.fromtimestamp(ts, UTC).isoformat()}


_CLIENT: CortexClient | None = None
_CLIENT_LOCK = threading.Lock()

# Bound concurrent compare requests so the single-user tool doesn't fan out.
_COMPARE_SEMAPHORE = threading.BoundedSemaphore(4)


def get_client(settings: Settings | None = None) -> CortexClient:
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = CortexClient(settings or get_settings())
    return _CLIENT


def get_cortex_client() -> CortexClient:
    """FastAPI dependency kept parameter-free for a clean public OpenAPI schema."""
    return get_client()
