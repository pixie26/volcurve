"""Machine-readable backend capability registry for the dynamic UI."""

from __future__ import annotations

from fastapi import APIRouter

from app.clients.cortex.client import load_api_version
from app.config import PROJECT_ROOT
from app.domain.api_requests import RV_WINDOW_MIN, RV_WINDOW_PRESETS
from app.domain.disclosures import disclosure_payload
from app.domain.requests import (
    DELTA_CODES,
    DELTA_MATURITIES,
    MATURITY_ALIASES,
    MONEYNESS_LEVELS,
    SLIDING_MATURITIES,
)

router = APIRouter(prefix="/api/v1", tags=["capabilities"])


def capability_payload() -> dict:
    """Return implemented capabilities, never aspirational frontend options."""
    return {
        "apiVersion": load_api_version(PROJECT_ROOT),
        "requestModes": [
            {
                "id": "sliding_moneyness",
                "maturityRules": ["sliding"],
                "strikeRules": ["relative_to_forward", "relative_to_spot_ref"],
                "enabled": True,
                "evidence": {
                    "requestModel": True,
                    "serializer": True,
                    "parser": True,
                    "fixture": True,
                    "liveProbe": True,
                },
            },
            {
                "id": "sliding_delta",
                "maturityRules": ["sliding"],
                "strikeRules": ["delta"],
                "enabled": True,
                "evidence": {
                    "requestModel": True,
                    "serializer": True,
                    "parser": True,
                    "fixture": True,
                    "liveProbe": True,
                },
            },
            {
                "id": "fixed_strike",
                "maturityRules": ["fixed", "listed"],
                "strikeRules": ["fixed"],
                "enabled": True,
                "evidence": {
                    "requestModel": True,
                    "serializer": True,
                    "parser": True,
                    "fixture": True,
                    "liveProbe": True,
                },
            },
            {
                "id": "listed_moneyness",
                "maturityRules": ["fixed", "listed"],
                "strikeRules": ["relative_to_forward", "relative_to_spot_ref"],
                "enabled": True,
                "evidence": {
                    "requestModel": True,
                    "serializer": True,
                    "parser": True,
                    "fixture": True,
                    "liveProbe": True,
                },
            },
        ],
        "slidingMaturities": list(SLIDING_MATURITIES),
        "slidingMaturityAliases": MATURITY_ALIASES,
        "deltaMaturities": list(DELTA_MATURITIES),
        "deltaStrikes": list(DELTA_CODES),
        "moneynessLevels": list(MONEYNESS_LEVELS),
        "indicators": [
            "implied_vol",
            "realized_vol",
            "spot",
            "forward",
            "iv_minus_rv",
            "iv_divided_by_rv",
            "percentile",
            "zscore",
            "correlation",
            "smile",
            "term_structure",
        ],
        "rvWindows": list(RV_WINDOW_PRESETS),
        "rvWindowRange": {
            "minimum": RV_WINDOW_MIN,
            "maximum": None,
            "integerOnly": True,
            "nearestSubstitution": False,
        },
        "rvAlignments": ["trailing", "forward"],
        "volatilityUnits": "percent_at_api_boundary",
        "priceSource": "Cortex spot",
        "priceAdjustment": "unadjusted",
        "returnType": "price_return",
        "corporateActionSource": None,
        "instrumentSearch": {
            "types": ["equity"],
            "defaultMaxResults": 50,
            "maximumMaxResults": 200,
        },
        "endpoints": {
            "instruments": "/api/v1/instruments",
            "compare": "/api/v1/vol/compare",
            "surface": "/api/v1/vol/surface",
            "compareCsv": "/api/v1/vol/compare.csv",
        },
        "disclosures": disclosure_payload(),
    }


@router.get("/capabilities")
def capabilities() -> dict:
    return capability_payload()
