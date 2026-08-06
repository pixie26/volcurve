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
    for entry, expected in zip(result.series, direct):
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
