"""Search the BNP instrument catalogue without exposing raw upstream data."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_cortex_client, mark_connectivity
from app.clients.cortex.client import CortexClient
from app.clients.cortex.errors import CortexError, ErrorCode
from app.domain.responses import ActivityEvent, InstrumentSearchResponse

router = APIRouter(prefix="/api/v1", tags=["instruments"])


@router.get("/instruments", response_model=InstrumentSearchResponse)
def instruments(
    request: Request,
    client: Annotated[CortexClient, Depends(get_cortex_client)],
    q: Annotated[str, Query(max_length=128)] = "",
    instrument_type: Annotated[Literal["equity"], Query(alias="type")] = "equity",
    max_results: Annotated[int, Query(alias="maxResults", ge=1, le=200)] = 50,
) -> InstrumentSearchResponse:
    query = q.strip().casefold()
    try:
        catalogue, fetch_result = client.get_instruments_with_result(instrument_type)
    except CortexError as exc:
        if exc.code in {ErrorCode.AUTHENTICATION_FAILED, ErrorCode.UPSTREAM_UNAVAILABLE}:
            mark_connectivity(False)
        raise
    if fetch_result.cache_status == "live":
        mark_connectivity(True)

    fields = (
        "code",
        "bbgCode",
        "isin",
        "ric",
        "sedol",
        "companyName",
        "marketName",
    )
    matched = [
        instrument
        for instrument in catalogue
        if not query
        or any(query in str(getattr(instrument, field) or "").casefold() for field in fields)
    ]
    returned = matched[:max_results]
    activity = [
        ActivityEvent(
            code="REQUEST_VALIDATED",
            stage="validation",
            message="Instrument 搜索参数已通过校验。",
        ),
        ActivityEvent(
            code=(
                "FIXTURE_LOADED"
                if fetch_result.cache_status == "fixture"
                else "CACHE_HIT"
                if fetch_result.cache_status == "hit"
                else "UPSTREAM_FETCH_COMPLETED"
            ),
            stage="fetch",
            message=(
                "已加载脱敏 instrument fixture。"
                if fetch_result.cache_status == "fixture"
                else "已使用 instrument catalogue 缓存。"
                if fetch_result.cache_status == "hit"
                else "Instrument catalogue 请求已完成。"
            ),
        ),
        ActivityEvent(
            code="INSTRUMENTS_FILTERED",
            stage="instrument",
            message=f"搜索匹配 {len(matched)} 个 instrument，返回 {len(returned)} 个。",
            affectedObservations=len(returned),
        ),
    ]
    return InstrumentSearchResponse(
        query=q.strip(),
        instrumentType=instrument_type,
        matchedCount=len(matched),
        returnedCount=len(returned),
        hasMore=len(matched) > len(returned),
        instruments=returned,
        activity=activity,
    )
