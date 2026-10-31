import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { silentWav } from "./fixtures/audio";

declare global {
  interface Window {
    phoneProof: {
      created: number;
      destroyed: number;
      connections: Record<string, string>[];
      disconnected: number;
      mode: string;
      call?: { emit: (event: string) => void };
      resolve?: () => void;
      error?: () => void;
    };
  }
}
const userId = "00000000-0000-0000-0000-000000000011";
async function setup(page: Page, enabled = true) {
  const state = {
    enabled,
    reservations: 0,
    sdkLoads: 0,
    rows: new Map<
      string,
      {
        id: string;
        state: string;
        outcome: string | null;
        owned_session: boolean;
      }
    >(),
    reserveGate: null as Promise<void> | null,
  };
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      json: {
        user: {
          id: userId,
          email: "phone@example.invalid",
          display_name: "Admin téléphone",
          role: "admin",
          is_active: true,
        },
        mfa_enrollment_required: false,
      },
    }),
  );
  await page.route("**/api/telephony/calls*", (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.route("**/api/telephony/test/session", (route) =>
    route.fulfill({
      json: {
        enabled: state.enabled,
        destination: "+14165550101",
        max_duration_seconds: 180,
        active:
          [...state.rows.values()].find(
            (row) => !["finished", "cancelled"].includes(row.state),
          ) || null,
      },
    }),
  );
  await page.route("**/api/telephony/test/intents", async (route) => {
    const body = route.request().postDataJSON();
    expect(Object.keys(body)).toEqual(["id"]);
    expect(body.id).toMatch(/^[a-f0-9-]{36}$/);
    state.reservations += 1;
    const intent = {
      id: body.id,
      state: "reserved",
      outcome: null,
      owned_session: true,
    };
    state.rows.set(body.id, intent);
    if (state.reserveGate) await state.reserveGate;
    await route.fulfill({
      status: 201,
      json: { intent, token: "synthetic-sdk-token" },
    });
  });
  await page.route(/\/api\/telephony\/test\/intents\/[a-f0-9-]+$/, (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop()!;
    return route.fulfill({ json: { intent: state.rows.get(id) } });
  });
  await page.route(
    /\/api\/telephony\/test\/intents\/[a-f0-9-]+\/cancel$/,
    (route) => {
      const id = new URL(route.request().url()).pathname.split("/").at(-2)!;
      const row = state.rows.get(id)!;
      if (row.state !== "reserved")
        return route.fulfill({
          status: 409,
          json: { detail: "Appel déjà autorisé." },
        });
      row.state = "cancelled";
      return route.fulfill({ json: row });
    },
  );
  await page.route("**/assets/twilio-*.js", async (route) => {
    state.sdkLoads += 1;
    await route.fulfill({
      contentType: "text/javascript",
      body: readFileSync(
        new URL("./fixtures/phone-sdk.js", import.meta.url),
        "utf8",
      ),
    });
  });
  return state;
}

test("appel désactivé : commandes visibles, aucun SDK chargé ni jeton demandé", async ({
  page,
}) => {
  const state = await setup(page, false);
  await page.goto("/poste-appel");
  await expect(
    page.getByRole("button", { name: "Appeler", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("Les appels ne sont pas encore activés.", { exact: true }),
  ).toBeVisible();
  expect(state.sdkLoads).toBe(0);
  expect(state.reservations).toBe(0);
  await page.setViewportSize({ width: 390, height: 844 });
  const report = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(report.violations.map((v) => v.id)).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("conversation persistante pendant la navigation et confirmation serveur du raccrochage", async ({
  page,
}) => {
  const state = await setup(page);
  await page.goto("/poste-appel");
  await page.getByRole("button", { name: "Appeler", exact: true }).click();
  await expect
    .poll(() => page.evaluate(() => window.phoneProof?.connections.length))
    .toBe(1);
  const id = [...state.rows.keys()][0];
  expect(
    await page.evaluate(() => Object.keys(window.phoneProof.connections[0])),
  ).toEqual(["Intent"]);
  state.rows.get(id)!.state = "answered";
  await page.evaluate(() => {
    window.phoneProof.call!.emit("ringing");
    window.phoneProof.call!.emit("accept");
  });
  await expect(
    page.getByRole("complementary", { name: "Appel en cours" }),
  ).toContainText("En conversation");
  await page.getByRole("link", { name: "Mon compte", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Raccrocher", exact: true }),
  ).toBeVisible();
  expect(state.reservations).toBe(1);
  expect(state.sdkLoads).toBe(1);
  expect(await page.evaluate(() => window.phoneProof.disconnected)).toBe(0);
  await page.evaluate(() =>
    window.scrollTo(0, document.documentElement.scrollHeight),
  );
  const box = await page
    .getByRole("button", { name: "Raccrocher", exact: true })
    .boundingBox();
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height).toBeLessThanOrEqual(
    await page.evaluate(() => innerHeight),
  );
  await page.getByRole("button", { name: "Raccrocher", exact: true }).click();
  await expect
    .poll(() => page.evaluate(() => window.phoneProof.disconnected))
    .toBe(1);
  await page.getByRole("link", { name: "Poste d’appel", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Appeler", exact: true }),
  ).toBeDisabled();
  state.rows.get(id)!.state = "finished";
  state.rows.get(id)!.outcome = "completed";
  await page
    .getByRole("button", { name: "Actualiser le téléphone", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Appeler", exact: true }),
  ).toBeEnabled();
  await expect(page.getByText("Appel terminé.", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
  ).toBe(0);
  await expect(page.locator("body")).not.toContainText("synthetic-sdk-token");
});

test("rechargement : réservation restaurée, aucune relance automatique", async ({
  page,
}) => {
  const state = await setup(page);
  const id = crypto.randomUUID();
  state.rows.set(id, {
    id,
    state: "answered",
    outcome: null,
    owned_session: false,
  });
  await page.goto("/poste-appel");
  await expect(
    page.getByRole("button", { name: "Appeler", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("Une réservation est conservée.", { exact: false }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Vérifier l’appel", exact: true }),
  ).toBeVisible();
  expect(state.sdkLoads).toBe(0);
  expect(state.reservations).toBe(0);
  await expect(
    page.getByRole("button", { name: "Raccrocher", exact: true }),
  ).toHaveCount(0);
});

test("raccrochage pendant connect : le média tardif est fermé sans nouvel appel", async ({
  page,
}) => {
  const state = await setup(page);
  await page.addInitScript(() => {
    window.phoneProof = {
      created: 0,
      destroyed: 0,
      connections: [],
      disconnected: 0,
      mode: "pending",
    };
  });
  await page.goto("/poste-appel");
  await page.getByRole("button", { name: "Appeler", exact: true }).click();
  await expect
    .poll(() => page.evaluate(() => window.phoneProof.connections.length))
    .toBe(1);
  state.rows.values().next().value!.state = "authorized";
  await page.getByRole("button", { name: "Raccrocher", exact: true }).click();
  await page.evaluate(() => window.phoneProof.resolve!());
  await expect
    .poll(() => page.evaluate(() => window.phoneProof.disconnected))
    .toBe(1);
  await expect(
    page.getByRole("button", { name: "Appeler", exact: true }),
  ).toBeDisabled();
  expect(state.reservations).toBe(1);
});

test("déconnexion pendant la réservation : aucune activation tardive du SDK", async ({
  page,
}) => {
  const state = await setup(page);
  let resolve!: () => void;
  state.reserveGate = new Promise<void>((done) => {
    resolve = done;
  });
  await page.route("**/api/auth/logout", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.goto("/poste-appel");
  await page.getByRole("button", { name: "Appeler", exact: true }).click();
  await expect.poll(() => state.reservations).toBe(1);
  await page
    .getByRole("button", { name: "Se déconnecter", exact: true })
    .click();
  resolve();
  await expect(
    page.getByRole("heading", {
      name: "Heureux de vous retrouver.",
      exact: true,
    }),
  ).toBeVisible();
  expect(state.sdkLoads).toBe(0);
});

test("la lecture d’une archive est arrêtée avant de connecter l’appel", async ({
  page,
}) => {
  await setup(page);
  const sid = "RE" + "1".repeat(32),
    audio = `/api/telephony/recordings/${sid}/audio`;
  await page.route("**/api/telephony/calls*", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: userId,
            created_at: "2026-10-31T15:00:00Z",
            actor_name: "Admin téléphone",
            destination: "+14165550101",
            state: "finished",
            outcome: "completed",
            recordings: [
              { sid, state: "archived", duration: 1, playback_path: audio },
            ],
          },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.route("**" + audio, (route) =>
    route.fulfill({ contentType: "audio/wav", body: silentWav() }),
  );
  await page.goto("/poste-appel");
  const player = await page.locator("audio").elementHandle();
  await player!.evaluate((node: HTMLAudioElement) => {
    node.loop = true;
    return node.play();
  });
  await page.getByRole("button", { name: "Appeler", exact: true }).click();
  await expect(page.locator("audio")).toHaveCount(0);
  expect(
    await player!.evaluate(
      (node: HTMLAudioElement) =>
        node.paused && node.getAttribute("src") === null,
    ),
  ).toBe(true);
  await expect
    .poll(() => page.evaluate(() => window.phoneProof?.connections.length))
    .toBe(1);
});
