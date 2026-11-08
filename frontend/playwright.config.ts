import { defineConfig } from "@playwright/test";
const evidenceMode =
  process.env.QA_EVIDENCE_MODE ??
  (process.env.QA_REAL_INCOMING_WORKFLOW === "1"
    ? "incoming"
    : process.env.QA_REAL_WORKFLOW === "1"
      ? "agent"
      : "main");
export default defineConfig({
  outputDir: `../qa-reports/evidence/browser-artifacts/${evidenceMode}`,
  testDir: "./tests",
  timeout: 120_000,
  workers: 1,
  retries: 0,
  reporter: [
    ["line"],
    ...(process.env.GITHUB_ACTIONS
      ? [["./scripts/browser-summary.ts"] as [string]]
      : []),
    [
      "json",
      {
        outputFile: `../qa-reports/evidence/browser-${evidenceMode}-results.json`,
      },
    ],
  ],
  maxFailures: 0,
  use: {
    baseURL: process.env.UI_TEST_URL ?? "https://localhost:18443",
    ignoreHTTPSErrors: true,
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
});
