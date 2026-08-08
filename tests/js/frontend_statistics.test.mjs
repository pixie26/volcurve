import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import test from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "../..");
const require = createRequire(import.meta.url);
const core = require(path.join(repoRoot, "app/web/compare-core.js"));

const {
  summarizeSeries,
  applyOperator,
  deriveSeries,
  coordinateSignature,
  boardSignature,
  stableStringify,
} = core;

function isoDate(day) {
  const date = new Date(Date.UTC(2026, 0, 1));
  date.setUTCDate(date.getUTCDate() + day);
  return date.toISOString().slice(0, 10);
}

function deterministicSeries() {
  const points = [];
  for (let index = 0; index < 90; index += 1) {
    const value = 18.5
      + index * 0.037
      + Math.sin(index / 4.3) * 1.9
      + Math.cos(index / 9.1) * 0.8
      + ((index % 7) - 3) * 0.041;
    points.push({ date: isoDate(index), value });
  }
  points[37] = { ...points[37], value: null };
  [points[11], points[12]] = [points[12], points[11]];
  return points;
}

function pythonReference(points) {
  const output = execFileSync(
    process.env.PYTHON || "python",
    [path.join(here, "stats_reference.py")],
    { cwd: repoRoot, input: JSON.stringify(points), encoding: "utf8" },
  );
  return JSON.parse(output);
}

function assertEquivalent(actual, expected, prefix = "stats") {
  assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort());
  for (const key of Object.keys(expected)) {
    const left = actual[key];
    const right = expected[key];
    const label = `${prefix}.${key}`;
    if (typeof right === "number") {
      assert.equal(typeof left, "number", `${label} must be numeric`);
      const tolerance = 1e-10 * Math.max(1, Math.abs(right));
      assert.ok(Math.abs(left - right) <= tolerance, `${label}: ${left} != ${right}`);
    } else {
      assert.equal(left, right, label);
    }
  }
}

test("Node executes the production compare-core implementation directly", () => {
  assert.equal(typeof summarizeSeries, "function");
  assert.equal(typeof deriveSeries, "function");
  assert.equal(typeof coordinateSignature, "function");
});

test("summarizeSeries matches an independent Python oracle across every returned statistic", () => {
  const points = deterministicSeries();
  const actual = summarizeSeries(structuredClone(points));
  const expected = pythonReference(points);
  assert.ok(actual);
  assert.ok(expected);
  assertEquivalent(actual, expected);
});

test("summarizeSeries is null-safe, finite-only, date-sorted and does not zero-fill gaps", () => {
  const stats = summarizeSeries([
    { date: "2026-02-04", value: Number.POSITIVE_INFINITY },
    { date: "2026-02-03", value: 4 },
    { date: "2026-02-01", value: 2 },
    { date: "2026-02-02", value: null },
  ]);
  assert.equal(stats.count, 2);
  assert.equal(stats.latestDate, "2026-02-03");
  assert.equal(stats.latest, 4);
  assert.equal(stats.change1, 2);
  assert.equal(stats.change5, null);
});

test("constant and small samples expose metrics only where mathematically valid", () => {
  const constant = summarizeSeries([
    { date: "2026-01-01", value: 3 },
    { date: "2026-01-02", value: 3 },
    { date: "2026-01-03", value: 3 },
    { date: "2026-01-04", value: 3 },
  ]);
  assert.equal(constant.stdDev, 0);
  assert.equal(constant.zScore, null);
  assert.equal(constant.skewness, null);
  assert.equal(constant.kurtosis, null);
  assert.equal(constant.autocorrelation, null);

  const single = summarizeSeries([{ date: "2026-01-01", value: 8 }]);
  assert.equal(single.count, 1);
  assert.equal(single.stdDev, 0);
  assert.equal(single.change1, null);
  assert.equal(single.largestGain, null);
  assert.equal(single.largestDrop, null);

  const two = summarizeSeries([{ date: "2026-01-01", value: 1 }, { date: "2026-01-02", value: 2 }]);
  assert.equal(two.skewness, null);
  assert.equal(two.kurtosis, null);
  assert.equal(two.autocorrelation, null);
});

test("1D / 5D / 20D changes use usable observation lags", () => {
  const points = Array.from({ length: 25 }, (_, index) => ({ date: isoDate(index), value: index }));
  points[20].value = null;
  const stats = summarizeSeries(points);
  assert.equal(stats.change1, 1);
  assert.equal(stats.change5, 6); // five usable observations back crosses the missing source point
  assert.equal(stats.change20, 21); // missing observation is excluded rather than zero-filled
});

test("most recent repeated extreme defines extrema dates and sessions-since", () => {
  const stats = summarizeSeries([
    { date: "2026-01-01", value: 1 },
    { date: "2026-01-02", value: 5 },
    { date: "2026-01-03", value: 1 },
    { date: "2026-01-04", value: 5 },
    { date: "2026-01-05", value: 2 },
  ]);
  assert.equal(stats.maxDate, "2026-01-04");
  assert.equal(stats.sessionsSinceMax, 1);
  assert.equal(stats.minDate, "2026-01-03");
  assert.equal(stats.sessionsSinceMin, 2);
});

test("derived arithmetic preserves missing values and refuses divide-by-zero", () => {
  assert.equal(applyOperator("add", 2, 3), 5);
  assert.equal(applyOperator("subtract", 2, 3), -1);
  assert.equal(applyOperator("multiply", -2, 3), -6);
  assert.equal(applyOperator("divide", 9, 3), 3);
  assert.equal(applyOperator("divide", 9, 0), null);
  assert.equal(applyOperator("add", null, 3), null);
  assert.equal(applyOperator("add", 3, null), null);
  assert.equal(applyOperator("bogus", 3, 4), null);
});

test("derived series uses only common dates and never fills missing/divide-zero points", () => {
  const left = [
    { date: "2026-01-01", value: 10 },
    { date: "2026-01-02", value: null },
    { date: "2026-01-03", value: 9 },
  ];
  const right = [
    { date: "2026-01-01", value: 2 },
    { date: "2026-01-03", value: 0 },
    { date: "2026-01-04", value: 4 },
  ];
  assert.deepEqual(deriveSeries(left, right, "divide"), [
    { date: "2026-01-01", value: 5 },
    { date: "2026-01-03", value: null },
  ]);
});

test("signatures are stable and ignore display-only coordinate fields", () => {
  const a = { type: "implied_vol", config: { instrumentCode: "US_QQQ", moneyness: "100", alias: "A", chartLane: "1" } };
  const b = { type: "implied_vol", config: { chartLane: "4", alias: "B", moneyness: "100", instrumentCode: "US_QQQ" } };
  assert.equal(coordinateSignature(a), coordinateSignature(b));
  assert.equal(stableStringify({ b: 2, a: 1 }), stableStringify({ a: 1, b: 2 }));
});

test("board signature ignores concrete dates only for sliding boards", () => {
  const base = { dateMode: "sliding", slidingWindow: "1Y", startDate: "2025-01-01", endDate: "2026-01-01", chartCount: 1, items: [] };
  assert.equal(boardSignature(base), boardSignature({ ...base, startDate: "2025-02-01", endDate: "2026-02-01" }));
  const fixed = { ...base, dateMode: "fixed" };
  assert.notEqual(boardSignature(fixed), boardSignature({ ...fixed, endDate: "2026-02-01" }));
});
