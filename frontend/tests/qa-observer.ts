import { test as base, expect } from "@playwright/test";

// Observations are evidence, not automatically unexplained defects: negative
// tests intentionally exercise HTTP errors and cancelled navigation requests.
export const test = base.extend<{ qaObservation: void }>({
  qaObservation: [
    async ({ page }, use, testInfo) => {
      const events: {
        kind: string;
        method?: string;
        path?: string;
        detail: string;
      }[] = [];
      const path = (url: string) => {
        try {
          return new URL(url).pathname;
        } catch {
          return "[invalid-url]";
        }
      };
      page.on("pageerror", (error) =>
        events.push({ kind: "exception", detail: error.message }),
      );
      page.on("console", (message) => {
        if (message.type() === "error")
          events.push({ kind: "console-error", detail: message.text() });
      });
      page.on("requestfailed", (request) =>
        events.push({
          kind: "request-failed",
          method: request.method(),
          path: path(request.url()),
          detail: request.failure()?.errorText ?? "unknown",
        }),
      );
      page.on("response", (response) => {
        if (response.status() >= 400)
          events.push({
            kind: "http-error",
            method: response.request().method(),
            path: path(response.url()),
            detail: String(response.status()),
          });
      });
      await use();
      await testInfo.attach("qa-browser-observations", {
        body: JSON.stringify(events, null, 2),
        contentType: "application/json",
      });
      const { appendFileSync, mkdirSync } = await import("node:fs");
      const { resolve, dirname } = await import("node:path");
      const target =
        process.env.QA_BROWSER_OBSERVATIONS ??
        resolve(
          process.cwd(),
          "../qa-reports/evidence/browser-observations.jsonl",
        );
      mkdirSync(dirname(target), { recursive: true });
      appendFileSync(
        target,
        JSON.stringify({
          title: testInfo.title,
          status: testInfo.status,
          events,
        }) + "\n",
      );
      expect(
        events.filter((event) => event.kind === "exception"),
        "Uncaught browser exceptions",
      ).toEqual([]);
    },
    { auto: true },
  ],
});
export { expect };
