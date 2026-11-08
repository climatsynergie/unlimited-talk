import { test, expect } from "./qa-observer";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const unknownRequests = new WeakMap<Page, string[]>();
test.afterEach(({ page }) => {
  expect(unknownRequests.get(page) ?? []).toEqual([]);
});

const uuid = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const campaign = {
  id: uuid(1),
  name: "Équipe Canada",
  description: "Prospection au Canada",
  timezone: "America/Toronto",
  version: 0,
  is_active: true,
  contact_count: 0,
};
async function fixture(page: Page, dense = false) {
  const unexpected: string[] = [];
  unknownRequests.set(page, unexpected);
  const agents = Array.from({ length: 65 }, (_, i) => ({
    id: uuid(i + 10),
    display_name: `Agent ${String(i + 1).padStart(2, "0")}`,
    email: `agent${i + 1}@example.invalid`,
    is_active: i !== 59,
    assigned: i < 2,
  }));
  const appointments = Array.from({ length: dense ? 120 : 12 }, (_, i) => {
    const start =
      Date.parse("2026-11-02T14:00:00Z") +
      (dense ? (i % 40) * 30 : Math.floor(i / 3) * 24 * 60 + (i % 3) * 90) *
        60000;
    return {
      id: uuid(i + 200),
      campaign_id: campaign.id,
      contact_id: uuid(i + 400),
      created_by: agents[i % 3].id,
      creator_name: agents[i % 3].display_name,
      starts_at: new Date(start).toISOString(),
      ends_at: new Date(start + 30 * 60000).toISOString(),
      timezone: "America/Toronto",
      notes: "Préparer la rencontre",
      status: ["booked", "completed", "no_show", "cancelled"][i % 4],
      version: 0,
      phone: "+14165550100",
      profile: { display_name: `Client ${String(i + 1).padStart(3, "0")}` },
      campaign_name: campaign.name,
    };
  });
  const proof = {
    batches: [] as {
      request_id: string;
      changes: {
        user_id: string;
        is_active: boolean;
        expected_assigned: boolean;
      }[];
    }[],
    queries: [] as URLSearchParams[],
    fail: false,
  };
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url()),
      path = url.pathname;
    let body: unknown;
    if (path === "/api/auth/me")
      body = {
        user: {
          id: uuid(2),
          display_name: "Administration",
          email: "admin@example.invalid",
          role: "admin",
          is_active: true,
        },
        mfa_enrollment_required: false,
      };
    else if (
      path === "/api/reporting/presence" &&
      route.request().method() === "POST"
    )
      body = { ok: true };
    else if (path === "/api/telephony/test/session")
      body = { enabled: true, active: null, max_duration_seconds: 600 };
    else if (path === "/api/telephony/dialer/session")
      body = {
        enabled: false,
        dialer: { mode: "stopped", generation: 0, campaign_id: null },
      };
    else if (path === "/api/campaigns")
      body = { items: [campaign], has_more: false };
    else if (path.endsWith("/board"))
      body = {
        campaign,
        stages: [
          {
            id: uuid(3),
            name: "À appeler",
            kind: "new",
            color: "violet",
            position: 0,
            total: 0,
            items: [],
          },
        ],
      };
    else if (path.endsWith("/agents") && route.request().method() === "PUT") {
      const batch = route.request().postDataJSON();
      proof.batches.push(batch);
      if (proof.fail) {
        proof.fail = false;
        return route.fulfill({
          status: 503,
          json: { detail: "Réessayez l’enregistrement." },
        });
      }
      batch.changes.forEach(
        (change: { user_id: string; is_active: boolean }) => {
          agents.find((a) => a.id === change.user_id)!.assigned =
            change.is_active;
        },
      );
      body = { assigned_count: agents.filter((a) => a.assigned).length };
    } else if (path.endsWith("/agents")) {
      const q = url.searchParams.get("q")?.toLowerCase() || "";
      const rows = agents.filter(
        (a) =>
          `${a.display_name} ${a.email}`.toLowerCase().includes(q) &&
          (!url.searchParams.has("assigned") ||
            a.assigned === (url.searchParams.get("assigned") === "true")) &&
          (!url.searchParams.has("active_only") || a.is_active),
      );
      const offset = Number(url.searchParams.get("offset"));
      body = {
        items: rows.slice(offset, offset + 50),
        has_more: rows.length > offset + 50,
        total: rows.length,
        assigned_count: agents.filter((a) => a.assigned).length,
      };
    } else if (path === "/api/calendar") {
      proof.queries.push(url.searchParams);
      const rows = appointments.filter(
        (a) =>
          Date.parse(a.starts_at) < Date.parse(url.searchParams.get("end")!) &&
          Date.parse(a.ends_at) > Date.parse(url.searchParams.get("start")!) &&
          (!url.searchParams.has("creator") ||
            a.created_by === url.searchParams.get("creator")) &&
          (!url.searchParams.has("status") ||
            a.status === url.searchParams.get("status")) &&
          (url.searchParams.get("exclude_cancelled") !== "true" ||
            a.status !== "cancelled"),
      );
      const offset = Number(url.searchParams.get("offset"));
      body = {
        items: rows.slice(offset, offset + 100),
        has_more: rows.length > offset + 100,
        viewer_id: uuid(2),
        name: "Unlimited Talks",
      };
    } else if (path.startsWith("/api/calendar/"))
      body = {
        appointment: appointments.find((a) => path.endsWith(a.id)),
        can_edit: true,
        events: [],
        has_more: false,
      };
    else {
      unexpected.push(`${route.request().method()} ${path}`);
      return route.fulfill({
        status: 404,
        json: { detail: "Ressource indisponible dans ce test." },
      });
    }
    await route.fulfill({ json: body });
  });
  return proof;
}
async function team(page: Page) {
  await page.goto("/campagnes");
  await page
    .getByRole("button")
    .filter({ hasText: campaign.name })
    .first()
    .click();
  await page
    .getByRole("button", { name: "Réglages de la campagne", exact: true })
    .click();
  await expect(page.locator(".team-agent")).toHaveCount(50);
}
async function accessible(page: Page) {
  const report = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    report.violations.map((v) => v.id),
    JSON.stringify(
      report.violations.flatMap((v) =>
        v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })),
      ),
    ),
  ).toEqual([]);
}

test("équipe : recherche, sélection entre pages et enregistrement atomique", async ({
  page,
}) => {
  const proof = await fixture(page);
  await team(page);
  await page.screenshot({
    path: "/tmp/ut-campaign-team-desktop.png",
    fullPage: true,
  });
  await accessible(page);
  await page
    .getByLabel("Rechercher un agent", { exact: true })
    .fill("Agent 04");
  await expect(page.locator(".team-agent")).toHaveCount(1);
  await page.locator(".team-agent").getByRole("checkbox").check();
  await page.getByLabel("Rechercher un agent", { exact: true }).fill("");
  await expect(page.locator(".team-agent")).toHaveCount(50);
  await page
    .getByRole("button", { name: "Agents suivants", exact: true })
    .click();
  await expect(page.locator(".team-agent")).toHaveCount(15);
  await page
    .locator(".team-agent")
    .filter({ hasText: "Agent 65" })
    .getByRole("checkbox")
    .check();
  await expect(
    page.getByText("2 modifications en attente", { exact: true }),
  ).toBeVisible();
  proof.fail = true;
  await page
    .getByRole("button", { name: "Enregistrer l’équipe", exact: true })
    .click();
  await expect(
    page.getByText("Réessayez l’enregistrement.", { exact: false }),
  ).toBeVisible();
  await expect(
    page
      .locator(".team-agent")
      .filter({ hasText: "Agent 65" })
      .getByRole("checkbox"),
  ).toBeChecked();
  await page
    .getByRole("button", { name: "Enregistrer l’équipe", exact: true })
    .click();
  await expect(
    page.getByText("L’équipe de la campagne a été enregistrée.", {
      exact: true,
    }),
  ).toBeVisible();
  expect(proof.batches[1]).toEqual(proof.batches[0]);
  expect(proof.batches[1].changes).toHaveLength(2);
  await expect(page.locator(".team-agent")).toHaveCount(50);
  await page.setViewportSize({ width: 390, height: 844 });
  await accessible(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("équipe : sélectionner une page respecte les agents désactivés", async ({
  page,
}) => {
  const proof = await fixture(page);
  await team(page);
  await page
    .getByRole("button", { name: "Agents suivants", exact: true })
    .click();
  await expect(page.locator(".team-agent")).toHaveCount(15);
  await page
    .getByRole("button", { name: "Sélectionner la page", exact: true })
    .click();
  await expect(
    page.getByText("14 modifications en attente", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".team-agent")
      .filter({ hasText: "Agent 60" })
      .getByRole("checkbox"),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Enregistrer l’équipe", exact: true })
    .click();
  await expect(
    page.getByText("L’équipe de la campagne a été enregistrée.", {
      exact: true,
    }),
  ).toBeVisible();
  expect(proof.batches[0].changes).toHaveLength(14);
});

test("calendrier : vues visuelles, couleurs, fuseaux et fiche du rendez-vous", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await fixture(page);
  await page.goto("/calendrier");
  await page.getByLabel("Aller à la date", { exact: true }).fill("2026-11-02");
  await page
    .getByRole("combobox", { name: "Statut", exact: true })
    .selectOption("all");
  await expect(
    page.getByText("12 rendez-vous dans cette période", { exact: true }),
  ).toBeVisible();
  for (const status of ["booked", "completed", "no_show", "cancelled"])
    await expect(
      page.locator(`.appointment-card.status-${status}`).first(),
    ).toBeVisible();
  await page.screenshot({
    path: "/tmp/ut-calendar-desktop.png",
    fullPage: true,
  });
  await accessible(page);
  await page
    .getByRole("combobox", { name: "Fuseau horaire", exact: true })
    .selectOption("America/Vancouver");
  await expect(
    page
      .locator(".appointment-card")
      .filter({ hasText: "Client 001" })
      .locator(".calendar-event-time"),
  ).toHaveText(/07:00/); // Vancouver stays UTC−07 after March 2026: https://news.gov.bc.ca/releases/2026AG0013-000209
  await page.getByRole("button", { name: "Mois", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Mois", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Agenda", exact: true }).click();
  await page
    .locator(".appointment-card")
    .filter({ hasText: "Client 001" })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Préparer la rencontre");
  await page
    .getByRole("button", { name: "Fermer la fenêtre", exact: true })
    .click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Jour", exact: true }).click();
  const scrolling = page
    .locator(".calendar-canvas [data-calendar-scroll]")
    .first();
  await expect(scrolling).toHaveAttribute("tabindex", "0");
  await scrolling.focus();
  await expect(scrolling).toBeFocused();
  await page.screenshot({
    path: "/tmp/ut-calendar-mobile.png",
    fullPage: true,
  });
  await accessible(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("calendrier : charge toutes les pages et respecte la semaine du changement d’heure", async ({
  page,
}) => {
  const proof = await fixture(page, true);
  await page.goto("/calendrier");
  await page.getByLabel("Aller à la date", { exact: true }).fill("2026-11-02");
  await page
    .getByRole("combobox", { name: "Statut", exact: true })
    .selectOption("all");
  await expect(
    page.getByText("120 rendez-vous dans cette période", { exact: true }),
  ).toBeVisible();
  expect(proof.queries.some((q) => q.get("offset") === "100")).toBe(true);
  await page.getByLabel("Aller à la date", { exact: true }).fill("2026-10-26");
  await expect
    .poll(() => {
      const q = proof.queries.at(-1)!;
      return (
        (Date.parse(q.get("end")!) - Date.parse(q.get("start")!)) / 3600000
      );
    })
    .toBe(169);
});
