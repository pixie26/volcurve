"""BNP Cortex wire serialization for strict domain request models."""

from __future__ import annotations

import hashlib
import json

from app.domain.requests import (
    FixedStrikeRequest,
    ListedMaturityMoneynessRequest,
    SlidingDeltaRequest,
    SlidingMoneynessRequest,
    VolatilityRequest,
)


def strike_to_wire(value: float) -> str:
    rendered = f"{value:.10f}".rstrip("0").rstrip(".")
    if "." not in rendered:
        rendered += ".0"
    return rendered.replace(".", "_")


def delta_to_wire(value: str) -> str:
    return value.replace(".", "_")


def _common(request: VolatilityRequest) -> dict:
    return {
        "code": request.code,
        "codeType": request.code_type,
        "maturityRule": request.maturity_rule,
        "strikeRule": request.strike_rule,
        "volatilityConvention": request.volatility_convention,
        "startDate": request.start_date.isoformat(),
        "endDate": request.end_date.isoformat(),
        "layout": request.layout,
    }


def serialize_volatility_request(request: VolatilityRequest) -> dict:
    """Serialize only the fields permitted for the concrete request mode."""
    body = _common(request)
    if isinstance(request, SlidingMoneynessRequest):
        body.update(
            lowStrike=strike_to_wire(request.low_strike),
            highStrike=strike_to_wire(request.high_strike),
            lowMaturity=request.low_maturity,
            highMaturity=request.high_maturity,
        )
        return body
    if isinstance(request, SlidingDeltaRequest):
        optional = {
            "lowDeltaStrike": delta_to_wire(request.low_delta_strike)
            if request.low_delta_strike
            else None,
            "highDeltaStrike": delta_to_wire(request.high_delta_strike)
            if request.high_delta_strike
            else None,
            "lowMaturity": request.low_maturity,
            "highMaturity": request.high_maturity,
        }
    elif isinstance(request, FixedStrikeRequest):
        optional = {
            "lowFixedStrike": request.low_fixed_strike,
            "highFixedStrike": request.high_fixed_strike,
            "lowFixedMaturity": request.low_fixed_maturity.isoformat()
            if request.low_fixed_maturity
            else None,
            "highFixedMaturity": request.high_fixed_maturity.isoformat()
            if request.high_fixed_maturity
            else None,
        }
    elif isinstance(request, ListedMaturityMoneynessRequest):
        body.update(
            lowStrike=strike_to_wire(request.low_strike),
            highStrike=strike_to_wire(request.high_strike),
        )
        optional = {
            "lowFixedMaturity": request.low_fixed_maturity.isoformat()
            if request.low_fixed_maturity
            else None,
            "highFixedMaturity": request.high_fixed_maturity.isoformat()
            if request.high_fixed_maturity
            else None,
        }
    else:  # pragma: no cover - the strict union makes this defensive only
        raise TypeError(f"unsupported volatility request: {type(request).__name__}")
    body.update({key: value for key, value in optional.items() if value is not None})
    return body


def volatility_request_hash(request: VolatilityRequest, api_version: str) -> str:
    canonical = json.dumps(
        serialize_volatility_request(request), sort_keys=True, separators=(",", ":")
    )
    payload = f"implied-volatility|{api_version}|{canonical}".encode()
    return hashlib.sha256(payload).hexdigest()[:32]
