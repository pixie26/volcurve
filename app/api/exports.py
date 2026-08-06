"""CSV export built from the exact same percent-unit CompareResponse as JSON."""

from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_cortex_client
from app.api.vol_compare import execute_compare_query
from app.clients.cortex.client import CortexClient
from app.domain.api_requests import CompareApiRequest

router = APIRouter(prefix="/api/v1/vol", tags=["exports"])

_FIELDS = (
    "date",
    "spot",
    "forward",
    "raw_implied_vol",
    "implied_vol",
    "realized_vol",
    "iv_minus_rv",
    "iv_divided_by_rv",
    "quality_flags",
)


@router.post("/compare.csv")
def compare_csv(
    payload: CompareApiRequest,
    request: Request,
    client: Annotated[CortexClient, Depends(get_cortex_client)],
) -> Response:
    comparison = execute_compare_query(payload, request_id=request.state.request_id, client=client)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_FIELDS, lineterminator="\n")
    writer.writeheader()
    for point in comparison.series:
        writer.writerow(
            {
                "date": point.date.isoformat(),
                "spot": point.spot,
                "forward": point.forward,
                "raw_implied_vol": point.rawImpliedVol,
                "implied_vol": point.impliedVol,
                "realized_vol": point.realizedVol,
                "iv_minus_rv": point.ivMinusRv,
                "iv_divided_by_rv": point.ivDividedByRv,
                "quality_flags": "|".join(point.qualityFlags),
            }
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="volcurve_compare.csv"',
            "X-Request-ID": request.state.request_id,
            "X-Activity-Event": "CSV_GENERATED",
        },
    )
