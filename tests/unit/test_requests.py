"""Strict request-mode contracts against Cortex OpenAPI 1.60.0."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.requests import (
    FixedStrikeRequest,
    ListedMaturityMoneynessRequest,
    SlidingDeltaRequest,
    SlidingMoneynessRequest,
    parse_volatility_request,
)

COMMON = {
    "code": "US_QQQ",
    "start_date": date(2025, 1, 1),
    "end_date": date(2025, 2, 1),
}


def test_sliding_moneyness_wire_and_forbidden_fields():
    request = SlidingMoneynessRequest(
        **COMMON,
        strike_rule="relative_to_forward",
        low_strike=97.5,
        high_strike=100.0,
        low_maturity="2W",
        high_maturity="3M",
    )
    body = request.to_api_body()
    assert body["lowStrike"] == "97_5"
    assert body["highStrike"] == "100_0"
    assert body["lowMaturity"] == "2W"
    with pytest.raises(ValidationError):
        SlidingMoneynessRequest(
            **COMMON,
            low_strike=100,
            high_strike=100,
            low_maturity="3M",
            high_maturity="3M",
            low_fixed_strike=300.0,
        )


def test_year_tenor_alias_is_normalized_to_openapi_month_code():
    request = SlidingMoneynessRequest(
        **COMMON,
        low_strike=100,
        high_strike=100,
        low_maturity="2Y",
        high_maturity="5Y",
    )
    assert request.low_maturity == "24M"
    assert request.to_api_body()["highMaturity"] == "60M"


def test_arbitrary_moneyness_is_rejected_instead_of_rounded_to_bnp_grid():
    with pytest.raises(ValidationError):
        SlidingMoneynessRequest(
            **COMMON,
            low_strike=99.5,
            high_strike=100,
            low_maturity="3M",
            high_maturity="3M",
        )


def test_delta_request_uses_readable_domain_and_wire_encoding():
    request = SlidingDeltaRequest(
        **COMMON,
        low_delta_strike="p25.0",
        high_delta_strike="c25.0",
        low_maturity="1M",
        high_maturity="12M",
    )
    body = request.to_api_body()
    assert body["lowDeltaStrike"] == "p25_0"
    assert body["highDeltaStrike"] == "c25_0"
    assert "lowStrike" not in body
    with pytest.raises(ValidationError):
        SlidingDeltaRequest(**COMMON, low_maturity="180M")


def test_fixed_strike_ranges_are_optional_per_openapi():
    all_coordinates = FixedStrikeRequest(**COMMON, maturity_rule="listed")
    assert "lowFixedStrike" not in all_coordinates.to_api_body()
    bounded = FixedStrikeRequest(
        **COMMON,
        low_fixed_strike=300.0,
        high_fixed_strike=400.0,
        low_fixed_maturity=date(2025, 3, 21),
        high_fixed_maturity=date(2025, 6, 20),
    )
    assert bounded.to_api_body()["lowFixedMaturity"] == "2025-03-21"


def test_listed_maturity_moneyness_uses_only_compatible_fields():
    request = ListedMaturityMoneynessRequest(
        **COMMON,
        maturity_rule="fixed",
        strike_rule="relative_to_spot_ref",
        low_strike=90,
        high_strike=110,
        low_fixed_maturity=date(2025, 3, 1),
    )
    body = request.to_api_body()
    assert body["lowStrike"] == "90_0"
    assert body["lowFixedMaturity"] == "2025-03-01"
    assert "lowMaturity" not in body


def test_union_rejects_mixed_mode_and_hash_covers_mode_fields():
    with pytest.raises(ValidationError):
        parse_volatility_request(
            {
                **COMMON,
                "maturity_rule": "sliding",
                "strike_rule": "delta",
                "low_strike": 100,
                "high_strike": 100,
            }
        )
    first = SlidingDeltaRequest(**COMMON, low_delta_strike="p25.0")
    second = SlidingDeltaRequest(**COMMON, low_delta_strike="p10.0")
    assert first.request_hash("1.60.0") != second.request_hash("1.60.0")
