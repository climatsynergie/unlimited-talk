import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { silentWav as wav } from "./fixtures/audio";
import { disabledDialer } from "./fixtures/dialer-disabled";

const id = "00000000-0000-0000-0000-000000000001";
const recording = "RE" + "1".repeat(32);
const playback = `/api/telephony/recordings/${recording}/audio`;
test.beforeEach(async ({ page }) => {
  await disabledDialer(page);
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      json: {
        user: {
          id,
          email: "history@example.invalid",
          display_name: "Agent historique",
          role: "agent",
          is_active: true,
        },
        mfa_enrollment_required: false,
      },
    }),
  );
  await page.route("**/api/telephony/test/session", (route) =>
    route.fulfill({
      json: {
        enabled: false,
        destination: null,
        max_duration_seconds: 180,
        active: null,
      },
    }),
  );
});

test("archive en attente, actualisation et lecture privée sans préchargement", async ({
  page,
}) => {
  let archived = false;
  let reads = 0;
  await page.route("**/api/telephony/calls*", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id,
            created_at: "2026-10-31T15:00:00Z",
            actor_name: "Agent historique",
            destination: "+14165550101",
            state: "finished",
            outcome: "completed",
            recordings: [
              {
                sid: recording,
                state: archived ? "archived" : "pending_archive",
                duration: 1,
                playback_path: archived ? playback : null,
              },
            ],
          },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.route("**" + playback, async (route) => {
    reads += 1;
    await route.fulfill({
      contentType: "audio/wav",
      body: wav(),
      headers: { "Cache-Control": "no-store" },
    });
  });
  await page.goto("/poste-appel");
  await expect(
    page.getByText("Enregistrement : sauvegarde privée en cours.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.locator("audio")).toHaveCount(0);
  archived = true;
  await page
    .getByRole("button", { name: "Actualiser les appels", exact: true })
    .click();
  const player = page.locator("audio");
  await expect(player).toHaveAttribute("src", playback);
  await expect(player).toHaveAttribute("preload", "none");
  expect(reads).toBe(0);
  await player.evaluate((node: HTMLAudioElement) => {
    node.loop = true;
    return node.play();
  });
  await expect.poll(() => reads).toBeGreaterThan(0);
  const report = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(report.violations.map((item) => item.id)).toEqual([]);
  const oldPlayer = await player.elementHandle();
  expect(
    await oldPlayer!.evaluate((node: HTMLAudioElement) => node.paused),
  ).toBe(false);
  await page.getByRole("link", { name: "Mon compte", exact: true }).click();
  await expect
    .poll(() =>
      oldPlayer!.evaluate(
        (node: HTMLAudioElement) =>
          node.paused && node.getAttribute("src") === null,
      ),
    )
    .toBe(true);
});

test("échec de lecture et reprise explicite avec la même archive", async ({
  page,
}) => {
  let reads = 0;
  await page.route("**/api/telephony/calls*", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id,
            created_at: "2026-10-31T15:00:00Z",
            actor_name: "Agent historique",
            destination: "+14165550101",
            state: "finished",
            outcome: "completed",
            recordings: [
              {
                sid: recording,
                state: "archived",
                duration: 1,
                playback_path: playback,
              },
            ],
          },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.route("**" + playback, async (route) => {
    reads += 1;
    if (reads === 1)
      await route.fulfill({
        status: 503,
        json: { detail: "Stockage indisponible" },
      });
    else await route.fulfill({ contentType: "audio/wav", body: wav() });
  });
  await page.goto("/poste-appel");
  await expect(page.locator("audio")).toBeVisible();
  await page
    .getByRole("button", { name: "Actualiser les appels", exact: true })
    .click();
  await page
    .locator("audio")
    .evaluate((node: HTMLAudioElement) => node.play().catch(() => {}));
  await expect(page.getByRole("alert")).toContainText(
    "La lecture est temporairement indisponible",
  );
  await page
    .getByRole("button", { name: "Réessayer la lecture", exact: true })
    .click();
  await expect.poll(() => reads).toBeGreaterThan(1);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("plus de 200 appels : pages bornées, recherche et accès à la conversation", async ({
  page,
}) => {
  const queries: URLSearchParams[] = [];
  const items = Array.from({ length: 205 }, (_, index) => ({
    id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
    created_at: new Date(
      Date.UTC(2026, 10, 1, 16, 0) - index * 60000,
    ).toISOString(),
    destination: `+1416555${1000 + index}`,
    contact_name: `Contact ${index + 1}`,
    campaign_name: "Test 1",
    actor_name: "Agent historique",
    caller_number: "+12369040720",
    state: "finished",
    outcome: "completed",
    recordings:
      index % 2 === 0
        ? [
            {
              sid: recording,
              state: "archived",
              duration: 60,
              playback_path: playback,
            },
          ]
        : [],
  }));
  await page.route("**/api/telephony/calls*", (route) => {
    const q = new URL(route.request().url()).searchParams;
    queries.push(q);
    let result = items.filter(
      (item) =>
        (!q.get("q") ||
          item.contact_name
            .toLowerCase()
            .includes(q.get("q")!.toLowerCase())) &&
        (!q.get("recordings_only") || item.recordings.length),
    );
    const after = q.get("before_id");
    if (after)
      result = result.slice(result.findIndex((item) => item.id === after) + 1);
    const current = result.slice(0, 20);
    return route.fulfill({
      json: {
        items: current,
        next_cursor:
          result.length > 20
            ? { id: current[19].id, created_at: current[19].created_at }
            : null,
      },
    });
  });
  await page.goto("/poste-appel");
  await expect(
    page.getByRole("heading", { name: "1. Tester le microphone", exact: true }),
  ).not.toBeVisible();
  await expect(page.locator(".call-inbox-row")).toHaveCount(20);
  await page
    .getByRole("button", { name: "Charger les appels précédents", exact: true })
    .click();
  await expect(
    page.getByText("Page 2 · 20 appels", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".call-inbox-row")).toHaveCount(20);
  await expect(page.locator(".call-conversation h3")).toHaveText("Contact 21");
  await page
    .getByRole("button", { name: "Appels plus récents", exact: true })
    .click();
  await expect(
    page.getByText("Page 1 · 20 appels", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Rechercher dans les appels", { exact: true })
    .fill("Contact 201");
  await page
    .getByRole("button", { name: "Rechercher les appels", exact: true })
    .click();
  await expect(page.locator(".call-inbox-row")).toHaveCount(1);
  await expect(page.locator(".call-conversation h3")).toHaveText("Contact 201");
  await expect(page.locator(".call-details")).toContainText("Agent historique");
  await expect(page.locator(".call-details")).toContainText("Test 1");
  expect(queries.at(-1)?.get("q")).toBe("Contact 201");
  await expect(page.locator("audio")).toHaveCount(1);
  await expect(page.locator("audio")).toHaveAttribute("preload", "none");
  await page
    .getByRole("button", { name: "Réinitialiser", exact: true })
    .click();
  await expect(page.locator(".call-inbox-row")).toHaveCount(20);
  await page.getByLabel("Avec enregistrement", { exact: true }).check();
  await page
    .getByRole("button", { name: "Rechercher les appels", exact: true })
    .click();
  await expect.poll(() => queries.at(-1)?.get("recordings_only")).toBe("true");
  await expect(page.locator(".call-inbox-row")).toHaveCount(20);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
