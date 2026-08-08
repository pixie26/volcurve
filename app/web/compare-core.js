"use strict";

// Pure helpers shared by the Time Series runtime. Keep this file free of DOM/state access so
// it can become the direct import seam for the rest of compare-builder's pure logic.
function compareStableStringify(value) {
  if (Array.isArray(value)) return `[${value.map(compareStableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${compareStableStringify(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

// What identifies an indicator as a market series: display alias and chart placement do not.
// PR #7 accidentally removed this helper while duplicateWarning still called it. Browser
// execution tests caught the resulting bulk-edit ReferenceError.
function coordinateSignature(item) {
  const config = { ...(item?.config || {}) };
  delete config.alias;
  delete config.chartLane;
  return compareStableStringify({ type: item?.type, config });
}
