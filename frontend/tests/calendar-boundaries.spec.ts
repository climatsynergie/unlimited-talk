import { test, expect } from "@playwright/test";

// Isolate display boundaries with synthetic read responses. Real booking,
// authorization and persistence flows run separately in identity.spec.ts.
test("une fin à minuit appartient seulement au jour précédent", async ({
  page,
}) => {
  const id = "00000000-0000-0000-0000-000000000001";
  let end = "2026-11-03T05:00:00Z"; // midnight Toronto, after DST fall-back
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    let body: unknown;
    if (url.pathname === "/api/auth/me") {
      body = {
        user: {
          id,
          email: "calendar@example.invalid",
          display_name: "Agent calendrier",
          role: "agent",
          is_active: true,
        },
        mfa_enrollment_required: false,
      };
    } else if (url.pathname === "/api/calendar/resolve") {
      body = {
        options: [
          {
            starts_at: url.searchParams.get("local_start") + "-05:00",
            utc_offset_minutes: -300,
            label: "UTC−05:00",
          },
        ],
      };
    } else if (url.pathname === "/api/calendar") {
      body = {
        name: "Unlimited Talks",
        viewer_id: id,
        has_more: false,
        items: [
          {
            id,
            campaign_id: id,
            contact_id: id,
            created_by: id,
            starts_at: "2026-11-03T04:30:00Z",
            ends_at: end,
            timezone: "America/Toronto",
            notes: "",
            status: "booked",
            version: 0,
            phone: "+14165550100",
            profile: { display_name: "Fin de journée" },
            campaign_name: "Campagne fictive",
            creator_name: "Agent calendrier",
          },
        ],
      };
    } else {
      await route.fulfill({
        status: 404,
        json: { detail: "Ressource introuvable." },
      });
      return;
    }
    await route.fulfill({ json: body });
  });
  await page.goto("/calendrier");
  await page
    .getByLabel("Semaine à partir du", { exact: true })
    .fill("2026-11-02");
  const monday = page.locator(".calendar-day").filter({
    has: page.getByRole("heading", {
      name: "lundi 2 novembre 2026",
      exact: true,
    }),
  });
  const tuesday = page.locator(".calendar-day").filter({
    has: page.getByRole("heading", {
      name: "mardi 3 novembre 2026",
      exact: true,
    }),
  });
  await expect(
    monday.getByRole("button").filter({ hasText: "Fin de journée" }),
  ).toHaveCount(1);
  await expect(tuesday.getByRole("button")).toHaveCount(0);
  end = "2026-11-03T05:30:00Z";
  await page.getByRole("button", { name: "Actualiser", exact: true }).click();
  await expect(
    tuesday.getByRole("button").filter({ hasText: "Fin de journée" }),
  ).toHaveCount(1);
});
