"""Unit tests for realized-vol calculations (Gate 3)."""

import math
from statistics import stdev

import pytest

from app.analytics.alignment import warmup_start
from app.analytics.realized_vol import (
    calculate_forward_realized_vol,
    calculate_log_returns,
    calculate_trailing_realized_vol,
    resolve_window,
)

SPOTS = [100.0, 101.0, 99.0, 102.0, 103.0, 98.0, 100.5, 102.5]


def test_log_returns_values():
    rets = calculate_log_returns(SPOTS)
    assert rets[0] is None
    assert rets[1] == pytest.approx(math.log(101.0 / 100.0))
    assert rets[3] == pytest.approx(math.log(102.0 / 99.0))
    assert len(rets) == len(SPOTS)


def test_log_returns_missing_spot_not_zero_filled():
    rets = calculate_log_returns([100.0, None, 102.0, 0.0, 101.0])
    assert rets[1] is None  # needs S_1
    assert rets[2] is None  # needs S_1 (missing)
    assert rets[3] is None  # S_2 ok but... S_3 = 0 -> non-positive
    assert rets[4] is None  # S_3 non-positive


def test_trailing_rv_matches_independent_stdev():
    window = 3
    rvs = calculate_trailing_realized_vol(SPOTS, window, annualization=252)
    rets = calculate_log_returns(SPOTS)
    # first `window` sessions must be null (insufficient history)
    assert all(v is None for v in rvs[:window])
    for i in range(window, len(SPOTS)):
        expected = stdev(rets[i - window + 1 : i + 1]) * math.sqrt(252)
        assert rvs[i] == pytest.approx(expected, abs=1e-15)


def test_trailing_rv_uses_sample_std_ddof1():
    # ddof=0 would differ by sqrt((n-1)/n); ensure sample std (Excel STDEV.S)
    window = 4
    rvs = calculate_trailing_realized_vol(SPOTS, window)
    rets = calculate_log_returns(SPOTS)
    i = len(SPOTS) - 1
    sample = stdev(rets[i - window + 1 : i + 1])
    n = window
    population = sample * math.sqrt((n - 1) / n)
    assert rvs[i] == pytest.approx(sample * math.sqrt(252))
    assert rvs[i] != pytest.approx(population * math.sqrt(252), abs=1e-6)


def test_forward_rv_tail_null():
    window = 3
    rvs = calculate_forward_realized_vol(SPOTS, window, annualization=252)
    # last `window` sessions unrealized -> null
    assert all(v is None for v in rvs[len(SPOTS) - window :])
    rets = calculate_log_returns(SPOTS)
    expected_0 = stdev(rets[1 : 1 + window]) * math.sqrt(252)
    assert rvs[0] == pytest.approx(expected_0, abs=1e-15)


def test_rv_null_propagates_from_missing_spot():
    spots = [100.0, 101.0, None, 102.0, 103.0, 104.0]
    rvs = calculate_trailing_realized_vol(spots, 2)
    rets = calculate_log_returns(spots)
    # r_2 and r_3 are both broken by the missing spot at index 2
    assert rets[2] is None and rets[3] is None
    assert rvs[2] is None  # window (r_1, r_2)
    assert rvs[3] is None  # window (r_2, r_3)
    assert rvs[4] is None  # window (r_3, r_4)
    assert rvs[5] is not None
    assert rvs[5] == pytest.approx(stdev(rets[4:6]) * math.sqrt(252))


def test_resolve_window_presets_and_bounds():
    assert resolve_window("3M") == 63
    assert resolve_window("1w") == 5
    assert resolve_window(63) == 63
    with pytest.raises(ValueError):
        resolve_window("9M")
    with pytest.raises(ValueError):
        resolve_window(1)


def test_warmup_start_covers_trading_window():
    from datetime import date

    start = warmup_start(date(2025, 8, 6), 63)
    buffer_days = (date(2025, 8, 6) - start).days
    # ceil(63*7/5) + 10 = 89 + 10 = 99 calendar days back
    assert buffer_days == 99
