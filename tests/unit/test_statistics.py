"""Unit tests for spread statistics."""

import pytest

from app.analytics.statistics import (
    correlation,
    iv_divided_by_rv,
    iv_minus_rv,
    percentile_rank,
    zscore,
)


def test_iv_minus_rv():
    assert iv_minus_rv(0.25, 0.20) == pytest.approx(0.05)
    assert iv_minus_rv(None, 0.20) is None
    assert iv_minus_rv(0.25, None) is None


def test_iv_divided_by_rv():
    assert iv_divided_by_rv(0.25, 0.20) == pytest.approx(1.25)
    assert iv_divided_by_rv(0.25, 0.0) is None
    assert iv_divided_by_rv(0.25, None) is None


def test_percentile_rank():
    series = [0.01, 0.02, 0.03, 0.04, None, 0.05]
    assert percentile_rank(series, 0.03) == pytest.approx(60.0)  # 3 of 5 valid <=
    assert percentile_rank(series, 0.05) == pytest.approx(100.0)
    assert percentile_rank(series, None) is None
    assert percentile_rank([], 0.03) is None


def test_zscore():
    series = [1.0, 2.0, 3.0, 4.0, 5.0]
    # mean=3, stdev(ddof=1)=sqrt(2.5)
    assert zscore(series, 5.0) == pytest.approx(2.0 / (2.5**0.5))
    assert zscore(series, 3.0) == pytest.approx(0.0)
    assert zscore([2.0, 2.0, 2.0], 2.0) is None  # zero variance
    assert zscore(series, None) is None


def test_correlation_perfect():
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [2.0, 4.0, 6.0, 8.0]
    assert correlation(xs, ys) == pytest.approx(1.0)
    assert correlation(xs, [8.0, 6.0, 4.0, 2.0]) == pytest.approx(-1.0)


def test_correlation_null_pairs_dropped():
    xs = [1.0, None, 3.0, 4.0]
    ys = [2.0, 4.0, 6.0, 8.0]
    assert correlation(xs, ys) == pytest.approx(1.0)
    assert correlation([1.0, 2.0], [1.0, 2.0]) is None  # < 3 pairs
