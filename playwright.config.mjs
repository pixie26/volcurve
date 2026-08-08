import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:8000",
    browserName: "chromium",
    headless: true,
  },
  webServer: {
    command: "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1",
    url: "http://127.0.0.1:8000/health/live",
    timeout: 120_000,
    reuseExistingServer: false,
    env: {
      ...process.env,
      CORTEX_MODE: "fixture",
    },
  },
});
