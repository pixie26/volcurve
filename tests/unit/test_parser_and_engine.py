"""Contract tests: parser coordinate resolution + engine end-to-end on fixture."""

import json
from datetime import date
from pathlib import Path

import pytest

from app.analytics.engine import run_compare
from app.analytics.realized_vol import calculate_trailing_realized_vol
from app.clients.cortex.errors import CortexError, ErrorCode
from app.clients.cortex.parser import parse_surface
from app.domain.observations import QualityFlag
from app.domain.requests import ImpliedVolRequest
from app.domain.responses import CompareResponse, build_quality_contract

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "implied_vol_surface.json"


def _request() -> ImpliedVolRequest:
    return ImpliedVolRequest(
        code="US_QQQ",
        start_date=date(2020, 1, 2),
        end_date=date(2020, 1, 20),
        low_strike=100.0,
        high_strike=100.0,
        low_maturity="3M",
        high_maturity="3M",
        strike_rule="relative_to_spot_ref",
    )


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parser_coordinate_resolution():
    obs = parse_surface(_payload(), _request())
    assert len(obs) == 9
    first = obs[0]
    assert first.returned_maturity == "3M"
    assert first.returned_strike == pytest.approx(100.0)
    # IV equals the raw matrix value at the resolved coordinates, exactly
    raw_first = _payload()[0]
    mi = raw_first["maturities"].index("3M")
    si = raw_first["strikes"].index("100.0")
    assert first.implied_vol == raw_first["matrix"][mi][si]
    assert first.forward == raw_first["forwardCurve"][mi]


def test_parser_rejects_matrix_dimension_mismatch():
    payload = _payload()
    payload[0]["matrix"] = [[0.2, 0.21]]  # 1x2 but axes are 1x1
    with pytest.raises(CortexError) as exc_info:
        parse_surface(payload, _request())
    assert exc_info.value.code == ErrorCode.SCHEMA_CHANGED


def test_parser_flags_missing_iv():
    payload = _payload()
    payload[0]["matrix"] = [[None]]
    obs = parse_surface(payload, _request())
    assert QualityFlag.MISSING_IV in obs[0].quality_flags
    assert obs[0].implied_vol is None


@pytest.mark.parametrize(
    ("raw_value", "expected_flag"),
    [
        (0.0, QualityFlag.INVALID_IV_ZERO),
        (-0.01, QualityFlag.INVALID_IV_NEGATIVE),
    ],
)
def test_parser_preserves_but_excludes_non_positive_iv(raw_value, expected_flag):
    payload = _payload()
    payload[0]["matrix"] = [[raw_value]]
    obs = parse_surface(payload, _request())
    assert obs[0].raw_implied_vol == raw_value
    assert obs[0].implied_vol is None
    assert expected_flag in obs[0].quality_flags


def test_parser_keeps_extreme_positive_iv_with_warning():
    payload = _payload()
    payload[0]["matrix"] = [[5.1]]
    obs = parse_surface(payload, _request())
    assert obs[0].raw_implied_vol == 5.1
    assert obs[0].implied_vol == 5.1
    assert QualityFlag.SUSPICIOUS_IV_EXTREME in obs[0].quality_flags


def test_parser_removes_identical_duplicate_and_sorts_source():
    payload = list(reversed(_payload()))
    payload.append(dict(payload[-1]))
    obs = parse_surface(payload, _request())
    assert len(obs) == 9
    assert [item.date for item in obs] == sorted(item.date for item in obs)
    assert any(QualityFlag.DUPLICATE_IDENTICAL_REMOVED in item.quality_flags for item in obs)
    assert all(QualityFlag.SOURCE_ORDER_CORRECTED in item.quality_flags for item in obs)


def test_parser_rejects_conflicting_duplicate_date():
    payload = _payload()
    conflict = dict(payload[0])
    conflict["spot"] = conflict["spot"] + 1
    payload.append(conflict)
    with pytest.raises(CortexError) as exc_info:
        parse_surface(payload, _request())
    assert exc_info.value.code == ErrorCode.AMBIGUOUS_DUPLICATE_DATE


def test_parser_flags_strike_mismatch():
    payload = _payload()
    payload[0]["strikes"] = ["99.5"]
    obs = parse_surface(payload, _request())
    assert QualityFlag.STRIKE_MISMATCH in obs[0].quality_flags


def test_engine_display_range_and_warmup():
    obs = parse_surface(_payload(), _request())
    result = run_compare(
        obs,
        display_from=date(2020, 1, 2),
        display_to=date(2020, 1, 20),
        window_sessions=3,
        alignment="trailing",
    )
    assert len(result.series) == 9
    # with only 9 observations and window=3, first 3 display dates lack RV
    assert result.series[0].realized_vol is None
    assert result.series[3].realized_vol is not None
    # summary fields present
    assert result.summary["latestIv"] is not None
    assert result.summary["observationCount"] == 6


def test_engine_rv_matches_direct_calculation():
    obs = parse_surface(_payload(), _request())
    result = run_compare(
        obs,
        display_from=date(2020, 1, 2),
        display_to=date(2020, 1, 20),
        window_sessions=3,
        alignment="trailing",
    )
    direct = calculate_trailing_realized_vol([o.spot for o in obs], 3)
    for entry, expected in zip(result.series, direct, strict=True):
        if expected is None:
            assert entry.realized_vol is None
        else:
            assert entry.realized_vol == pytest.approx(expected, abs=1e-15)


def test_engine_forward_alignment_tail_null():
    obs = parse_surface(_payload(), _request())
    result = run_compare(
        obs,
        display_from=date(2020, 1, 2),
        display_to=date(2020, 1, 20),
        window_sessions=3,
        alignment="forward",
    )
    assert result.series[-1].realized_vol is None
    assert result.series[-3].realized_vol is None
    assert result.series[0].realized_vol is not None
    assert result.summary["latestMarketDate"] == result.series[-1].date
    assert result.summary["latestIvDate"] == result.series[-1].date
    assert result.summary["latestComparableDate"] == result.series[-4].date
    assert result.summary["latestComparableRv"] is not None


def test_invalid_iv_is_excluded_and_exposed_in_response_quality_contract():
    payload = _payload()
    affected_date = date.fromisoformat(payload[-1]["date"])
    payload[-1]["matrix"] = [[-0.01]]
    obs = parse_surface(payload, _request())
    result = run_compare(
        obs,
        display_from=date(2020, 1, 2),
        display_to=date(2020, 1, 20),
        window_sessions=3,
        alignment="trailing",
    )
    quality, activity = build_quality_contract(result.series)

    assert result.series[-1].raw_implied_vol == -0.01
    assert result.series[-1].implied_vol is None
    assert result.summary["latestIvDate"] == result.series[-2].date
    assert result.summary["observationCount"] == 5
    assert quality.invalidIvCount == 1
    assert quality.invalidIvDateFrom == affected_date
    assert quality.invalidIvDateTo == affected_date
    assert quality.flagCounts[QualityFlag.INVALID_IV_NEGATIVE.value] == 1
    assert activity[0].code == "INVALID_POINTS_EXCLUDED"
    assert activity[0].affectedObservations == 1
    schema = CompareResponse.model_json_schema()["properties"]
    assert "dataQuality" in schema
    assert "activity" in schema
