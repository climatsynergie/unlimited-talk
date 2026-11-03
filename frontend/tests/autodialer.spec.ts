import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import {
  qualificationSchema,
  validQualification,
  fillQualification,
} from "./fixtures/qualification";
import type { SavedQualification } from "../src/Qualification";

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
async function setup(page: Page, role = "agent", sameContact = false) {
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
  const notes: {
    id: string;
    contact: string;
    content: string;
    created_at: string;
    actor_name: string;
  }[] = [];
  const moves: { contact: string; stage: string }[] = [];
  const moveRequests: string[] = [];
  const appliedMoves = new Set<string>();
  const qualifications = new Map<string, SavedQualification>();
  const qualificationReplays = new Map<string, SavedQualification>();
  const appointments: Record<string, unknown>[] = [];
  const stages = [
    { id: "stage-new", name: "À appeler", kind: "new" },
    { id: "stage-other", name: "Autre", kind: "other" },
    { id: "stage-appointment", name: "RDV booké", kind: "appointment" },
    { id: "stage-restricted", name: "Non intéressé", kind: "non_interested" },
  ];
  const versions = new Map<string, number>();
  const stageByContact = new Map<string, string>();
  const failures = { note: false, move: false, qualification: false };
  const detailReads = {
    block: false,
    pending: 0,
    release: null as (() => void) | null,
  };
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
        contact_id: `00000000-0000-0000-0000-${String(50 + (sameContact ? 1 : nextCount)).padStart(12, "0")}`,
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
    } else if (path === `/api/campaigns/${campaign}/board`) {
      result = {
        campaign: {
          id: campaign,
          name: "Campagne Canada",
          timezone: "America/Toronto",
          is_active: true,
          version: 0,
        },
        stages: stages.map((stage, position) => ({
          ...stage,
          position,
          color: "violet",
          total: 0,
          items: [],
        })),
      };
    } else if (path.startsWith(`/api/campaigns/${campaign}/contacts/`)) {
      const parts = path.split("/");
      const contact = parts[5];
      const action = parts[6];
      if (action === "notes") {
        if (failures.note)
          return route.fulfill({
            status: 503,
            json: { detail: "Enregistrement indisponible, réessayez." },
          });
        notes.push({
          ...body,
          contact,
          created_at: new Date().toISOString(),
          actor_name: "Agent composeur",
        });
        result = { id: body.id };
      } else if (action === "qualification") {
        if (failures.qualification)
          return route.fulfill({
            status: 503,
            json: { detail: "Qualification non enregistrée. Réessayez." },
          });
        if (qualificationReplays.has(body.request_id))
          result = qualificationReplays.get(body.request_id);
        else {
          const current = qualifications.get(contact);
          if (body.expected_revision !== (current?.revision || null))
            return route.fulfill({
              status: 409,
              json: { detail: "Qualification modifiée par un autre agent." },
            });
          const saved = {
            revision: String(Number(current?.revision || 0) + 1),
            qualification: body.qualification,
          };
          qualifications.set(contact, saved);
          qualificationReplays.set(body.request_id, saved);
          result = saved;
        }
      } else if (action === "move") {
        moveRequests.push(body.request_id);
        if (!appliedMoves.has(body.request_id)) {
          expect(body.version).toBe(versions.get(contact) || 0);
          stageByContact.set(contact, body.stage_id);
          versions.set(contact, body.version + 1);
          moves.push({ contact, stage: body.stage_id });
          appliedMoves.add(body.request_id);
        }
        if (failures.move)
          return route.fulfill({
            status: 503,
            json: { detail: "Réponse interrompue après le déplacement." },
          });
        result = {};
      } else {
        if (detailReads.block) {
          detailReads.pending += 1;
          await new Promise<void>((resolve) => {
            detailReads.release = resolve;
          });
          detailReads.pending -= 1;
          detailReads.block = false;
        }
        result = {
          contact: {
            contact_id: contact,
            phone: "+14165550111",
            profile: {
              display_name: `Client ${Number(contact.slice(-2)) - 50}`,
              city: "Montréal",
            },
            stage_id: stageByContact.get(contact) || "stage-new",
            version: versions.get(contact) || 0,
            queue_position: "1",
            do_not_contact: false,
            non_interested: false,
            contact_updated_at: new Date().toISOString(),
          },
          notes: notes.filter((note) => note.contact === contact),
          events: [],
          notes_has_more: false,
          events_has_more: false,
          qualification_schema: qualificationSchema,
          booker_name: "Agent composeur",
          qualification: qualifications.get(contact) || null,
        };
      }
    } else if (path === "/api/calendar/resolve") {
      result = {
        options: [
          {
            starts_at: "2026-11-03T15:00:00Z",
            utc_offset_minutes: -300,
            label: "Toronto",
          },
        ],
      };
    } else if (path === "/api/calendar" && body) {
      if (
        body.qualification_revision !==
        (qualifications.get(body.contact_id)?.revision || null)
      )
        return route.fulfill({
          status: 409,
          json: {
            detail:
              "La qualification a changé. Actualisez la fiche avant de confirmer ce rendez-vous.",
          },
        });
      appointments.push(body);
      qualifications.set(body.contact_id, {
        revision: String(
          Number(qualifications.get(body.contact_id)?.revision || 0) + 1,
        ),
        qualification: body.qualification,
      });
      stageByContact.set(body.contact_id, "stage-appointment");
      versions.set(body.contact_id, (versions.get(body.contact_id) || 0) + 1);
      result = { id: body.id };
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
    notes,
    moves,
    moveRequests,
    qualifications,
    appointments,
    failures,
    detailReads,
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
  await expect.poll(() => f.nextCount, { timeout: 12_000 }).toBe(2);
});

test("agent : après la fin serveur, aucun appel avant cinq secondes puis reprise automatique", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-11-03T12:00:00Z") });
  await page.clock.pauseAt(new Date("2026-11-03T12:00:01Z"));
  const f = await setup(page);
  await start(page);
  expect(
    await page.evaluate(() => Object.keys(window.phoneProof.connections[0])),
  ).toEqual(["Intent"]);
  const row = [...f.rows.values()][0];
  row.state = "finished";
  row.outcome = "no-answer";
  await page.evaluate(() => window.phoneProof.call!.emit("disconnect"));
  const wait = page.getByRole("complementary", {
    name: "Prochain appel",
    exact: true,
  });
  await expect(wait).toBeVisible();
  await expect(wait.getByRole("timer")).toHaveText("5 s");
  await page.clock.runFor(4_999);
  expect(f.nextCount).toBe(1);
  await page.clock.runFor(1);
  await expect.poll(() => f.nextCount, { timeout: 12_000 }).toBe(2);
  await page.getByRole("link", { name: "Mon compte", exact: true }).click();
  await expect(
    page.getByRole("complementary", { name: "Appel en cours", exact: true }),
  ).toBeVisible();
});

test("agent : Attendre reste visible pendant la navigation et bloque jusqu’à Reprendre les appels", async ({
  page,
}) => {
  await page.clock.install();
  const f = await setup(page);
  await start(page);
  const first = [...f.rows.values()][0];
  first.state = "finished";
  first.outcome = "completed";
  await page.evaluate(() => window.phoneProof.call!.emit("disconnect"));
  const wait = page.getByRole("complementary", {
    name: "Prochain appel",
    exact: true,
  });
  await expect(wait).toBeVisible();
  await page.screenshot({
    path: "/tmp/ut-between-calls-desktop.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "Mon compte", exact: true }).click();
  await expect(wait).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const report = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    report.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({
        target: n.target,
        summary: n.failureSummary,
      })),
    })),
  ).toEqual([]);
  await page.screenshot({
    path: "/tmp/ut-between-calls-mobile.png",
    fullPage: true,
  });
  await wait.getByRole("button", { name: "Attendre", exact: true }).click();
  await expect.poll(() => f.controls.at(-1)).toBe("pause");
  await page.clock.fastForward(30_000);
  expect(f.nextCount).toBe(1);
  await expect(wait).toHaveCount(0);
  await page.getByRole("link", { name: "Poste d’appel", exact: true }).click();
  const sheet = page.getByRole("region", {
    name: "Fiche du contact",
    exact: true,
  });
  await expect(
    sheet.getByRole("heading", { name: "Client 1", exact: true }),
  ).toBeVisible();
  await sheet
    .getByRole("textbox", { name: "Ajouter une note", exact: true })
    .fill("Le client demande des informations après l’appel.");
  await sheet
    .getByRole("button", { name: "Enregistrer la note", exact: true })
    .click();
  await expect.poll(() => f.notes.length).toBe(1);
  await page
    .getByRole("button", { name: "Reprendre les appels", exact: true })
    .click();
  await expect.poll(() => f.nextCount, { timeout: 12_000 }).toBe(2);
});

test("fiche pendant l’appel : conserve la saisie sur le bon client lorsque l’enchaînement continue", async ({
  page,
}) => {
  const f = await setup(page);
  await start(page);
  const sheet = page.getByRole("region", {
    name: "Fiche du contact",
    exact: true,
  });
  await expect(
    sheet.getByRole("heading", { name: "Client 1", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Raccrocher", exact: true }),
  ).toBeEnabled();
  await sheet
    .getByRole("textbox", { name: "Ajouter une note", exact: true })
    .fill("Client propriétaire, souhaite un rendez-vous.");
  const first = [...f.rows.values()][0];
  first.state = "finished";
  first.outcome = "completed";
  await page.evaluate(() => window.phoneProof.call!.emit("disconnect"));
  await expect.poll(() => f.nextCount, { timeout: 12_000 }).toBe(2);
  await expect(
    page.getByText(/Vous complétez encore la fiche de l’appel précédent/),
  ).toBeVisible();
  await expect(
    sheet.getByRole("heading", { name: "Client 1", exact: true }),
  ).toBeVisible();
  f.failures.note = true;
  await sheet
    .getByRole("button", { name: "Enregistrer la note", exact: true })
    .click();
  await expect(sheet.getByRole("alert")).toContainText(
    "Enregistrement indisponible",
  );
  await expect(
    sheet.getByRole("textbox", { name: "Ajouter une note", exact: true }),
  ).toHaveValue("Client propriétaire, souhaite un rendez-vous.");
  f.failures.note = false;
  await sheet
    .getByRole("button", { name: "Enregistrer la note", exact: true })
    .click();
  await expect.poll(() => f.notes.length).toBe(1);
  expect(f.notes[0].contact).toBe(first.contact_id);
  expect(f.notes[0].content).toBe(
    "Client propriétaire, souhaite un rendez-vous.",
  );
  await expect(
    sheet.getByRole("heading", { name: "Client 2", exact: true }),
  ).toBeVisible();
  await expect(
    sheet.getByRole("textbox", { name: "Ajouter une note", exact: true }),
  ).toBeEmpty();
  await sheet
    .getByRole("combobox", { name: "Étape du pipeline", exact: true })
    .selectOption("stage-other");
  f.failures.move = true;
  await sheet
    .getByRole("button", { name: "Déplacer vers cette étape", exact: true })
    .click();
  await expect(sheet.getByRole("alert")).toContainText("Réponse interrompue");
  f.failures.move = false;
  f.detailReads.block = true;
  await sheet
    .getByRole("button", { name: "Déplacer vers cette étape", exact: true })
    .click();
  await expect.poll(() => f.moveRequests.length).toBe(2);
  expect(f.moveRequests[0]).toBe(f.moveRequests[1]);
  await expect.poll(() => f.detailReads.pending).toBe(1);
  await expect(
    sheet.getByRole("combobox", { name: "Étape du pipeline", exact: true }),
  ).toBeDisabled();
  f.detailReads.release!();
  await expect.poll(() => f.moves.length).toBe(1);
  expect(f.moves[0]).toEqual({
    contact: [...f.rows.values()][1].contact_id,
    stage: "stage-other",
  });
  await expect(
    sheet.getByRole("combobox", { name: "Étape du pipeline", exact: true }),
  ).toHaveValue("stage-other");
  await sheet
    .getByRole("combobox", { name: "Étape du pipeline", exact: true })
    .selectOption("stage-restricted");
  await sheet
    .getByRole("button", { name: "Déplacer vers cette étape", exact: true })
    .click();
  await expect(
    sheet.getByRole("region", {
      name: "Confirmer la restriction",
      exact: true,
    }),
  ).toBeVisible();
  expect(f.moves).toHaveLength(1);
  await sheet
    .getByRole("button", {
      name: "Confirmer pour toutes les campagnes",
      exact: true,
    })
    .click();
  await expect.poll(() => f.moves.length).toBe(2);
});

test("qualification : sans RDV, la fiche passe directement au prochain contact", async ({
  page,
}) => {
  const f = await setup(page);
  await start(page);
  const sheet = page.getByRole("region", {
    name: "Fiche du contact",
    exact: true,
  });
  const field = (key: string) =>
    qualificationSchema.fields.find((field) => field.key === key)!;
  await expect(sheet.locator(".booking-booker")).toContainText(
    "Agent composeur",
  );
  await sheet
    .getByRole("combobox", { name: field("owner").label, exact: true })
    .selectOption("Oui");
  await expect(
    sheet.getByRole("combobox", { name: field("owners").label, exact: true }),
  ).toBeVisible();
  await sheet
    .getByRole("combobox", { name: field("heat_pump").label, exact: true })
    .selectOption("Oui, murale");
  await expect(
    sheet.getByRole("textbox", {
      name: field("wall_pump_floors").label,
      exact: true,
    }),
  ).toBeVisible();
  await sheet
    .getByRole("combobox", { name: field("heat_pump").label, exact: true })
    .selectOption("Non");
  await expect(
    sheet.getByRole("textbox", {
      name: field("wall_pump_floors").label,
      exact: true,
    }),
  ).toHaveCount(0);
  await sheet
    .getByRole("textbox", { name: field("city").label, exact: true })
    .fill("Laval");
  await expect(
    sheet.getByRole("button", {
      name: "Enregistrer la qualification",
      exact: true,
    }),
  ).toHaveCount(0);
  const first = [...f.rows.values()][0];
  first.state = "finished";
  first.outcome = "completed";
  await page.evaluate(() => window.phoneProof.call!.emit("disconnect"));
  await expect.poll(() => f.nextCount, { timeout: 12_000 }).toBe(2);
  await expect(
    sheet.getByRole("heading", { name: "Client 2", exact: true }),
  ).toBeVisible();
  await expect(
    sheet.getByRole("combobox", { name: field("owner").label, exact: true }),
  ).toHaveValue("");
  await expect(
    sheet.getByRole("textbox", { name: field("city").label, exact: true }),
  ).toHaveValue("Montréal");
  expect(f.controls).not.toContain("hold");
  expect(f.qualifications.has(first.contact_id)).toBe(false);
  expect(f.appointments).toHaveLength(0);
});

test("qualification : une nouvelle tentative sur le même contact repart de sa fiche enregistrée", async ({
  page,
}) => {
  const f = await setup(page, "agent", true);
  await start(page);
  const sheet = page.getByRole("region", {
    name: "Fiche du contact",
    exact: true,
  });
  const field = qualificationSchema.fields.find(
    (field) => field.key === "owner",
  )!;
  await sheet
    .getByRole("combobox", { name: field.label, exact: true })
    .selectOption("Oui");
  const first = [...f.rows.values()][0];
  first.state = "finished";
  first.outcome = "completed";
  await page.evaluate(() => window.phoneProof.call!.emit("disconnect"));
  await expect.poll(() => f.nextCount, { timeout: 12_000 }).toBe(2);
  await expect(
    sheet.getByRole("combobox", { name: field.label, exact: true }),
  ).toHaveValue("");
  expect(f.qualifications.size).toBe(0);
  expect(f.appointments).toHaveLength(0);
});

test("qualification : conflit de réservation conserve les réponses jusqu’au rechargement explicite", async ({
  page,
}) => {
  const f = await setup(page);
  await start(page);
  const sheet = page.getByRole("region", {
    name: "Fiche du contact",
    exact: true,
  });
  const city = qualificationSchema.fields.find(
    (field) => field.key === "city",
  )!.label;
  const first = [...f.rows.values()][0];
  await fillQualification(sheet);
  f.qualifications.set(first.contact_id, {
    revision: "99",
    qualification: {
      ...validQualification,
      answers: { ...validQualification.answers, city: "Québec" },
    },
  });
  await sheet
    .getByRole("button", { name: "Prendre rendez-vous", exact: true })
    .click();
  await sheet
    .getByLabel("Date et heure du rendez-vous", { exact: true })
    .fill("2026-11-03T10:00");
  await sheet
    .getByRole("button", { name: "Confirmer le rendez-vous", exact: true })
    .click();
  await expect(sheet.getByRole("alert")).toContainText(
    "La qualification a changé",
  );
  await expect(
    sheet.getByRole("textbox", { name: city, exact: true }),
  ).toHaveValue("Montréal");
  expect(f.appointments).toHaveLength(0);
  await sheet
    .getByRole("button", { name: "Annuler la saisie", exact: true })
    .click();
  await sheet
    .getByRole("button", {
      name: "Abandonner mes modifications et recharger",
      exact: true,
    })
    .click();
  await expect(
    sheet.getByRole("textbox", { name: city, exact: true }),
  ).toHaveValue("Québec");
  await sheet
    .getByRole("button", { name: "Prendre rendez-vous", exact: true })
    .click();
  await sheet
    .getByLabel("Date et heure du rendez-vous", { exact: true })
    .fill("2026-11-03T10:00");
  await sheet
    .getByRole("button", { name: "Confirmer le rendez-vous", exact: true })
    .click();
  await expect.poll(() => f.appointments.length).toBe(1);
  expect(
    f.qualifications.get(first.contact_id)?.qualification.answers.city,
  ).toBe("Québec");
});

test("fiche pendant l’appel : réservation sans fenêtre bloquante et passage à RDV booké", async ({
  page,
}) => {
  const f = await setup(page);
  await start(page);
  const sheet = page.getByRole("region", {
    name: "Fiche du contact",
    exact: true,
  });
  await sheet
    .getByRole("button", { name: "Prendre rendez-vous", exact: true })
    .click();
  await expect.poll(() => f.controls.at(-1)).toBe("hold");
  await expect(
    page.getByRole("button", { name: "Raccrocher", exact: true }),
  ).toBeEnabled();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.screenshot({
    path: "/tmp/ut-call-sheet-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
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
    path: "/tmp/ut-call-sheet-mobile.png",
    fullPage: true,
  });
  await sheet
    .getByLabel("Date et heure du rendez-vous", { exact: true })
    .fill("2026-11-03T10:00");
  await sheet
    .getByLabel("Notes du rendez-vous", { exact: true })
    .fill("Détails de la demande du client.");
  await sheet
    .getByRole("button", { name: "Confirmer le rendez-vous", exact: true })
    .click();
  expect(f.appointments).toHaveLength(0);
  await fillQualification(sheet);
  await sheet
    .getByRole("button", { name: "Confirmer le rendez-vous", exact: true })
    .click();
  await expect.poll(() => f.appointments.length).toBe(1);
  expect(f.appointments[0]).toMatchObject({
    campaign_id: campaign,
    contact_id: [...f.rows.values()][0].contact_id,
    local_start: "2026-11-03T10:00",
    timezone: "America/Toronto",
    duration_minutes: 30,
    notes: "Détails de la demande du client.",
    qualification: validQualification,
  });
  await expect(
    sheet.getByRole("combobox", { name: "Étape du pipeline", exact: true }),
  ).toHaveValue("stage-appointment");
  await expect.poll(() => f.controls.at(-1)).toBe("release");
  expect(f.nextCount).toBe(1);
});

test("administrateur : un numéro suffit, sans horaires ni règles régionales", async ({
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
    .getByRole("combobox", { name: "Numéro émetteur", exact: true })
    .selectOption(ca);
  await expect(
    dialog.getByText("Horaires d’appel", { exact: true }),
  ).toHaveCount(0);
  await expect(
    dialog.getByText("Numéros par région", { exact: true }),
  ).toHaveCount(0);
  await dialog
    .getByRole("button", { name: "Enregistrer la téléphonie", exact: true })
    .click();
  await expect(
    dialog.getByText("Réglages téléphoniques enregistrés.", { exact: true }),
  ).toBeVisible();
  expect(f.settings.hours).toEqual([]);
  expect(f.settings.rules).toEqual([]);
  expect(f.settings.enabled).toBe(true);
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
    page.getByRole("combobox", { name: "Numéro émetteur", exact: true }),
  ).toHaveValue(ca);
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
