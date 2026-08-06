"""BNP OpenAPI 1.60.0 wire-field combination tests."""

from datetime import date

import pytest

from app.clients.cortex.serializers import (
    serialize_volatility_request,
    volatility_request_hash,
)
from app.domain.requests import (
    FixedStrikeRequest,
    ListedMaturityMoneynessRequest,
    SlidingDeltaRequest,
    SlidingMoneynessRequest,
)

COMMON = {
    "code": "US_QQQ",
    "start_date": date(2026, 8, 1),
    "end_date": date(2026, 8, 5),
}
BASE_FIELDS = {
    "code",
    "codeType",
    "maturityRule",
    "strikeRule",
    "volatilityConvention",
    "startDate",
    "endDate",
    "layout",
}


@pytest.mark.parametrize(
    ("vol_request", "mode_fields"),
    [
        (
            SlidingMoneynessRequest(
                **COMMON,
                strike_rule="relative_to_forward",
                low_strike=97.5,
                high_strike=100,
                low_maturity="1M",
                high_maturity="3M",
            ),
            {"lowStrike", "highStrike", "lowMaturity", "highMaturity"},
        ),
        (
            SlidingMoneynessRequest(
                **COMMON,
                strike_rule="relative_to_spot_ref",
                low_strike=100,
                high_strike=100,
                low_maturity="3M",
                high_maturity="3M",
            ),
            {"lowStrike", "highStrike", "lowMaturity", "highMaturity"},
        ),
        (
            SlidingDeltaRequest(
                **COMMON,
                low_delta_strike="p25.0",
                high_delta_strike="c25.0",
                low_maturity="1M",
                high_maturity="3M",
            ),
            {"lowDeltaStrike", "highDeltaStrike", "lowMaturity", "highMaturity"},
        ),
        (
            FixedStrikeRequest(
                **COMMON,
                maturity_rule="fixed",
                low_fixed_strike=600,
                high_fixed_strike=620,
                low_fixed_maturity=date(2026, 9, 18),
                high_fixed_maturity=date(2026, 12, 18),
            ),
            {
                "lowFixedStrike",
                "highFixedStrike",
                "lowFixedMaturity",
                "highFixedMaturity",
            },
        ),
        (
            FixedStrikeRequest(**COMMON, maturity_rule="listed"),
            set(),
        ),
        (
            ListedMaturityMoneynessRequest(
                **COMMON,
                maturity_rule="fixed",
                strike_rule="relative_to_forward",
                low_strike=90,
                high_strike=110,
                low_fixed_maturity=date(2026, 9, 18),
            ),
            {"lowStrike", "highStrike", "lowFixedMaturity"},
        ),
        (
            ListedMaturityMoneynessRequest(
                **COMMON,
                maturity_rule="listed",
                strike_rule="relative_to_spot_ref",
                low_strike=100,
                high_strike=100,
            ),
            {"lowStrike", "highStrike"},
        ),
    ],
)
def test_each_openapi_combination_emits_only_allowed_wire_fields(vol_request, mode_fields):
    body = serialize_volatility_request(vol_request)
    assert set(body) == BASE_FIELDS | mode_fields


def test_wire_encoding_and_dates_match_openapi_examples():
    delta = SlidingDeltaRequest(
        **COMMON,
        low_delta_strike="p25.0",
        high_delta_strike="c10.0",
        low_maturity="1M",
        high_maturity="3M",
    )
    fixed = FixedStrikeRequest(
        **COMMON,
        low_fixed_maturity=date(2026, 9, 18),
        high_fixed_maturity=date(2026, 9, 18),
    )
    assert serialize_volatility_request(delta)["lowDeltaStrike"] == "p25_0"
    assert serialize_volatility_request(delta)["highDeltaStrike"] == "c10_0"
    assert serialize_volatility_request(fixed)["lowFixedMaturity"] == "2026-09-18"


def test_canonical_hash_changes_for_mode_layout_and_optional_bounds():
    requests = [
        SlidingDeltaRequest(**COMMON, low_delta_strike="p25.0"),
        SlidingDeltaRequest(**COMMON, low_delta_strike="p10.0"),
        SlidingDeltaRequest(**COMMON, low_delta_strike="p25.0", layout="vector"),
        FixedStrikeRequest(**COMMON, maturity_rule="fixed"),
        FixedStrikeRequest(**COMMON, maturity_rule="listed"),
        FixedStrikeRequest(**COMMON, maturity_rule="fixed", low_fixed_strike=600),
    ]
    hashes = {volatility_request_hash(request, "1.60.0") for request in requests}
    assert len(hashes) == len(requests)
