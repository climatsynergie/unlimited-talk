import { test, expect } from "./qa-observer";
import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { disabledDialer } from "./fixtures/dialer-disabled";

const uuid = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const number = "+15145550123";
async function setup(
  page: Page,
  options: {
    hidden?: boolean;
    unknown?: boolean;
    dnc?: boolean;
    ni?: boolean;
    fail?: boolean;
  } = {},
) {
  const unexpected: string[] = [];
  const reservations: Record<string, string>[] = [];
  const rows = new Map<string, Record<string, unknown>>();
  const queue = {
    id: uuid(50),
    name: "Réception Canada",
    phone: "+14165550102",
    timezone: "America/Toronto",
    hours: [],
    max_wait_seconds: 60,
    offer_seconds: 20,
    is_active: true,
    version: 1,
    agents: [],
    routing_active: true,
  };
  const profile = {
    display_name: "Nina Gros",
    email: "nina@example.invalid",
    address: "123 rue du Test",
    city: "Montréal",
    postal_code: "H2X 1Y4",
  };
  const followup = {
    id: uuid(51),
    queue_id: queue.id,
    caller_number: options.hidden ? null : number,
    profile: options.hidden || options.unknown ? null : profile,
    owner_id: null,
    owner_name: null,
    stage: "pending",
    version: 1,
    callback_at: null,
    callback_timezone: null,
    do_not_contact: options.dnc ?? false,
    non_interested: options.ni ?? false,
    call_count: 1,
  };
  let failure = options.fail ?? false;
  await page.route("**/api/**", (route) => {
    unexpected.push(
      `${route.request().method()} ${new URL(route.request().url()).pathname}`,
    );
    return route.fulfill({
      status: 404,
      json: { detail: "Unexpected fixture request" },
    });
  });
  await disabledDialer(page);
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      json: {
        user: {
          id: uuid(11),
          role: "agent",
          display_name: "Agent réception",
          email: "agent@example.invalid",
          is_active: true,
        },
        mfa_enrollment_required: false,
      },
    }),
  );
  await page.route("**/api/inbound/reception", (route) =>
    route.fulfill({
      json: { enabled: false, queues: [], registration: null, active: null },
    }),
  );
  await page.route("**/api/inbound/queues", (route) =>
    route.fulfill({ json: { items: [queue] } }),
  );
  await page.route(`**/api/inbound/queues/${queue.id}/board`, (route) =>
    route.fulfill({
      json: {
        queue,
        columns: [
          {
            stage: "pending",
            name: "À traiter",
            count: 1,
            items: [followup],
            has_more: false,
          },
        ],
      },
    }),
  );
  await page.route(`**/api/inbound/followups/${followup.id}`, (route) =>
    route.fulfill({ json: { followup, events: [], has_more: false } }),
  );
  await page.route(`**/api/inbound/followups/${followup.id}/calls`, (route) =>
    route.fulfill({ json: { items: [], has_more: false } }),
  );
  await page.route(`**/api/inbound/queues/${queue.id}/calls`, (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: uuid(60),
            caller_number: followup.caller_number,
            profile: followup.profile,
            do_not_contact: followup.do_not_contact,
            non_interested: followup.non_interested,
            followup_id: followup.id,
            received_at: "2026-11-14T12:00:00Z",
            outcome: "abandoned",
            recordings: [],
          },
          {
            id: uuid(61),
            caller_number: number,
            profile,
            do_not_contact: options.dnc ?? false,
            non_interested: options.ni ?? false,
            followup_id: null,
            received_at: "2026-11-14T11:00:00Z",
            outcome: "answered",
            recordings: [],
          },
        ],
        has_more: false,
      },
    }),
  );
  await page.route("**/api/telephony/test/session", (route) =>
    route.fulfill({
      json: {
        enabled: true,
        max_duration_seconds: 1800,
        active: [...rows.values()].find((r) => r.state !== "finished") ?? null,
      },
    }),
  );
  await page.route("**/api/telephony/test/intents", (route) => {
    const body = route.request().postDataJSON();
    reservations.push(body);
    if (options.dnc)
      return route.fulfill({
        status: 403,
        json: {
          detail: "Ne pas contacter — ce client ne peut pas être rappelé.",
        },
      });
    if (failure)
      return route.fulfill({
        status: 409,
        json: {
          detail:
            "Ce numéro est déjà en cours d’appel. Réessayez après sa fin.",
        },
      });
    const intent = {
      id: body.id,
      destination: body.destination,
      caller_number: queue.phone,
      state: "reserved",
      owned_session: true,
      outcome: null,
    };
    rows.set(body.id, intent);
    return route.fulfill({
      json: { intent, token: "SYNTHETIC_CALLBACK_TOKEN" },
    });
  });
  await page.route(/\/api\/telephony\/test\/intents\/[a-f0-9-]+$/, (route) =>
    route.fulfill({
      json: {
        intent: rows.get(
          new URL(route.request().url()).pathname.split("/").at(-1)!,
        ),
      },
    }),
  );
  await page.route("**/api/telephony/test/intents/*/cancel", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").at(-2)!;
    const row = rows.get(id)!;
    row.state = "cancelled";
    row.outcome = "canceled";
    return route.fulfill({ json: row });
  });
  await page.route("**/assets/twilio-*.js", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: readFileSync(
        new URL("./fixtures/phone-sdk.js", import.meta.url),
        "utf8",
      ),
    }),
  );
  await page.goto("/appels-entrants");
  return {
    unexpected,
    reservations,
    rows,
    setFailure: (value: boolean) => {
      failure = value;
    },
  };
}
async function openFollowup(page: Page) {
  await page
    .getByRole("region", { name: "Suivis des appels entrants", exact: true })
    .getByRole("button")
    .filter({ hasText: "Nina Gros" })
    .click();
  return page.getByRole("dialog");
}

test("entrant : la fiche affiche les coordonnées et appelle le client sans quitter la page", async ({
  page,
}) => {
  const f = await setup(page);
  const dialog = await openFollowup(page);
  await expect(
    dialog.getByText("nina@example.invalid", { exact: true }),
  ).toBeVisible();
  await expect(
    dialog.getByText("123 rue du Test", { exact: true }),
  ).toBeVisible();
  await dialog
    .getByRole("button", { name: "Appeler ce client", exact: true })
    .click();
  await expect.poll(() => f.reservations.length).toBe(1);
  expect(f.reservations[0]).toEqual({
    id: expect.any(String),
    destination: number,
  });
  await expect
    .poll(() => page.evaluate(() => window.phoneProof?.connections.length ?? 0))
    .toBe(1);
  await expect(
    dialog.getByRole("button", { name: "Appeler ce client", exact: true }),
  ).toBeDisabled();
  await expect(
    dialog.getByRole("button", { name: "Raccrocher", exact: true }),
  ).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Boîte vocale", exact: true }),
  ).toBeVisible();
  await dialog
    .getByRole("button", { name: "Fermer la fenêtre", exact: true })
    .click();
  await expect(
    page.getByRole("complementary", { name: "Appel en cours", exact: true }),
  ).toContainText(number);
  expect(f.unexpected).toEqual([]);
});

for (const dnc of [false, true])
  test(`entrant : Non intéressé reste appelable en manuel, Ne pas contacter=${dnc}`, async ({
    page,
  }) => {
    const f = await setup(page, { dnc, ni: true });
    const dialog = await openFollowup(page);
    const call = dialog.getByRole("button", {
      name: "Appeler ce client",
      exact: true,
    });
    if (dnc) {
      await expect(call).toBeDisabled();
      await expect(dialog).toContainText("Ne pas contacter");
      expect(f.reservations).toHaveLength(0);
    } else {
      await expect(call).toBeEnabled();
      await call.click();
      await expect.poll(() => f.reservations.length).toBe(1);
    }
    expect(f.unexpected).toEqual([]);
  });

test("entrant : numéro masqué, aucune tentative d’appel", async ({ page }) => {
  const f = await setup(page, { hidden: true });
  await page
    .getByRole("region", { name: "Suivis des appels entrants", exact: true })
    .getByRole("button")
    .filter({ hasText: "Appelant à identifier" })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("button", { name: "Appeler ce client", exact: true }),
  ).toBeDisabled();
  await expect(dialog).toContainText("Numéro masqué");
  expect(f.reservations).toHaveLength(0);
  expect(f.unexpected).toEqual([]);
});

test("entrant : refus de réservation visible et nouvelle tentative possible", async ({
  page,
}) => {
  const f = await setup(page, { fail: true });
  const dialog = await openFollowup(page);
  const call = dialog.getByRole("button", {
    name: "Appeler ce client",
    exact: true,
  });
  await call.click();
  await expect(dialog.getByRole("alert")).toContainText(
    "déjà en cours d’appel",
  );
  await expect(call).toBeEnabled();
  f.setFailure(false);
  await call.click();
  await expect.poll(() => f.reservations.length).toBe(2);
  await expect
    .poll(() => page.evaluate(() => window.phoneProof?.connections.length ?? 0))
    .toBe(1);
  expect(f.unexpected).toEqual([]);
});

for (const linked of [true, false])
  test(`historique entrant : fiche et rappel depuis un appel avec suivi=${linked}`, async ({
    page,
  }) => {
    const f = await setup(page);
    await page
      .getByRole("button", { name: /Historique des appels reçus/ })
      .click();
    await page
      .getByRole("button", { name: "Voir la fiche client", exact: true })
      .nth(linked ? 0 : 1)
      .click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Montréal", { exact: true })).toBeVisible();
    await dialog
      .getByRole("button", { name: "Appeler ce client", exact: true })
      .click();
    await expect.poll(() => f.reservations.length).toBe(1);
    expect(f.reservations[0].destination).toBe(number);
    expect(f.unexpected).toEqual([]);
  });

test("fiche entrante : mobile et accessibilité", async ({ page }) => {
  const f = await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const dialog = await openFollowup(page);
  await expect(dialog.getByText("H2X 1Y4", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const a11y = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(a11y.violations.map((v) => v.id)).toEqual([]);
  await page.screenshot({
    path: "../qa-reports/evidence/inbound-client-mobile.png",
    fullPage: true,
  });
  expect(f.unexpected).toEqual([]);
});

test("entrant : un appelant non importé peut être rappelé sans créer de contact", async ({
  page,
}) => {
  const f = await setup(page, { unknown: true });
  await page
    .getByRole("region", { name: "Suivis des appels entrants", exact: true })
    .getByRole("button")
    .filter({ hasText: "Appelant à identifier" })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Appeler ce client", exact: true })
    .click();
  await expect.poll(() => f.reservations.length).toBe(1);
  expect(f.reservations[0].destination).toBe(number);
  expect(f.unexpected).toEqual([]);
});

test("historique sans suivi : Ne pas contacter interdit le rappel", async ({
  page,
}) => {
  const f = await setup(page, { dnc: true });
  await page
    .getByRole("button", { name: /Historique des appels reçus/ })
    .click();
  await page
    .getByRole("button", { name: "Voir la fiche client", exact: true })
    .nth(1)
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Ne pas contacter");
  await expect(
    dialog.getByRole("button", { name: "Appeler ce client", exact: true }),
  ).toBeDisabled();
  expect(f.reservations).toHaveLength(0);
  expect(f.unexpected).toEqual([]);
});

for (const view of ["Liste", "Pipeline", "Historique"] as const)
  test(`rappel direct entrant depuis ${view} : une seule réservation et fiche client ouverte`, async ({
    page,
  }) => {
    const f = await setup(page);
    if (view === "Pipeline")
      await page.getByRole("button", { name: "Pipeline", exact: true }).click();
    if (view === "Historique")
      await page
        .getByRole("button", { name: /Historique des appels reçus/ })
        .click();
    const area =
      view === "Historique"
        ? page.locator(".incoming-history")
        : page.getByRole("region", {
            name: "Suivis des appels entrants",
            exact: true,
          });
    await area
      .getByRole("button", { name: "Rappeler Nina Gros", exact: true })
      .first()
      .click();
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByText("nina@example.invalid", { exact: true }),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "Raccrocher", exact: true }),
    ).toBeVisible();
    await expect.poll(() => f.reservations.length).toBe(1);
    expect(f.reservations[0]).toEqual({
      id: expect.any(String),
      destination: number,
    });
    expect(f.unexpected).toEqual([]);
  });

async function openConversation(page: Page, destination = number) {
  await page.route("**/api/telephony/calls*", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: uuid(71),
            created_at: "2026-11-14T12:00:00Z",
            destination,
            contact_name: "Nina Gros",
            actor_name: "Agent réception",
            campaign_id: null,
            contact_id: null,
            state: "finished",
            outcome: "completed",
            recordings: [],
          },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.goto("/conversations");
  return page.getByRole("region", { name: "Rappeler ce contact", exact: true });
}

test("conversation : rappeler un appel manuel sans campagne, puis raccrocher depuis la conversation", async ({
  page,
}) => {
  const f = await setup(page);
  const controls = await openConversation(page);
  const call = controls.getByRole("button", { name: "Rappeler", exact: true });
  await expect(call).toBeEnabled();
  await call.dblclick();
  await expect.poll(() => f.reservations.length).toBe(1);
  expect(f.reservations[0]).toEqual({
    id: expect.any(String),
    destination: number,
  });
  await expect(
    controls.getByRole("button", { name: "Raccrocher", exact: true }),
  ).toBeVisible();
  await controls
    .getByRole("button", { name: "Raccrocher", exact: true })
    .click();
  await expect
    .poll(() => page.evaluate(() => window.phoneProof?.disconnected ?? 0))
    .toBeGreaterThan(0);
  expect(f.unexpected).toEqual([]);
});

test("conversation : Ne pas contacter reste refusé par le serveur", async ({
  page,
}) => {
  const f = await setup(page, { dnc: true });
  const controls = await openConversation(page);
  await controls.getByRole("button", { name: "Rappeler", exact: true }).click();
  await expect(controls.getByRole("alert")).toContainText("Ne pas contacter");
  expect(f.rows.size).toBe(0);
  expect(
    await page.evaluate(() => window.phoneProof?.connections.length ?? 0),
  ).toBe(0);
  expect(f.unexpected).toEqual([]);
});

test("conversation : erreur visible, nouvelle tentative possible et affichage mobile accessible", async ({
  page,
}) => {
  const f = await setup(page, { fail: true });
  const controls = await openConversation(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const call = controls.getByRole("button", { name: "Rappeler", exact: true });
  await call.click();
  await expect(controls.getByRole("alert")).toContainText(
    "déjà en cours d’appel",
  );
  await expect(call).toBeEnabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const audit = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(audit.violations.map((v) => v.id)).toEqual([]);
  await page.screenshot({
    path: "../qa-reports/evidence/direct-recall-conversation-mobile.png",
    fullPage: true,
  });
  f.setFailure(false);
  await call.click();
  await expect.poll(() => f.reservations.length).toBe(2);
  await expect
    .poll(() => page.evaluate(() => window.phoneProof?.connections.length ?? 0))
    .toBe(1);
  expect(f.unexpected).toEqual([]);
});

for (const options of [{ dnc: true }, { hidden: true }])
  test(`rappel direct : numéro indisponible sans réservation ${JSON.stringify(options)}`, async ({
    page,
  }) => {
    const f = await setup(page, options);
    const area = page.getByRole("region", {
      name: "Suivis des appels entrants",
      exact: true,
    });
    await expect(
      area.getByRole("button", { name: /^Rappeler / }),
    ).toBeDisabled();
    expect(f.reservations).toHaveLength(0);
    expect(f.unexpected).toEqual([]);
  });

test("historique entrant sans suivi : rappeler ouvre les coordonnées disponibles", async ({
  page,
}) => {
  const f = await setup(page);
  await page
    .getByRole("button", { name: /Historique des appels reçus/ })
    .click();
  await page
    .locator(".incoming-history")
    .getByRole("button", { name: "Rappeler Nina Gros", exact: true })
    .nth(1)
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByText("nina@example.invalid", { exact: true }),
  ).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Raccrocher", exact: true }),
  ).toBeVisible();
  await expect.poll(() => f.reservations.length).toBe(1);
  expect(f.unexpected).toEqual([]);
});

test("liste entrante : actions visibles et accessibles sur mobile", async ({
  page,
}) => {
  const f = await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const area = page.getByRole("region", {
    name: "Suivis des appels entrants",
    exact: true,
  });
  await expect(
    area.getByRole("button", { name: "Rappeler Nina Gros", exact: true }),
  ).toBeEnabled();
  await expect(area.getByText("Fiche client", { exact: false })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const report = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(report.violations.map((v) => v.id)).toEqual([]);
  await page.screenshot({
    path: "../qa-reports/evidence/direct-recall-incoming-mobile.png",
    fullPage: true,
  });
  expect(f.unexpected).toEqual([]);
});
