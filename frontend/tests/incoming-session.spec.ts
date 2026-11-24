import { test, expect } from "./qa-observer";
import type { Page, Route } from "@playwright/test";
import { qualificationSchema } from "./fixtures/qualification";
import { disabledDialer } from "./fixtures/dialer-disabled";
const queueId = "00000000-0000-0000-0000-000000000050";
const offerId = "00000000-0000-0000-0000-000000000051";
const registrationId = "00000000-0000-0000-0000-000000000052";
type Proof = {
  disconnected: number;
  destroyed: number;
  created: number;
  registrations: number;
  updatedTokens: number;
  tokenRefreshMs: number;
};
async function setup(page: Page) {
  const fixture = {
    active: false,
    finished: false,
    accepted: false,
    epoch: 1,
    tokenFailures: 0,
    tokenRequests: 0,
    startupHangs: 0,
    unexpected: [] as string[],
    logout: null as null | ((route: Route) => Promise<void>),
  };
  const user = {
    id: "00000000-0000-0000-0000-000000000011",
    role: "agent",
    display_name: "Agent QA",
    email: "qa@example.invalid",
    is_active: true,
  };
  const queue = {
    id: queueId,
    name: "Réception principale",
    phone: "+14165550102",
    timezone: "America/Toronto",
    hours: [],
    is_active: true,
    agents: [],
    routing_active: true,
    version: 1,
  };
  function row() {
    return {
      id: offerId,
      call_id: "call",
      registration_id: registrationId,
      caller_number: "+14165550101",
      called_number: queue.phone,
      queue_name: queue.name,
      state: fixture.finished
        ? "finished"
        : fixture.accepted
          ? "connected"
          : "offered",
      call_state: fixture.finished
        ? "finished"
        : fixture.accepted
          ? "connected"
          : "offered",
    };
  }
  function active() {
    const { id, ...offer } = row();
    return fixture.active && !fixture.finished
      ? { ...offer, offer_id: id, owned_session: fixture.epoch === 1 }
      : null;
  }
  // Unexpected requests fail visibly; no request can reach a real business API.
  await page.route("**/api/**", (route) => {
    fixture.unexpected.push(new URL(route.request().url()).pathname);
    return route.fulfill({
      status: 404,
      json: { detail: "Unexpected isolated test request" },
    });
  });
  await disabledDialer(page);
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => new MediaStream();
  });
  await page.route("**/api/auth/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me")
      return route.fulfill({ json: { user, mfa_enrollment_required: false } });
    if (path === "/api/auth/logout")
      return fixture.logout
        ? fixture.logout(route)
        : route.fulfill({ json: { ok: true } });
    if (path === "/api/auth/password") {
      fixture.epoch++;
      return route.fulfill({
        json: { user: { ...user }, mfa_enrollment_required: false },
      });
    }
    fixture.unexpected.push(path);
    return route.fulfill({
      status: 404,
      json: { detail: "Unexpected auth request" },
    });
  });
  await page.route("**/api/telephony/test/session", (route) =>
    route.fulfill({
      json: {
        enabled: true,
        destination: null,
        max_duration_seconds: 1800,
        active: null,
      },
    }),
  );
  await page.route("**/api/inbound/queues", (route) =>
    route.fulfill({ json: { items: [queue] } }),
  );
  await page.route("**/api/inbound/queues/*/board", (route) =>
    route.fulfill({
      json: {
        queue,
        columns: [
          {
            stage: "pending",
            name: "À traiter",
            count: 0,
            items: [],
            has_more: false,
          },
        ],
      },
    }),
  );
  await page.route("**/api/inbound/reception", (route) =>
    route.fulfill({
      json: {
        enabled: true,
        queues: [queue],
        registration: null,
        active: active(),
      },
    }),
  );
  await page.route("**/api/inbound/reception/register", (route) =>
    route.fulfill({
      status: 201,
      json: { id: registrationId, token: "SYNTHETIC_INCOMING_ONLY" },
    }),
  );
  await page.route(
    `**/api/inbound/reception/${registrationId}/token`,
    (route) => {
      fixture.tokenRequests++;
      return fixture.tokenFailures-- > 0
        ? route.fulfill({
            status: 503,
            json: { detail: "Coupure réseau simulée." },
          })
        : route.fulfill({
            json: { token: "SYNTHETIC_RENEWED_TOKEN", expires_in: 300 },
          });
    },
  );
  await page.route(`**/api/inbound/reception/${registrationId}`, (route) =>
    fixture.epoch === 1
      ? route.fulfill({
          json: {
            available: route.request().postDataJSON().available,
            media_ready: true,
            active: active(),
          },
        })
      : route.fulfill({
          status: 404,
          json: { detail: "Session de réception introuvable." },
        }),
  );
  await page.route(`**/api/inbound/reception/offers/${offerId}`, (route) => {
    if (fixture.epoch !== 1)
      return route.fulfill({
        status: 404,
        json: { detail: "Proposition d’appel introuvable." },
      });
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toEqual({
        registration_id: registrationId,
        accept: true,
      });
      fixture.accepted = true;
    }
    return route.fulfill({ json: row() });
  });
  await page.route("**/assets/twilio-*.js", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: `
    window.incomingSessionProof={disconnected:0,destroyed:0,created:0,registrations:0,updatedTokens:0,tokenRefreshMs:0};
    window.incomingSessionHangRegisters=${fixture.startupHangs};
    export class Device {
      state='unregistered'; handlers=new Map(); audio={setInputDevice:async()=>{},unsetInputDevice:async()=>{}};
      constructor(token,options){window.incomingSessionProof.created++;window.incomingSessionProof.device=this;window.incomingSessionProof.tokenRefreshMs=options.tokenRefreshMs;}
      on(event,callback){this.handlers.set(event,callback);}
      async register(){window.incomingSessionProof.registrations++;if(window.incomingSessionHangRegisters>0){window.incomingSessionHangRegisters--;this.state='registering';return new Promise(()=>{});}this.state='registered';this.handlers.get('registered')?.();}
      updateToken(){window.incomingSessionProof.updatedTokens++;}
      destroy(){window.incomingSessionProof.destroyed++;}
    }
    window.ringIncomingSession=()=>{
      const handlers=new Map();
      const call={customParameters:new Map([['Offer','${offerId}']]),on:(event,callback)=>handlers.set(event,callback),accept:()=>handlers.get('accept')?.(),reject:()=>{},disconnect:()=>{window.incomingSessionProof.disconnected++;handlers.get('disconnect')?.();}};
      window.incomingSessionProof.device.handlers.get('incoming')(call);
    };
  `,
    }),
  );
  return fixture;
}

test("réception : inscription SDK bloquée puis reprise automatique avec un téléphone neuf", async ({
  page,
}) => {
  const f = await setup(page);
  f.startupHangs = 1;
  await page.goto("/appels-entrants");
  await page
    .getByRole("button", { name: "Recevoir les appels", exact: true })
    .click();
  await expect(
    page.getByText("Connexion du téléphone…", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Réception ouverte", { exact: true }),
  ).toBeVisible({ timeout: 20_000 });
  expect(f.tokenRequests).toBe(1);
  expect((await proof(page)).created).toBe(2);
  expect((await proof(page)).destroyed).toBe(1);
  expect(f.unexpected).toEqual([]);
});

test("réception : erreur SDK sans événement de déconnexion puis nouvel appel sans deuxième clic", async ({
  page,
}) => {
  const f = await setup(page);
  await page.goto("/appels-entrants");
  await page
    .getByRole("button", { name: "Recevoir les appels", exact: true })
    .click();
  await expect(
    page.getByText("Réception ouverte", { exact: true }),
  ).toBeVisible();
  expect((await proof(page)).tokenRefreshMs).toBe(60_000);
  await page.evaluate(() => {
    const device = (
      window as unknown as {
        incomingSessionProof: {
          device: {
            state: string;
            handlers: Map<string, (error: { code: number }) => void>;
          };
        };
      }
    ).incomingSessionProof.device;
    // SDK 2.18.5 can emit an error while its public state remains registered.
    device.handlers.get("error")?.({ code: 53000 });
  });
  await expect(
    page.getByText("Reconnexion automatique…", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Recevoir les appels", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Réception ouverte", { exact: true }),
  ).toBeVisible({ timeout: 10_000 });
  expect(f.tokenRequests).toBe(1);
  expect((await proof(page)).registrations).toBe(2);
  expect((await proof(page)).created).toBe(2);
  expect((await proof(page)).destroyed).toBe(1);
  f.active = true;
  await page.evaluate(() =>
    (
      window as unknown as { ringIncomingSession: () => void }
    ).ringIncomingSession(),
  );
  const bar = page.getByRole("complementary", {
    name: "Appel entrant en cours",
    exact: true,
  });
  await bar.getByRole("button", { name: "Répondre", exact: true }).click();
  await expect(bar).toContainText("En conversation");
  expect(f.unexpected).toEqual([]);
});

test("réception : renouvellement après trois indisponibilités sans pause et pause volontaire respectée", async ({
  page,
}) => {
  const f = await setup(page);
  await page.goto("/appels-entrants");
  await page
    .getByRole("button", { name: "Recevoir les appels", exact: true })
    .click();
  await expect(
    page.getByText("Réception ouverte", { exact: true }),
  ).toBeVisible();
  f.tokenFailures = 3;
  await page.evaluate(() => {
    const device = (
      window as unknown as {
        incomingSessionProof: { device: { handlers: Map<string, () => void> } };
      }
    ).incomingSessionProof.device;
    device.handlers.get("tokenWillExpire")?.();
  });
  await expect.poll(() => f.tokenRequests, { timeout: 25_000 }).toBe(4);
  await expect(
    page.getByText("Réception ouverte", { exact: true }),
  ).toBeVisible();
  expect((await proof(page)).updatedTokens).toBe(1);
  await page
    .getByRole("button", { name: "Mettre la réception en pause", exact: true })
    .click();
  await expect(
    page.getByText("Réception en pause", { exact: true }),
  ).toBeVisible();
  const before = await proof(page);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect(
    page.getByRole("button", { name: "Recevoir les appels", exact: true }),
  ).toBeVisible();
  expect(await proof(page)).toEqual(before);
  expect(f.unexpected).toEqual([]);
});
async function proof(page: Page) {
  return page.evaluate(
    () =>
      (window as unknown as { incomingSessionProof: Proof })
        .incomingSessionProof,
  );
}
async function connect(page: Page, fixture: Awaited<ReturnType<typeof setup>>) {
  await page.goto("/appels-entrants");
  await page
    .getByRole("button", { name: "Recevoir les appels", exact: true })
    .click();
  await expect(
    page.getByText("Réception ouverte", { exact: true }),
  ).toBeVisible();
  fixture.active = true;
  await page.evaluate(() =>
    (
      window as unknown as { ringIncomingSession: () => void }
    ).ringIncomingSession(),
  );
  const bar = page.getByRole("complementary", {
    name: "Appel entrant en cours",
    exact: true,
  });
  await bar.getByRole("button", { name: "Répondre", exact: true }).click();
  await expect(bar).toContainText("En conversation");
  return bar;
}
test("déconnexion entrante : microphone fermé avant la réponse, échec récupéré sans reconnexion automatique", async ({
  page,
}) => {
  const fixture = await setup(page);
  await connect(page, fixture);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  fixture.logout = async (route) => {
    await gate;
    await route.fulfill({
      status: 500,
      json: { detail: "Échec de déconnexion simulé." },
    });
  };
  const before = await proof(page);
  try {
    await page
      .getByRole("button", { name: "Se déconnecter", exact: true })
      .click();
    await expect
      .poll(async () => (await proof(page)).disconnected, { timeout: 1500 })
      .toBeGreaterThan(before.disconnected);
    await expect
      .poll(async () => (await proof(page)).destroyed)
      .toBeGreaterThan(before.destroyed);
    release();
    await expect(page.getByRole("alert")).toContainText(
      "Échec de déconnexion simulé.",
    );
    await expect(
      page.getByText("Réception en pause", { exact: true }),
    ).toBeVisible();
    expect((await proof(page)).created).toBe(before.created);
    fixture.finished = true;
    const bar = page.getByRole("complementary", {
      name: "Appel entrant en cours",
      exact: true,
    });
    await bar
      .getByRole("button", { name: "Vérifier l’appel", exact: true })
      .click();
    await expect(bar).toHaveCount(0);
    expect(fixture.unexpected).toEqual([]);
  } finally {
    release();
  }
});
test("changement de mot de passe : ancienne réception détruite même lorsque le compte reste le même", async ({
  page,
}) => {
  const fixture = await setup(page);
  await connect(page, fixture);
  const before = await proof(page);
  await page.getByRole("link", { name: "Mon compte", exact: true }).click();
  await page
    .getByLabel("Mot de passe actuel", { exact: true })
    .fill("phrase-actuelle-de-test");
  await page
    .getByLabel("Nouveau mot de passe", { exact: true })
    .fill("nouvelle-phrase-de-test");
  await page
    .getByLabel("Confirmer le mot de passe", { exact: true })
    .fill("nouvelle-phrase-de-test");
  await page
    .getByRole("button", { name: "Enregistrer le mot de passe", exact: true })
    .click();
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "Votre mot de passe a été modifié." }),
  ).toBeVisible();
  await expect
    .poll(async () => (await proof(page)).disconnected, { timeout: 1500 })
    .toBeGreaterThan(before.disconnected);
  await expect
    .poll(async () => (await proof(page)).destroyed)
    .toBeGreaterThan(before.destroyed);
  expect((await proof(page)).created).toBe(before.created);
  expect(fixture.unexpected).toEqual([]);
});

test("appel entrant actif : ouvrir et fermer la qualification conserve le média", async ({
  page,
}) => {
  const f = await setup(page);
  await page.route("**/api/inbound/calls/*/booking-options?*", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: queueId,
            name: "Canada",
            timezone: "America/Toronto",
            already_enrolled: true,
          },
        ],
        has_more: false,
      },
    }),
  );
  await page.route("**/api/inbound/calls/*/booking-context", (route) =>
    route.fulfill({
      json: {
        campaign_id: queueId,
        contact_id: offerId,
        membership_version: 0,
        timezone: "America/Toronto",
        qualification_schema: qualificationSchema,
        qualification: null,
        booker_name: "Agent QA",
      },
    }),
  );
  const bar = await connect(page, f);
  const before = await proof(page);
  await bar
    .getByRole("button", {
      name: "Fiche client / Prendre rendez-vous",
      exact: true,
    })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("group", { name: "Qualification du client", exact: true }),
  ).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Prendre rendez-vous", exact: true }),
  ).toBeEnabled();
  await dialog
    .getByRole("button", { name: "Fermer la fenêtre", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(bar).toContainText("En conversation");
  expect(await proof(page)).toEqual(before);
  expect(f.unexpected).toEqual([]);
});
