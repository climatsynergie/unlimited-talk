import type { Page } from "@playwright/test";

// Synthetic sessions keep phone reads in their own fixture, without a real cookie.
export async function disabledDialer(page: Page) {
  await page.route("**/api/telephony/call-agents", (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.route("**/api/telephony/dialer/campaigns", (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.route("**/api/telephony/dialer/session", (route) =>
    route.fulfill({
      json: {
        enabled: false,
        dialer: {
          mode: "stopped",
          generation: 0,
          campaign_id: null,
          browser_id: null,
        },
      },
    }),
  );
}
