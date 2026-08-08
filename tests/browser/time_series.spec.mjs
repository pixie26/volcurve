import { expect, test } from "@playwright/test";

function syntheticCompareResponse(requestBody, sequence = 1) {
  const vol = requestBody.volatilityRequest;
  const dates = ["2026-08-04", "2026-08-05", "2026-08-06"];
  const series = dates.map((date, index) => ({
    date,
    spot: 100 + index,
    forward: 101 + index,
    rawImpliedVol: 20 + index,
    impliedVol: 20 + index,
    realizedVol: null,
    ivMinusRv: null,
    ivDividedByRv: null,
    qualityFlags: [],
  }));
  return {
    requestId: `browser-${sequence}`,
    series,
    summary: {
      latestMarketDate: dates.at(-1),
      latestIvDate: dates.at(-1),
      latestIv: 22,
      latestComparableDate: null,
      latestComparableIv: null,
      latestComparableRv: null,
      latestComparableSpread: null,
      latestRv: null,
      latestSpread: null,
      spreadPercentile: null,
      spreadZScore: null,
      correlation: null,
      observationCount: series.length,
    },
    methodology: {
      maturity: vol.low_maturity || vol.low_fixed_maturity || "3M",
      strikeConvention: vol.strike_rule || "relative_to_forward",
      strike: vol.low_strike ?? vol.low_fixed_strike ?? 100,
      ivLabel: "browser fixture IV",
      rvLabel: "RV 2 trading days (trailing)",
      rvWindowSessions: 2,
      rvAlignment: "trailing",
      rvFormula: "fixture",
      annualization: 252,
      volUnits: "percent",
      spotNote: "fixture spot",
      corporateActionAdjustment: "none",
    },
    source: {
      provider: "bnpp",
      apiVersion: "1.60.0",
      instrumentCode: vol.code,
      retrievedAt: "2026-08-08T12:00:00Z",
      cacheStatus: "miss",
      requestId: `browser-${sequence}`,
      requestIds: [`browser-${sequence}`],
      warmupFrom: vol.start_date,
      isStale: false,
      oldestRetrievedAt: null,
      newestRetrievedAt: null,
      refreshAttemptedAt: null,
      refreshRequestId: null,
      staleReason: null,
    },
    dataQuality: {
      status: "OK",
      observationCount: series.length,
      usableIvCount: series.length,
      invalidIvCount: 0,
      invalidIvDateFrom: null,
      invalidIvDateTo: null,
      suspiciousIvCount: 0,
      flagCounts: {},
      warningBanner: null,
      analyticsExclusionPolicy: "fixture",
    },
    activity: [],
    disclosures: [],
    requestAudit: {
      userRequestBody: requestBody,
      upstreamRequests: [],
    },
    issues: [],
  };
}

async function openWorkspace(page) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  await page.goto("/");
  await expect(page.locator("#indicatorBuilder")).toBeVisible();
  await expect(page.locator("#apiVersion")).not.toHaveText("API —");
  return errors;
}

test("Time Series boots without browser runtime errors", async ({ page }) => {
  const errors = await openWorkspace(page);
  await expect(page.locator("#addIndicatorButton")).toBeEnabled();
  await expect(page.locator("#timeseriesTitle")).toHaveText("空白时序图");
  expect(errors).toEqual([]);
});

test("adding an indicator executes the real builder, chart and statistics paths", async ({ page }) => {
  const requests = [];
  await page.route("**/api/v1/vol/compare", async (route) => {
    const body = route.request().postDataJSON();
    requests.push(body);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(syntheticCompareResponse(body, requests.length)),
    });
  });
  const errors = await openWorkspace(page);

  await page.locator("#addIndicatorButton").click();

  await expect(page.locator("#indicatorCount")).toHaveText("1");
  await expect(page.locator("#indicatorStatsCount")).toHaveText("1 series");
  await expect(page.locator("#timeseriesTitle")).toContainText("1 instruments · 1 indicators");
  await expect(page.locator("#savedIndicators")).not.toContainText("尚未添加指标");
  await expect(page.locator("#indicatorChart-1 .plotly")).toBeAttached();
  expect(requests).toHaveLength(1);
  expect(requests[0].volatilityRequest.maturity_rule).toBe("sliding");
  expect(requests[0].volatilityRequest.strike_rule).toBe("relative_to_forward");
  expect(errors).toEqual([]);
});

test("bulk Fixed maturity persists exact state and the next refresh serializes it exactly", async ({ page }) => {
  const requests = [];
  await page.route("**/api/v1/vol/compare", async (route) => {
    const body = route.request().postDataJSON();
    requests.push(body);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(syntheticCompareResponse(body, requests.length)),
    });
  });
  const errors = await openWorkspace(page);
  await page.locator("#addIndicatorButton").click();
  await expect(page.locator("#indicatorCount")).toHaveText("1");
  await expect(page.locator("#indicatorStatsCount")).toHaveText("1 series");
  await expect.poll(() => requests.length).toBe(1);

  await page.locator("#bulkModeButton").click();
  await page.locator("#savedIndicators [data-bulk-select]").first().check();
  await page.locator("#bulkMaturityTab").click();
  await page.locator("#bulkMaturityMode").selectOption("fixed");
  await page.locator("#bulkFixedMaturity").fill("2026-12-30");
  await expect(page.locator("#bulkMaturityMoveButton")).toBeEnabled();
  await page.locator("#bulkMaturityMoveButton").click();

  const persisted = await page.evaluate(() => JSON.parse(localStorage.getItem("volcurve.compare.workspace.v1")));
  expect(persisted.items[0].config.maturityMode).toBe("fixed");
  expect(persisted.items[0].config.expiry).toBe("2026-12-30");

  // A refresh is the stable public action that promises re-fetch.  It must serialize the
  // bulk-edited coordinate exactly; no nearest listed expiry substitution is allowed.
  await page.locator("#refreshIndicatorsButton").click();
  await expect.poll(() => requests.length).toBeGreaterThanOrEqual(2);
  const latest = requests.at(-1).volatilityRequest;
  expect(latest.maturity_rule).toBe("fixed");
  expect(latest.low_fixed_maturity).toBe("2026-12-30");
  expect(latest.high_fixed_maturity).toBe("2026-12-30");
  expect(errors).toEqual([]);
});
