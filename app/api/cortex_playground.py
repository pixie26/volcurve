"""Raw Cortex DataHub request playground."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel

from app.api.deps import get_cortex_client
from app.clients.cortex.client import CortexClient
from app.clients.cortex.errors import CortexError, ErrorCode

router = APIRouter(prefix="/api/cortex-playground", tags=["cortex-playground"])
_MAX_BODY_BYTES = 100_000


class PlaygroundResponse(BaseModel):
    endpoint: str
    status: int
    elapsedMs: float
    correlationId: str
    payload: Any


@router.post("/implied-volatility", response_model=PlaygroundResponse)
def post_implied_volatility_raw(
    body: dict[str, Any] = Body(...),
    client: CortexClient = Depends(get_cortex_client),
) -> PlaygroundResponse:
    """Send one editable JSON body directly to Cortex implied-volatility.

    This intentionally bypasses application cache, domain request normalization,
    response parsing, analytics and normalized storage. Existing backend auth,
    timeout, retry, proxy and TLS behaviour are preserved.
    """
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if len(encoded) > _MAX_BODY_BYTES:
        raise CortexError(ErrorCode.INVALID_REQUEST, "Playground JSON body is too large.")

    if getattr(client, "_mode", None) == "fixture":
        raise CortexError(
            ErrorCode.CONFIGURATION_ERROR,
            "Cortex Playground requires live mode.",
        )

    correlation_id = f"play-{uuid.uuid4().hex[:12]}"
    started = time.perf_counter()
    payload = client._request_with_retry(
        "POST",
        "/v1/implied-volatility",
        json_body=body,
        correlation_id=correlation_id,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)

    return PlaygroundResponse(
        endpoint="/v1/implied-volatility",
        status=200,
        elapsedMs=elapsed_ms,
        correlationId=correlation_id,
        payload=payload,
    )
