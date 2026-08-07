"""FastAPI application entry point."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.capabilities import router as capabilities_router
from app.api.errors import install_error_handlers
from app.api.exports import router as exports_router
from app.api.health import router as health_router
from app.api.instruments import router as instruments_router
from app.api.vol_compare import router as compare_router
from app.api.vol_surface import router as surface_router

app = FastAPI(
    title="Cortex Vol Analytics",
    version="0.4.0",
    description="Internal volatility analytics backed by Cortex DataHub.",
)

WEB_ROOT = Path(__file__).resolve().parent / "web"


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


install_error_handlers(app)
app.include_router(capabilities_router)
app.include_router(instruments_router)
app.include_router(compare_router)
app.include_router(surface_router)
app.include_router(exports_router)
app.include_router(health_router)
app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")


@app.get("/", include_in_schema=False)
def web_app() -> HTMLResponse:
    """Serve the Phase D single-page research workspace."""
    return HTMLResponse((WEB_ROOT / "index.html").read_text(encoding="utf-8"))
