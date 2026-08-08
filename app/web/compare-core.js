"use strict";

// Canonical pure logic for the Time Series workspace.
//
// This file deliberately has no DOM, fetch, localStorage or mutable UI-state access.  The
// browser loads it directly and the Node tests require the exact same production file.
// Keep the CommonJS export: package.json is intentionally not `type: module`, so this is a
// dependency-free seam that works in both runtimes.
(function exposeCompareCore(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else Object.assign(root, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function buildCompareCore() {
  function stableStringify(value) {
    if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
    if (value && typeof value === "object") {
      return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
    }
    return JSON.stringify(value);
  }

  // Backward-compatible name used by the first extraction seam.
  const compareStableStringify = stableStringify;

  // Display-only fields do not identify a market coordinate.
  function coordinateSignature(item) {
    const config = { ...(item?.config || {}) };
    delete config.alias;
    delete config.chartLane;
    return stableStringify({ type: item?.type, config });
  }

  // A sliding board's concrete dates are derived from "today" and therefore are not part
  // of its saved semantic identity.  Everything else that changes what the board means is.
  function boardSignature(snapshot) {
    const sliding = snapshot.dateMode === "sliding";
    return stableStringify({
      dateMode: snapshot.dateMode,
      slidingWindow: sliding ? snapshot.slidingWindow : null,
      startDate: sliding ? null : snapshot.startDate,
      endDate: sliding ? null : snapshot.endDate,
      chartCount: snapshot.chartCount,
      chartOrder: snapshot.chartOrder || [],
      chartNames: snapshot.chartNames || [],
      columnWidths: snapshot.columnWidths || {},
      items: (snapshot.items || []).map((item) => ({
        id: item.id,
        type: item.type,
        active: item.active,
        config: item.config,
      })),
    });
  }

  function numericValue(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function applyOperator(operator, left, right) {
    if (left === null || right === null || left === undefined || right === undefined) return null;
    if (operator === "add") return left + right;
    if (operator === "subtract") return left - right;
    if (operator === "multiply") return left * right;
    if (operator !== "divide" || right === 0) return null;
    const value = left / right;
    return Number.isFinite(value) ? value : null;
  }

  // Browser-derived series are defined only on common observation dates. Missing values
  // stay missing and divide-by-zero stays null; there is no interpolation or fill.
  function deriveSeries(leftPoints, rightPoints, operator) {
    if (!Array.isArray(leftPoints) || !Array.isArray(rightPoints)) return [];
    const rightByDate = new Map(rightPoints.map((point) => [point.date, point.value]));
    return leftPoints
      .filter((point) => rightByDate.has(point.date))
      .map((point) => ({
        date: point.date,
        value: applyOperator(operator, point.value, rightByDate.get(point.date)),
      }));
  }

  function average(values) {
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  }

  function quantile(sorted, fraction) {
    if (!sorted.length) return null;
    if (sorted.length === 1) return sorted[0];
    const position = (sorted.length - 1) * fraction;
    const lower = Math.floor(position);
    const upper = Math.ceil(position);
    if (lower === upper) return sorted[lower];
    return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
  }

  // Lags count usable observations. A missing source point is excluded before this stage,
  // so it is never silently treated as zero or as an extra trading session.
  function changeOverSessions(values, lag) {
    return values.length > lag ? values.at(-1) - values.at(-1 - lag) : null;
  }

  function sampleSkewness(values, mean, stdDev) {
    const count = values.length;
    if (count < 3 || !(stdDev > 0)) return null;
    const sum = values.reduce((total, value) => total + ((value - mean) / stdDev) ** 3, 0);
    return (count / ((count - 1) * (count - 2))) * sum;
  }

  function sampleKurtosis(values, mean, stdDev) {
    const count = values.length;
    if (count < 4 || !(stdDev > 0)) return null;
    const sum = values.reduce((total, value) => total + ((value - mean) / stdDev) ** 4, 0);
    return ((count * (count + 1)) / ((count - 1) * (count - 2) * (count - 3))) * sum
      - (3 * (count - 1) ** 2) / ((count - 2) * (count - 3));
  }

  function autocorrelationAtLag(values, mean, lag) {
    if (values.length < lag + 2) return null;
    let numerator = 0;
    let denominator = 0;
    for (let index = 0; index < values.length; index += 1) {
      const centered = values[index] - mean;
      denominator += centered * centered;
      if (index >= lag) numerator += centered * (values[index - lag] - mean);
    }
    return denominator > 0 ? numerator / denominator : null;
  }

  function summarizeSeries(points) {
    if (!points) return null;
    const usable = points
      .filter((point) => point.value !== null && point.value !== undefined)
      .map((point) => ({ date: point.date, value: numericValue(point.value) }))
      .filter((point) => point.value !== null)
      .sort((left, right) => (left.date < right.date ? -1 : left.date > right.date ? 1 : 0));
    if (!usable.length) return null;

    const values = usable.map((point) => point.value);
    const sorted = [...values].sort((left, right) => left - right);
    const count = values.length;
    const mean = average(values);
    const variance = count > 1
      ? values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (count - 1)
      : 0;
    const stdDev = Math.sqrt(variance);
    const latest = usable.at(-1);
    const min = sorted[0];
    const max = sorted.at(-1);
    // "Distance from the extreme" is useful only if it points to the most recent touch.
    const maxIndex = values.lastIndexOf(max);
    const minIndex = values.lastIndexOf(min);
    const steps = values.slice(1).map((value, index) => value - values[index]);
    const mean20 = average(values.slice(-20));

    return {
      count,
      latest: latest.value,
      latestDate: latest.date,
      min,
      max,
      range: max - min,
      minDate: usable[minIndex].date,
      maxDate: usable[maxIndex].date,
      sessionsSinceMax: count - 1 - maxIndex,
      sessionsSinceMin: count - 1 - minIndex,
      mean,
      mean20,
      mean60: average(values.slice(-60)),
      vsMean20: mean20 === null ? null : latest.value - mean20,
      median: quantile(sorted, 0.5),
      p25: quantile(sorted, 0.25),
      p75: quantile(sorted, 0.75),
      stdDev,
      iqr: quantile(sorted, 0.75) - quantile(sorted, 0.25),
      percentile: (sorted.filter((value) => value <= latest.value).length / count) * 100,
      zScore: stdDev > 0 ? (latest.value - mean) / stdDev : null,
      change1: changeOverSessions(values, 1),
      change5: changeOverSessions(values, 5),
      change20: changeOverSessions(values, 20),
      change60: changeOverSessions(values, 60),
      largestGain: steps.length ? steps.reduce((best, step) => Math.max(best, step), -Infinity) : null,
      largestDrop: steps.length ? steps.reduce((best, step) => Math.min(best, step), Infinity) : null,
      meanAbsChange: steps.length ? average(steps.map(Math.abs)) : null,
      positiveShare: (values.filter((value) => value > 0).length / count) * 100,
      skewness: sampleSkewness(values, mean, stdDev),
      kurtosis: sampleKurtosis(values, mean, stdDev),
      autocorrelation: autocorrelationAtLag(values, mean, 1),
      autocorrelation5: autocorrelationAtLag(values, mean, 5),
      autocorrelation20: autocorrelationAtLag(values, mean, 20),
    };
  }

  return {
    stableStringify,
    compareStableStringify,
    coordinateSignature,
    boardSignature,
    numericValue,
    applyOperator,
    deriveSeries,
    average,
    quantile,
    changeOverSessions,
    sampleSkewness,
    sampleKurtosis,
    autocorrelationAtLag,
    summarizeSeries,
  };
});
