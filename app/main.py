"""FastAPI application entry point."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.capabilities import router as capabilities_router
from app.api.cortex_playground import router as cortex_playground_router
from app.api.errors import install_error_handlers
from app.api.exports import router as exports_router
from app.api.health import router as health_router
from app.api.instruments import router as instruments_router
from app.api.vol_compare import router as compare_router
from app.api.vol_surface import router as surface_router
from app.version import __version__

app = FastAPI(
    title="Cortex Vol Analytics",
    version=__version__,
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
app.include_router(cortex_playground_router)
app.include_router(instruments_router)
app.include_router(compare_router)
app.include_router(surface_router)
app.include_router(exports_router)
app.include_router(health_router)
app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")


def _asset_version() -> str:
    """A token that changes whenever any served front-end file changes.

    The static mount hands out ETag/Last-Modified, so browsers happily keep a script or
    stylesheet cached while fetching fresh HTML. A page assembled from two different
    versions breaks in ways that look like ordinary bugs — a handler binds against an
    element the other file has not grown yet, and everything after it in that binding pass
    silently never runs. Stamping the URLs makes each version a distinct resource.
    """
    newest = 0.0
    for name in ("index.html", "app.js", "compare-builder.js", "cortex-playground.js", "styles.css"):
        path = WEB_ROOT / name
        if path.exists():
            newest = max(newest, path.stat().st_mtime)
    return f"{app.version}-{int(newest)}"


@app.get("/", include_in_schema=False)
def web_app() -> HTMLResponse:
    """Serve the Phase D single-page research workspace."""
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    html = html.replace("{{ASSET_VERSION}}", _asset_version())
    # The HTML is the only thing that carries the current version, so it must never be the
    # stale half of the pair.
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})

# VOLCURVE_CORTEX_PLAYGROUND_V1_6
