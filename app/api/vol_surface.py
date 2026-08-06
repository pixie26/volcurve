"""Multi-coordinate volatility surface endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_cortex_client, mark_connectivity
from app.api.presenters import build_surface_response
from app.clients.cortex.client import CortexClient
from app.clients.cortex.errors import CortexError, ErrorCode
from app.domain.api_requests import SurfaceApiRequest
from app.domain.responses import SurfaceResponse

router = APIRouter(prefix="/api/v1/vol", tags=["volatility"])


@router.post("/surface", response_model=SurfaceResponse)
def surface(
    payload: SurfaceApiRequest,
    request: Request,
    client: Annotated[CortexClient, Depends(get_cortex_client)],
) -> SurfaceResponse:
    volatility_request = payload.volatilityRequest
    try:
        snapshots, fetch_result = client.get_implied_volatility_surface(
            volatility_request, force_refresh=payload.forceRefresh
        )
    except CortexError as exc:
        if exc.code in {ErrorCode.AUTHENTICATION_FAILED, ErrorCode.UPSTREAM_UNAVAILABLE}:
            mark_connectivity(False)
        raise
    if fetch_result.cache_status == "live":
        mark_connectivity(True)
    return build_surface_response(
        request_id=request.state.request_id,
        client=client,
        request=volatility_request,
        snapshots=snapshots,
        fetch_result=fetch_result,
    )
