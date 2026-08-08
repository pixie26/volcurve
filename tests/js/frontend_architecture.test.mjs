import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "../..");
const webRoot = path.join(repoRoot, "app/web");
const moduleNames = [
  "compare-core.js",
  "compare-workspace.js",
  "compare-request.js",
  "compare-render.js",
  "compare-builder.js",
];

function read(name) {
  return fs.readFileSync(path.join(webRoot, name), "utf8");
}

test("all split Time Series browser modules are valid JavaScript", () => {
  for (const name of moduleNames) {
    execFileSync(process.execPath, ["--check", path.join(webRoot, name)], {
      cwd: repoRoot,
      stdio: "pipe",
    });
  }
});

test("compare-builder stays a thin controller rather than regrowing the monolith", () => {
  const builder = read("compare-builder.js");
  assert.ok(builder.length < 12_000, `controller is unexpectedly large: ${builder.length} bytes`);
  assert.doesNotMatch(builder, /function\s+summarizeSeries\s*\(/);
  assert.doesNotMatch(builder, /function\s+applyOperator\s*\(/);
  assert.doesNotMatch(builder, /localStorage\.(?:getItem|setItem)/);
  for (const name of ["compare-workspace", "compare-request", "compare-render"]) {
    assert.match(builder, new RegExp(name));
  }
});

test("pure numerical implementation exists only in compare-core", () => {
  const core = read("compare-core.js");
  assert.match(core, /function\s+summarizeSeries\s*\(/);
  assert.match(core, /function\s+deriveSeries\s*\(/);
  assert.match(core, /function\s+coordinateSignature\s*\(/);
  assert.match(core, /function\s+boardSignature\s*\(/);

  for (const name of ["compare-workspace.js", "compare-request.js", "compare-render.js", "compare-builder.js"]) {
    const source = read(name);
    assert.doesNotMatch(source, /function\s+summarizeSeries\s*\(/, `${name} duplicated summarizeSeries`);
    assert.doesNotMatch(source, /function\s+applyOperator\s*\(/, `${name} duplicated applyOperator`);
    assert.doesNotMatch(source, /function\s+coordinateSignature\s*\(/, `${name} duplicated coordinateSignature`);
    assert.doesNotMatch(source, /function\s+boardSignature\s*\(/, `${name} duplicated boardSignature`);
  }
});

test("split boundaries remain explicit", () => {
  const workspace = read("compare-workspace.js");
  const request = read("compare-request.js");
  const render = read("compare-render.js");

  assert.match(workspace, /localStorage\.setItem/);
  assert.doesNotMatch(workspace, /Plotly\.react/);
  assert.match(request, /apiFetch\(/);
  assert.match(request, /deriveSeries\(/);
  assert.doesNotMatch(request, /Plotly\.react/);
  assert.match(render, /Plotly\.react/);
  assert.match(render, /summarizeSeries\(/);
});
