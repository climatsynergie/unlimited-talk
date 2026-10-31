import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  workers: 1,
  retries: 0,
  reporter: process.env.GITHUB_ACTIONS
    ? [["line"], ["./scripts/browser-summary.ts"]]
    : "line",
  maxFailures: 1,
  use: {
    baseURL: process.env.UI_TEST_URL ?? "https://localhost:18443",
    ignoreHTTPSErrors: true,
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
    viewport: { width: 1440, height: 1000 },
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
