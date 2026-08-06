"""Contract fixtures for every Phase B volatility request mode."""

import json
from datetime import date
from pathlib import Path

import pytest

from app.clients.cortex.errors import CortexError, ErrorCode
from app.clients.cortex.parser import parse_surface, parse_surface_snapshots
from app.domain.observations import QualityFlag
from app.domain.requests import (
    FixedStrikeRequest,
    ListedMaturityMoneynessRequest,
    SlidingDeltaRequest,
    SlidingMoneynessRequest,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
COMMON = {
    "code": "US_QQQ",
    "start_date": date(2026, 8, 1),
    "end_date": date(2026, 8, 5),
}


def _fixture(path: str):
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))


def test_sliding_moneyness_surface_contract_keeps_all_coordinates():
    request = SlidingMoneynessRequest(
        **COMMON,
        low_strike=97.5,
        high_strike=100,
        low_maturity="1M",
        high_maturity="3M",
    )
    snapshots = parse_surface_snapshots(_fixture("schema/sliding_moneyness.json"), request)
    assert snapshots[0].maturities == ["1M", "3M"]
    assert snapshots[0].strikes == ["97.5", "100.0"]
    assert len(snapshots[0].points) == 4
    assert snapshots[0].points[-1].implied_vol == pytest.approx(0.225)


def test_sliding_delta_contract_normalizes_wire_axis_and_selects_exact_series():
    request = SlidingDeltaRequest(
        **COMMON,
        low_delta_strike="p25.0",
        high_delta_strike="p25.0",
        low_maturity="1M",
        high_maturity="1M",
    )
    payload = _fixture("schema/sliding_delta.json")
    snapshots = parse_surface_snapshots(payload, request)
    series = parse_surface(payload, request)
    assert snapshots[0].strikes == ["p25.0", "c25.0"]
    assert series[0].target_strike == "p25.0"
    assert series[0].returned_strike == "p25.0"
    assert series[0].implied_vol == pytest.approx(0.245)


def test_fixed_absolute_strike_contract_selects_expiry_and_strike():
    expiry = date(2026, 9, 18)
    request = FixedStrikeRequest(
        **COMMON,
        maturity_rule="fixed",
        low_fixed_strike=600,
        high_fixed_strike=600,
        low_fixed_maturity=expiry,
        high_fixed_maturity=expiry,
    )
    series = parse_surface(_fixture("schema/fixed_strike.json"), request)
    assert series[0].target_maturity == "2026-09-18"
    assert series[0].returned_strike == 600.0
    assert series[0].implied_vol == pytest.approx(0.230)


def test_listed_moneyness_contract_selects_expiry_and_relative_strike():
    expiry = date(2026, 9, 18)
    request = ListedMaturityMoneynessRequest(
        **COMMON,
        maturity_rule="listed",
        strike_rule="relative_to_spot_ref",
        low_strike=97.5,
        high_strike=97.5,
        low_fixed_maturity=expiry,
        high_fixed_maturity=expiry,
    )
    series = parse_surface(_fixture("schema/listed_moneyness.json"), request)
    assert series[0].target_maturity == "2026-09-18"
    assert series[0].returned_strike == 97.5
    assert series[0].implied_vol == pytest.approx(0.225)


def test_vector_layout_is_reshaped_by_documented_maturity_major_orientation():
    payload = _fixture("schema/sliding_moneyness.json")
    payload[0]["vector"] = [0.220, 0.210, 0.235, 0.225]
    payload[0]["matrix"] = []
    request = SlidingMoneynessRequest(
        **COMMON,
        layout="vector",
        low_strike=97.5,
        high_strike=100,
        low_maturity="1M",
        high_maturity="3M",
    )
    snapshots = parse_surface_snapshots(payload, request)
    assert [point.implied_vol for point in snapshots[0].points] == [
        0.220,
        0.210,
        0.235,
        0.225,
    ]


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        ("errors/negative_iv.json", QualityFlag.INVALID_IV_NEGATIVE),
        ("errors/zero_iv.json", QualityFlag.INVALID_IV_ZERO),
    ],
)
def test_error_fixtures_preserve_raw_and_exclude_invalid_iv(fixture_name, expected):
    request = SlidingMoneynessRequest(
        **COMMON,
        low_strike=100,
        high_strike=100,
        low_maturity="3M",
        high_maturity="3M",
    )
    point = parse_surface_snapshots(_fixture(fixture_name), request)[0].points[0]
    assert point.raw_implied_vol is not None
    assert point.implied_vol is None
    assert expected in point.quality_flags


def test_error_fixture_rejects_malformed_matrix():
    request = SlidingMoneynessRequest(
        **COMMON,
        low_strike=100,
        high_strike=100,
        low_maturity="1M",
        high_maturity="3M",
    )
    with pytest.raises(CortexError) as exc_info:
        parse_surface_snapshots(_fixture("errors/malformed_matrix.json"), request)
    assert exc_info.value.code == ErrorCode.SCHEMA_CHANGED


def test_empty_fixed_surface_is_missing_data_not_schema_change():
    expiry = date(2026, 9, 18)
    request = FixedStrikeRequest(
        **COMMON,
        maturity_rule="fixed",
        low_fixed_strike=600,
        high_fixed_strike=600,
        low_fixed_maturity=expiry,
        high_fixed_maturity=expiry,
    )
    payload = [
        {
            "date": "2026-08-03",
            "code": "US_QQQ",
            "maturityRule": "fixed",
            "strikeRule": "fixed",
            "volatilityConvention": "bsVol",
            "spot": 620.0,
            "maturities": [],
            "strikes": [],
            "forwardCurve": [],
            "zcCurve": [],
            "matrix": [],
        }
    ]
    snapshots = parse_surface_snapshots(payload, request)
    series = parse_surface(payload, request)
    assert snapshots[0].points == []
    assert QualityFlag.MISSING_IV in snapshots[0].quality_flags
    assert series[0].implied_vol is None
    assert QualityFlag.MATURITY_MISMATCH in series[0].quality_flags
    assert QualityFlag.STRIKE_MISMATCH in series[0].quality_flags


def test_empty_axis_with_iv_values_remains_schema_change():
    request = SlidingMoneynessRequest(
        **COMMON,
        low_strike=100,
        high_strike=100,
        low_maturity="3M",
        high_maturity="3M",
    )
    payload = _fixture("schema/sliding_moneyness.json")
    payload[0]["strikes"] = []
    payload[0]["matrix"] = [[0.22]]
    with pytest.raises(CortexError) as exc_info:
        parse_surface_snapshots(payload, request)
    assert exc_info.value.code == ErrorCode.SCHEMA_CHANGED


def test_error_fixture_rejects_conflicting_duplicate_date():
    request = SlidingMoneynessRequest(
        **COMMON,
        low_strike=100,
        high_strike=100,
        low_maturity="3M",
        high_maturity="3M",
    )
    with pytest.raises(CortexError) as exc_info:
        parse_surface_snapshots(_fixture("errors/duplicate_conflict.json"), request)
    assert exc_info.value.code == ErrorCode.AMBIGUOUS_DUPLICATE_DATE


def test_single_series_rejects_a_range_instead_of_choosing_first_coordinate():
    request = SlidingDeltaRequest(
        **COMMON,
        low_delta_strike="p25.0",
        high_delta_strike="c25.0",
        low_maturity="1M",
        high_maturity="3M",
    )
    with pytest.raises(CortexError) as exc_info:
        parse_surface(_fixture("schema/sliding_delta.json"), request)
    assert exc_info.value.code == ErrorCode.INVALID_REQUEST
