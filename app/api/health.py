"""Health endpoints. Ready check never acquires a token."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import connectivity_status
from app.config import get_settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict:
    return {"status": "alive"}


@router.get("/ready")
def ready() -> dict:
    settings = get_settings()
    checks = {
        "storage_writable": _storage_writable(settings),
        "configuration": settings.credentials_configured or settings.cortex_mode == "fixture",
        "openapi_schema_present": (
            settings.data_dir.parent / "schemas" / "cortex-openapi.yaml"
        ).exists(),
        "cortex_mode": settings.cortex_mode,
        "cortex_connectivity": connectivity_status(),
    }
    healthy = (
        checks["storage_writable"] and checks["configuration"] and checks["openapi_schema_present"]
    )
    return {"status": "ready" if healthy else "degraded", "checks": checks}


def _storage_writable(settings) -> bool:
    try:
        settings.raw_dir.mkdir(parents=True, exist_ok=True)
        return settings.raw_dir.is_dir()
    except OSError:
        return False
