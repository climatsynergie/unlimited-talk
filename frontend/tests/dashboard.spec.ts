import { test, expect } from "./qa-observer";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const empty = {
  calls: 0,
  answered: 0,
  no_answer: 0,
  busy: 0,
  failed: 0,
  cancelled: 0,
  in_progress: 0,
  manual: 0,
  automatic: 0,
  contacts: 0,
  bookings: 0,
  cancelled_bookings: 0,
  pauses: 0,
  stops: 0,
  starts: 0,
  automatic_pauses: 0,
  talk_seconds: 0,
  duration_known: 0,
  duration_missing: 0,
  answer_rate: null,
  bookings_per_100_calls: null,
  average_talk_seconds: null,
  first_call_at: null,
  last_call_at: null,
};
async function fixture(page: Page, role = "admin", incoming = false) {
  await page.clock.install({ time: new Date("2026-11-05T12:00:00Z") });
  const agents = Array.from({ length: 22 }, (_, i) => ({
    id: id(i + 20),
    display_name: `Agent ${String(i + 1).padStart(2, "0")}`,
    email: `agent${i + 1}@example.invalid`,
    role: "agent",
    is_active: i !== 21,
    metrics: {
      ...empty,
      ...(incoming
        ? { incoming_calls: 7, incoming_answered: 3, incoming_talk_seconds: 95 }
        : {}),
      calls: 24 + i,
      answered: 12,
      contacts: 18,
      bookings: 3,
      cancelled_bookings: 1,
      pauses: 2,
      stops: 1,
      manual: 4,
      automatic: 20 + i,
      talk_seconds: 720,
      duration_known: 12,
      answer_rate: 50,
      average_talk_seconds: 60,
    },
  }));
  if (incoming)
    agents.push({
      ...agents[0],
      id: id(99),
      display_name: "Admin réception",
      role: "admin",
      metrics: {
        ...agents[0].metrics,
        calls: 0,
        answered: 0,
        talk_seconds: 0,
        duration_known: 0,
      },
    });
  const requests: URL[] = [];
  const unexpected: string[] = [];
  let failedExport = false;
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    let body: unknown;
    if (url.pathname === "/api/auth/me")
      body = {
        user: {
          id: id(11),
          email: "supervisor@example.invalid",
          display_name: "Responsable",
          role,
          is_active: true,
        },
        mfa_enrollment_required: false,
      };
    else if (url.pathname === "/api/reporting/presence") body = { ok: true };
    else if (url.pathname === "/api/telephony/test/session")
      body = { enabled: false, active: null, max_duration_seconds: 1800 };
    else if (url.pathname === "/api/telephony/dialer/session")
      body = {
        enabled: false,
        dialer: { mode: "stopped", generation: 0, campaign_id: null },
      };
    else if (url.pathname === "/api/reporting/live")
      body = {
        generated_at: "2026-11-05T12:00:00Z",
        online: 2,
        in_calls: 1,
        connected: 1,
        paused: 1,
        items: agents.map((agent, i) => ({
          ...agent,
          status:
            i === 0 || agent.id === id(99)
              ? "connected"
              : i === 1
                ? "paused"
                : "offline",
          online: i < 2,
          last_seen_at: null,
          campaign_name: "Campagne Canada",
          call_id: i === 0 || agent.id === id(99) ? id(500) : null,
          destination: i === 0 ? "+14165550100" : null,
          consumed_at: null,
        })),
      };
    else if (url.pathname === "/api/reporting/export.xlsx") {
      if (failedExport)
        return route.fulfill({
          status: 503,
          json: { detail: "Export momentanément indisponible." },
        });
      return route.fulfill({
        contentType:
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        body: Buffer.from("PK-synthetic-download"),
      });
    } else if (url.pathname === "/api/reporting/report") {
      const start = url.searchParams.get("start")!,
        end = url.searchParams.get("end")!,
        zone = url.searchParams.get("timezone")!;
      if (start < "2026-08-01")
        return route.fulfill({
          status: 422,
          json: { detail: "Choisissez une période de trois mois maximum." },
        });
      const agent = url.searchParams.get("agent_id");
      const selected = agent
        ? agents.filter((row) => row.id === agent)
        : agents;
      const dates: string[] = [];
      for (
        let cursor = new Date(start + "T12:00:00Z");
        cursor.toISOString().slice(0, 10) <= end;
        cursor.setUTCDate(cursor.getUTCDate() + 1)
      )
        dates.push(cursor.toISOString().slice(0, 10));
      body = {
        period: { start, end, timezone: zone },
        generated_at: "2026-11-05T12:00:00Z",
        agents: selected,
        totals: selected[0]?.metrics || empty,
        daily: selected.flatMap((row) =>
          dates.map((date) => ({ agent_id: row.id, date, ...row.metrics })),
        ),
        hourly: agent
          ? dates.flatMap((date) =>
              Array.from(
                { length: date === "2026-11-01" ? 25 : 24 },
                (_, i) => ({
                  date,
                  label: `${String(i === 24 ? 1 : i).padStart(2, "0")}:00`,
                  utc_offset: i === 24 ? "-0500" : "-0400",
                  starts_at:
                    date +
                    "T" +
                    String(i % 24).padStart(2, "0") +
                    ":" +
                    (i === 24 ? "01" : "00") +
                    ":00Z",
                  ...empty,
                  ...(incoming
                    ? {
                        incoming_calls: 2,
                        incoming_answered: 1,
                        incoming_talk_seconds: 45,
                      }
                    : {}),
                  calls: i % 5,
                  answered: i % 2,
                }),
              ),
            )
          : [],
        definitions: {
          calls: "Préparations annulées exclues.",
          answered: "Une connexion peut inclure un répondeur.",
          talk: "Les durées absentes restent inconnues.",
          bookings: "RDV comptés à la création.",
          pauses: "Actions journalisées.",
          time: "Présence récente et temps travaillé sont distincts.",
        },
      };
    } else {
      unexpected.push(url.pathname);
      return route.fulfill({
        status: 404,
        json: { detail: "Unexpected isolated dashboard request" },
      });
    }
    return route.fulfill({ json: body });
  });
  return {
    agents,
    requests,
    unexpected,
    failExport: () => {
      failedExport = true;
    },
  };
}

test("dashboard réservé à l’admin : direct, 22 onglets et navigation clavier", async ({
  page,
}) => {
  const f = await fixture(page);
  await page.goto("/admin/tableau-de-bord");
  await expect(
    page.getByRole("heading", { name: "Tableau de bord.", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".report-agent")).toHaveCount(2);
  await page.getByLabel("Afficher aussi les agents hors ligne").check();
  await expect(page.locator(".report-agent")).toHaveCount(22);
  await expect(page.getByRole("tab")).toHaveCount(23);
  await expect(
    page.getByText("1–10 sur 22 agents", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Agents suivants", exact: true })
    .click();
  await expect(
    page.getByText("11–20 sur 22 agents", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Trier les agents", exact: true })
    .selectOption("calls");
  await expect(
    page.getByText("1–10 sur 22 agents", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Vue d’ensemble", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    page.getByRole("tab", { name: "Agent 01", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(
    page.getByRole("heading", { name: "Agent 01", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Appels heure par heure", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".report-hour-cells > div")).toHaveCount(24);
  await page.getByRole("tab", { name: "Vue d’ensemble", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Comparaison des agents", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Chargement de l’activité…")).toHaveCount(0);
  await expect
    .poll(
      () =>
        f.requests.filter((url) => url.pathname === "/api/reporting/presence")
          .length,
    )
    .toBeGreaterThan(0);
});

test("rapport par agent : 90 jours, pagination, heure doublée et export daté", async ({
  page,
}) => {
  const f = await fixture(page);
  await page.goto("/admin/tableau-de-bord");
  await page.getByRole("tab", { name: "Agent 01", exact: true }).click();
  await page
    .getByRole("button", { name: "90 derniers jours", exact: true })
    .click();
  await expect(
    page.getByText("1–14 sur 90 jours", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Jours suivants", exact: true })
    .click();
  await expect(
    page.getByText("15–28 sur 90 jours", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Journée", { exact: true }).fill("2026-11-01");
  await expect(page.locator(".report-hour-cells > div")).toHaveCount(25);
  const pending = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Exporter cet agent · Excel", exact: true })
    .click();
  const download = await pending;
  expect(download.suggestedFilename()).toContain(f.agents[0].id);
  expect(download.suggestedFilename()).toMatch(/2026-11-05\.xlsx$/);
  const request = f.requests
    .filter((url) => url.pathname === "/api/reporting/export.xlsx")
    .at(-1)!;
  expect(request.searchParams.get("agent_id")).toBe(f.agents[0].id);
  expect(request.searchParams.get("start")).toBe("2026-08-08");
  f.failExport();
  await page
    .getByRole("button", { name: "Exporter cet agent · Excel", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Export momentanément indisponible",
  );
});

test("dashboard : refus agent et périodes invalides, affichage mobile accessible", async ({
  page,
}) => {
  await fixture(page, "agent");
  await page.goto("/admin/tableau-de-bord");
  await expect(
    page
      .getByRole("navigation")
      .getByRole("link", { name: "Tableau de bord", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Tableau de bord.", exact: true }),
  ).toHaveCount(0);
});

test("dashboard administrateur : filtres explicites, lisibilité et accessibilité", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/admin/tableau-de-bord");
  await expect(
    page.getByRole("heading", { name: "Comparaison des agents", exact: true }),
  ).toBeVisible();
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  expect(
    results.violations.map((row) => ({
      id: row.id,
      nodes: row.nodes.map((node) => node.failureSummary),
    })),
  ).toEqual([]);
  await page.screenshot({
    path: "/tmp/ut-dashboard-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "/tmp/ut-dashboard-mobile.png",
    fullPage: true,
  });
  await page.getByLabel("Du", { exact: true }).fill("2026-01-01");
  await expect(
    page.getByRole("button", {
      name: "Exporter l’équipe · Excel",
      exact: true,
    }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Appliquer", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("trois mois maximum");
});

test("dashboard : entrants séparés des sortants dans les indicateurs, agents, jours et heures", async ({
  page,
}) => {
  const proof = await fixture(page, "admin", true);
  await page.goto("/admin/tableau-de-bord");
  const kpi = (title: string) =>
    page
      .locator(".report-kpi")
      .filter({
        has: page.locator("span").filter({ hasText: new RegExp(`^${title}$`) }),
      })
      .locator("strong");
  await expect(kpi("Appels entrants proposés")).toHaveText("7");
  await expect(kpi("Entrants décrochés")).toHaveText("3");
  await expect(kpi("Conversation entrante connue")).toHaveText(
    "0 h 01 min 35 s",
  );
  await expect(kpi("Appels lancés")).toHaveText("24");
  await expect(kpi("Décrochés clients")).toHaveText("12");
  await expect(kpi("Conversation connue")).toHaveText("0 h 12 min 00 s");
  await expect(
    page.locator(".report-agent").filter({ hasText: "Admin réception" }),
  ).toBeVisible();
  const comparison = page.getByRole("table");
  await expect(
    comparison.getByRole("columnheader", {
      name: "Entrants proposés",
      exact: true,
    }),
  ).toBeVisible();
  const agent = comparison.getByRole("row").filter({
    has: page.getByRole("button", { name: "Agent 01", exact: true }),
  });
  await expect(agent.getByRole("cell").nth(4)).toHaveText("7");
  await expect(agent.getByRole("cell").nth(5)).toHaveText("3");
  await expect(agent.getByRole("cell").nth(6)).toHaveText("0 h 01 min 35 s");
  await page.getByRole("tab", { name: "Agent 01", exact: true }).click();
  const journal = page.getByRole("table");
  await expect(
    journal.getByRole("columnheader", {
      name: "Conversation entrante connue",
      exact: true,
    }),
  ).toBeVisible();
  const day = journal.getByRole("row").nth(1);
  await expect(day.getByRole("cell").nth(3)).toHaveText("7");
  await expect(day.getByRole("cell").nth(4)).toHaveText("3");
  await expect(day.getByRole("cell").nth(5)).toHaveText("0 h 01 min 35 s");
  const hour = page.locator(".report-hour-cells > div").first();
  await expect(hour).toContainText("2 entrants proposés · 1 décrochés");
  await expect(hour).toContainText("0 h 00 min 45 s de conversation entrante");
  expect(proof.unexpected).toEqual([]);
});

test("dashboard : ancien rapport sans compteurs entrants conserve les sortants et affiche zéro", async ({
  page,
}) => {
  const proof = await fixture(page);
  await page.goto("/admin/tableau-de-bord");
  const card = page
    .locator(".report-kpi")
    .filter({ hasText: "Appels entrants proposés" });
  await expect(card.locator("strong")).toHaveText("0");
  await expect(
    page
      .locator(".report-kpi")
      .filter({ hasText: "Appels lancés" })
      .locator("strong"),
  ).toHaveText("24");
  expect(proof.unexpected).toEqual([]);
});
