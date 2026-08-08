"""Independent Python oracle for the browser statistics tests.

This file deliberately does not import app.analytics.statistics.  It mirrors the
published formulas from first principles so the Node tests can catch accidental
changes in the JavaScript implementation rather than comparing one copy of the
same code with another.
"""

from __future__ import annotations

import json
import math
import sys
from statistics import fmean


def quantile(sorted_values: list[float], fraction: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (
        position - lower
    )


def average(values: list[float]) -> float | None:
    return fmean(values) if values else None


def change(values: list[float], lag: int) -> float | None:
    return values[-1] - values[-1 - lag] if len(values) > lag else None


def sample_skewness(values: list[float], mean: float, std_dev: float) -> float | None:
    count = len(values)
    if count < 3 or not std_dev > 0:
        return None
    total = sum(((value - mean) / std_dev) ** 3 for value in values)
    return (count / ((count - 1) * (count - 2))) * total


def sample_kurtosis(values: list[float], mean: float, std_dev: float) -> float | None:
    count = len(values)
    if count < 4 or not std_dev > 0:
        return None
    total = sum(((value - mean) / std_dev) ** 4 for value in values)
    return (
        (count * (count + 1)) / ((count - 1) * (count - 2) * (count - 3)) * total
        - (3 * (count - 1) ** 2) / ((count - 2) * (count - 3))
    )


def autocorrelation(values: list[float], mean: float, lag: int) -> float | None:
    if len(values) < lag + 2:
        return None
    denominator = sum((value - mean) ** 2 for value in values)
    if denominator <= 0:
        return None
    numerator = sum(
        (values[index] - mean) * (values[index - lag] - mean)
        for index in range(lag, len(values))
    )
    return numerator / denominator


def summarize(points: list[dict[str, object]]) -> dict[str, object] | None:
    usable = sorted(
        (
            {"date": str(point["date"]), "value": float(point["value"])}
            for point in points
            if point.get("value") is not None
        ),
        key=lambda point: point["date"],
    )
    if not usable:
        return None

    values = [float(point["value"]) for point in usable]
    sorted_values = sorted(values)
    count = len(values)
    mean = fmean(values)
    variance = (
        sum((value - mean) ** 2 for value in values) / (count - 1) if count > 1 else 0.0
    )
    std_dev = math.sqrt(variance)
    minimum = sorted_values[0]
    maximum = sorted_values[-1]
    min_index = values.index(minimum)
    max_index = values.index(maximum)
    steps = [values[index] - values[index - 1] for index in range(1, count)]
    mean20 = average(values[-20:])

    return {
        "count": count,
        "latest": values[-1],
        "latestDate": usable[-1]["date"],
        "min": minimum,
        "max": maximum,
        "range": maximum - minimum,
        "minDate": usable[min_index]["date"],
        "maxDate": usable[max_index]["date"],
        "sessionsSinceMax": count - 1 - max_index,
        "sessionsSinceMin": count - 1 - min_index,
        "mean": mean,
        "mean20": mean20,
        "mean60": average(values[-60:]),
        "vsMean20": None if mean20 is None else values[-1] - mean20,
        "median": quantile(sorted_values, 0.5),
        "p25": quantile(sorted_values, 0.25),
        "p75": quantile(sorted_values, 0.75),
        "stdDev": std_dev,
        "iqr": quantile(sorted_values, 0.75) - quantile(sorted_values, 0.25),
        "percentile": 100.0
        * sum(value <= values[-1] for value in sorted_values)
        / count,
        "zScore": (values[-1] - mean) / std_dev if std_dev > 0 else None,
        "change1": change(values, 1),
        "change5": change(values, 5),
        "change20": change(values, 20),
        "change60": change(values, 60),
        "largestGain": max(steps) if steps else None,
        "largestDrop": min(steps) if steps else None,
        "meanAbsChange": average([abs(step) for step in steps]),
        "positiveShare": 100.0 * sum(value > 0 for value in values) / count,
        "skewness": sample_skewness(values, mean, std_dev),
        "kurtosis": sample_kurtosis(values, mean, std_dev),
        "autocorrelation": autocorrelation(values, mean, 1),
        "autocorrelation5": autocorrelation(values, mean, 5),
        "autocorrelation20": autocorrelation(values, mean, 20),
    }


def main() -> int:
    points = json.load(sys.stdin)
    json.dump(summarize(points), sys.stdout, allow_nan=False, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
