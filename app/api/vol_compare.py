"""Single-coordinate IV/RV comparison endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_cortex_client, mark_connectivity
from app.api.presenters import build_compare_response
from app.clients.cortex.client import CortexClient
from app.clients.cortex.errors import CortexError, ErrorCode
from app.clients.cortex.parser import exact_coordinate
from app.domain.api_requests import CompareApiRequest
from app.domain.responses import CompareResponse
from app.services.compare import execute_compare

router = APIRouter(prefix="/api/v1/vol", tags=["volatility"])


def execute_compare_query(
    payload: CompareApiRequest, *, request_id: str, client
) -> CompareResponse:
    volatility_request = payload.volatilityRequest
    exact_coordinate(volatility_request)
    try:
        execution = execute_compare(
            client,
            volatility_request,
            window_sessions=payload.rvWindowSessions,
            alignment=payload.rvAlignment,
            available_through=payload.availableThrough,
            force_refresh=payload.forceRefresh,
            include_realized_vol=payload.includeRealizedVol,
        )
    except CortexError as exc:
        if exc.code in {ErrorCode.AUTHENTICATION_FAILED, ErrorCode.UPSTREAM_UNAVAILABLE}:
            mark_connectivity(False)
        raise
    if any(result.cache_status == "stale" for result in execution.load.fetch_results):
        mark_connectivity(False)
    elif any(result.cache_status == "live" for result in execution.load.fetch_results):
        mark_connectivity(True)
    return build_compare_response(
        request_id=request_id,
        client=client,
        request=volatility_request,
        execution=execution,
    )


@router.post("/compare", response_model=CompareResponse)
def compare(
    payload: CompareApiRequest,
    request: Request,
    client: Annotated[CortexClient, Depends(get_cortex_client)],
) -> CompareResponse:
    return execute_compare_query(payload, request_id=request.state.request_id, client=client)
