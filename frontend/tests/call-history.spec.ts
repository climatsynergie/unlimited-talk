import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { silentWav as wav } from "./fixtures/audio";

const id = "00000000-0000-0000-0000-000000000001";
const recording = "RE" + "1".repeat(32);
const playback = `/api/telephony/recordings/${recording}/audio`;
test.beforeEach(async ({ page }) => {
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
