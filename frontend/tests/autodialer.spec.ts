import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";

test.use({
  launchOptions: {
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  },
});
const campaign = "00000000-0000-0000-0000-000000000031";
const user = "00000000-0000-0000-0000-000000000011";
const ca = "00000000-0000-0000-0000-000000000041";
const gb = "00000000-0000-0000-0000-000000000042";
type Row = {
  id: string;
  state: string;
  outcome: string | null;
  destination: string;
  caller_number: string;
  campaign_id: string;
  contact_id: string;
  callback_id: string | null;
  automatic: boolean;
  owned_session: boolean;
};
type Dialer = {
  mode: string;
  generation: number;
  campaign_id: string | null;
  browser_id: string | null;
  hold_token: string | null;
};
async function setup(page: Page, role = "agent") {
  const rows = new Map<string, Row>();
  let dialer: Dialer = {
    mode: "stopped",
    generation: 0,
    campaign_id: null,
    browser_id: null,
    hold_token: null,
  };
  let nextCount = 0;
  let settings = {
    version: 0,
    enabled: false,
    default_number_id: null as string | null,
    hours: [] as { weekday: number; start: number; end: number }[],
    rules: [] as { number_id: string; country: string; prefix: string }[],
  };
  const controls: string[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body =
      route.request().method() === "GET"
        ? null
        : route.request().postDataJSON();
    let result: unknown;
    if (path === "/api/auth/me")
      result = {
        user: {
          id: user,
          email: "dialer@example.invalid",
          display_name: "Agent composeur",
          role,
          is_active: true,
        },
        mfa_enrollment_required: false,
      };
    else if (path === "/api/telephony/test/session")
      result = {
        enabled: true,
        destination: null,
        max_duration_seconds: 600,
        active:
          [...rows.values()].find(
            (r) => !["finished", "cancelled"].includes(r.state),
          ) || null,
      };
    else if (path === "/api/telephony/calls")
      result = { items: [], next_cursor: null };
    else if (path === "/api/telephony/active-calls")
      result = { items: [], active_count: 0, answered_count: 0 };
    else if (path === "/api/telephony/dialer/session")
      result = { enabled: true, dialer: { ...dialer } };
    else if (path === "/api/telephony/dialer/campaigns")
      result = {
        items: [
          {
            id: campaign,
            name: "Campagne Canada",
            timezone: "America/Toronto",
            automatic_enabled: true,
          },
        ],
      };
    else if (path === "/api/telephony/dialer/control") {
      controls.push(body.action);
      dialer = {
        ...dialer,
        generation: dialer.generation + 1,
        browser_id: body.browser_id,
        campaign_id: body.campaign_id || dialer.campaign_id,
      };
      if (body.action === "start" || body.action === "release")
        dialer.mode = "running";
      else if (body.action === "hold") {
        dialer.mode = "booking";
        dialer.hold_token = body.hold_token;
      } else {
        dialer.mode = body.action === "stop" ? "stopped" : "paused";
        dialer.hold_token = null;
        for (const row of rows.values())
          if (row.state === "reserved") row.state = "cancelled";
      }
      result = { dialer: { ...dialer } };
    } else if (path === "/api/telephony/dialer/heartbeat")
      result = { dialer: { ...dialer } };
    else if (path === "/api/telephony/dialer/next") {
      nextCount += 1;
      const row: Row = {
        id: body.id,
        state: "reserved",
        outcome: null,
        destination: nextCount === 1 ? "+14165550111" : "+14165550112",
        caller_number: "+14165550200",
        campaign_id: campaign,
        contact_id: "00000000-0000-0000-0000-000000000051",
        callback_id:
          nextCount === 1 ? "00000000-0000-0000-0000-000000000061" : null,
        automatic: true,
        owned_session: true,
      };
      rows.set(row.id, row);
      result = {
        intent: { ...row },
        token: "synthetic-sdk-token",
        dialer: { ...dialer },
      };
    } else if (
      /^\/api\/telephony\/test\/intents\/[a-f0-9-]+\/cancel$/.test(path)
    ) {
      const row = rows.get(path.split("/").at(-2)!)!;
      row.state = "cancelled";
      result = { ...row };
    } else if (/^\/api\/telephony\/test\/intents\/[a-f0-9-]+$/.test(path))
      result = { intent: rows.get(path.split("/").at(-1)!) };
    else if (path === "/api/telephony/numbers")
      result = {
        configured: true,
        sync: {
          synchronized_at: new Date().toISOString(),
          last_error_code: null,
          syncing: false,
        },
        items: [
          {
            id: ca,
            number: "+14165550200",
            name: "Toronto",
            country: "CA",
            voice_enabled: true,
            is_present: true,
            is_active: true,
            fresh: true,
          },
          {
            id: gb,
            number: "+442079460002",
            name: "Royaume-Uni",
            country: "GB",
            voice_enabled: true,
            is_present: true,
            is_active: true,
            fresh: true,
          },
        ],
      };
    else if (path === `/api/telephony/campaigns/${campaign}/calling`) {
      if (body) {
        settings = {
          version: settings.version + 1,
          enabled: body.enabled,
          default_number_id: body.default_number_id,
          hours: body.hours,
          rules: body.rules,
        };
      }
      result = {
        settings: { ...settings },
        timezone: "America/Toronto",
        attempts_per_day: 2,
        retry_hours: 2,
      };
    } else
      return route.fulfill({
        status: 404,
        json: { detail: "Fixture API manquante : " + path },
      });
    return route.fulfill({ json: result });
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
  return {
    rows,
    controls,
    get nextCount() {
      return nextCount;
    },
    get settings() {
      return settings;
    },
  };
}
async function start(page: Page) {
  await page.goto("/poste-appel");
  await page
    .getByRole("combobox", { name: "Campagne d’appel", exact: true })
    .selectOption(campaign);
  await page
    .getByRole("button", { name: "Démarrer les appels", exact: true })
    .click();
  await expect
    .poll(() => page.evaluate(() => window.phoneProof?.connections.length || 0))
    .toBe(1);
}

test("agent : rappel prioritaire, pause sans raccrochage puis reprise explicite", async ({
  page,
}) => {
  const f = await setup(page);
  await page.goto("/poste-appel");
  expect(f.nextCount).toBe(0);
  expect(await page.evaluate(() => window.phoneProof?.created || 0)).toBe(0);
  await page
    .getByRole("combobox", { name: "Campagne d’appel", exact: true })
    .selectOption(campaign);
  await page
    .getByRole("button", { name: "Démarrer les appels", exact: true })
    .click();
  await expect.poll(() => f.nextCount).toBe(1);
  await expect
    .poll(() => page.evaluate(() => window.phoneProof?.connections.length || 0))
    .toBe(1);
  const row = [...f.rows.values()][0];
  row.state = "answered";
  await page.evaluate(() => window.phoneProof.call!.emit("accept"));
  await expect(
    page.getByText("+14165550111 · rappel programmé", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Mettre en pause", exact: true })
    .click();
  await expect.poll(() => f.controls.at(-1)).toBe("pause");
  expect(await page.evaluate(() => window.phoneProof.disconnected)).toBe(0);
  row.state = "finished";
  row.outcome = "completed";
  await page.evaluate(() => window.phoneProof.call!.emit("disconnect"));
  await expect(
    page.getByRole("complementary", { name: "Appel en cours", exact: true }),
  ).toHaveCount(0);
  expect(f.nextCount).toBe(1);
  await page
    .getByRole("button", { name: "Reprendre les appels", exact: true })
    .click();
  await expect.poll(() => f.nextCount).toBe(2);
});

test("agent : un résultat serveur terminé déclenche le contact suivant sans nouveau clic", async ({
  page,
}) => {
  const f = await setup(page);
  await start(page);
  expect(
    await page.evaluate(() => Object.keys(window.phoneProof.connections[0])),
  ).toEqual(["Intent"]);
  const row = [...f.rows.values()][0];
  row.state = "finished";
  row.outcome = "no-answer";
  await page.evaluate(() => window.phoneProof.call!.emit("disconnect"));
  await expect.poll(() => f.nextCount).toBe(2);
  await page.getByRole("link", { name: "Mon compte", exact: true }).click();
  await expect(
    page.getByRole("complementary", { name: "Appel en cours", exact: true }),
  ).toBeVisible();
});

test("administrateur : numéros vérifiés, horaires et règle régionale conservés", async ({
  page,
}) => {
  const f = await setup(page, "admin");
  await page.goto("/poste-appel");
  await page
    .getByRole("combobox", { name: "Campagne d’appel", exact: true })
    .selectOption(campaign);
  await page
    .getByRole("button", { name: "Régler la téléphonie", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("Autoriser le composeur automatique pour cette campagne")
    .check();
  await dialog
    .getByRole("combobox", { name: "Numéro émetteur par défaut", exact: true })
    .selectOption(ca);
  await dialog
    .getByRole("button", { name: "Ajouter une plage horaire", exact: true })
    .click();
  await dialog.getByLabel("Début de la plage 1", { exact: true }).fill("08:30");
  await dialog.getByLabel("Fin de la plage 1", { exact: true }).fill("19:00");
  await dialog
    .getByRole("button", { name: "Ajouter une règle régionale", exact: true })
    .click();
  await dialog
    .getByLabel("Pays de la règle 1 (optionnel)", { exact: true })
    .fill("GB");
  await dialog
    .getByLabel("Préfixe de la règle 1 (optionnel)", { exact: true })
    .fill("+44");
  await dialog
    .getByRole("combobox", { name: "Numéro de la règle 1", exact: true })
    .selectOption(gb);
  await dialog
    .getByRole("button", { name: "Enregistrer la téléphonie", exact: true })
    .click();
  await expect(
    dialog.getByText("Réglages téléphoniques enregistrés.", { exact: true }),
  ).toBeVisible();
  expect(f.settings.hours).toEqual([{ weekday: 0, start: 510, end: 1140 }]);
  expect(f.settings.rules).toEqual([
    { number_id: gb, country: "GB", prefix: "+44" },
  ]);
  const report = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(report.violations.map((v) => v.id)).toEqual([]);
  await dialog
    .getByRole("button", { name: "Fermer la fenêtre", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Régler la téléphonie", exact: true })
    .click();
  await expect(
    page.getByLabel("Préfixe de la règle 1 (optionnel)", { exact: true }),
  ).toHaveValue("+44");
  expect(f.nextCount).toBe(0);
});

test("refus du microphone : aucun composeur serveur ni appel", async ({
  page,
}) => {
  const f = await setup(page);
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      throw new DOMException("", "NotAllowedError");
    };
  });
  await page.goto("/poste-appel");
  await page
    .getByRole("combobox", { name: "Campagne d’appel", exact: true })
    .selectOption(campaign);
  await page
    .getByRole("button", { name: "Démarrer les appels", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Autorisez et vérifiez le microphone",
  );
  expect(f.controls).toEqual([]);
  expect(f.nextCount).toBe(0);
});
