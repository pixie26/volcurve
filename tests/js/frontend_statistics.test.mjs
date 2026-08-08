import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "../..");
const sourcePath = path.join(repoRoot, "app/web/compare-builder.js");
const source = fs.readFileSync(sourcePath, "utf8");

function extractFunction(name) {
  const marker = `  function ${name}(`;
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, `compare-builder.js must contain ${name}`);
  const next = source.indexOf("\n  function ", start + marker.length);
  const end = next === -1 ? source.length : next;
  return source.slice(start, end).trim();
}

const statsFunctions = [
  "summarizeSeries",
  "average",
  "quantile",
  "changeOverSessions",
  "sampleSkewness",
  "sampleKurtosis",
  "autocorrelationAtLag",
];
const operatorFunctions = ["applyOperator", "numericValue"];

const context = vm.createContext({ console });
vm.runInContext(
  [...statsFunctions, ...operatorFunctions].map(extractFunction).join("\n\n"),
  context,
  { filename: "compare-builder-extracted.js" },
);

const summarizeSeries = context.summarizeSeries;
const applyOperator = context.applyOperator;

function isoDate(day) {
  const date = new Date(Date.UTC(2026, 0, 1));
  date.setUTCDate(date.getUTCDate() + day);
  return date.toISOString().slice(0, 10);
}

function deterministicSeries() {
  const points = [];
  for (let index = 0; index < 90; index += 1) {
    // Deliberately nonlinear and asymmetric so skew/kurtosis/autocorrelation tests are real.
    const value = 18.5
      + index * 0.037
      + Math.sin(index / 4.3) * 1.9
      + Math.cos(index / 9.1) * 0.8
      + ((index % 7) - 3) * 0.041;
    points.push({ date: isoDate(index), value });
  }
  points[37] = { ...points[37], value: null }; // one missing observation
  // Input order is not guaranteed by callers; summarizeSeries promises date ordering.
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

function assertEquivalent(actual, expected, pathPrefix = "stats") {
  assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort());
  for (const key of Object.keys(expected)) {
    const left = actual[key];
    const right = expected[key];
    const label = `${pathPrefix}.${key}`;
    if (typeof right === "number") {
      assert.equal(typeof left, "number", `${label} must be numeric`);
      const tolerance = 1e-10 * Math.max(1, Math.abs(right));
      assert.ok(Math.abs(left - right) <= tolerance, `${label}: ${left} != ${right}`);
    } else {
      assert.equal(left, right, label);
    }
  }
}

test("summarizeSeries matches an independent Python oracle across every returned statistic", () => {
  const points = deterministicSeries();
  const actual = summarizeSeries(structuredClone(points));
  const expected = pythonReference(points);
  assert.ok(actual);
  assert.ok(expected);
  assertEquivalent(actual, expected);
});

test("summarizeSeries is null-safe, date-sorted and does not zero-fill gaps", () => {
  const stats = summarizeSeries([
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

test("constant and small samples return defined metrics only where mathematically valid", () => {
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
});

test("derived arithmetic preserves missing values and refuses divide-by-zero", () => {
  assert.equal(applyOperator("add", 2, 3), 5);
  assert.equal(applyOperator("subtract", 2, 3), -1);
  assert.equal(applyOperator("multiply", -2, 3), -6);
  assert.equal(applyOperator("divide", 9, 3), 3);
  assert.equal(applyOperator("divide", 9, 0), null);
  assert.equal(applyOperator("add", null, 3), null);
  assert.equal(applyOperator("add", 3, null), null);
});

test("extreme-distance tie policy is explicitly tracked", { todo: "use the most recent occurrence for max/min ties" }, () => {
  // Current production code uses indexOf(max/min), i.e. the first occurrence.  Keeping
  // this TODO visible prevents the known semantics issue from disappearing into prose.
});
