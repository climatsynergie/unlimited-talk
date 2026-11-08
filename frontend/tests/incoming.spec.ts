import { test, expect } from "./qa-observer";
import { disabledDialer } from "./fixtures/dialer-disabled";
const queue = "00000000-0000-0000-0000-000000000050";
const offer = "00000000-0000-0000-0000-000000000051";
const reg = "00000000-0000-0000-0000-000000000052";
test("réception globale : réponse explicite, navigation, pause sans couper et confirmation serveur", async ({
  page,
  context,
}) => {
  await disabledDialer(page);
  await page.route("**/api/telephony/test/session", (r) =>
    r.fulfill({
      json: {
        enabled: true,
        destination: null,
        max_duration_seconds: 1800,
        active: null,
      },
    }),
  );
  await context.grantPermissions(["microphone"]);
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => new MediaStream();
  });
  await page.route("**/api/auth/me", (r) =>
    r.fulfill({
      json: {
        user: {
          id: "00000000-0000-0000-0000-000000000011",
          role: "agent",
          display_name: "Agent QA",
          email: "qa@example.invalid",
          is_active: true,
        },
        mfa_enrollment_required: false,
      },
    }),
  );
  const q = {
    id: queue,
    name: "Réception principale",
    phone: "+14165550102",
    timezone: "America/Toronto",
    hours: [],
    is_active: true,
    agents: [],
    routing_active: true,
    version: 1,
  };
  await page.route("**/api/inbound/queues", (r) =>
    r.fulfill({ json: { items: [q] } }),
  );
  await page.route("**/api/inbound/queues/*/board", (r) =>
    r.fulfill({
      json: {
        queue: q,
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
  let active = false,
    finished = false,
    accepted = 0;
  const row = () => ({
    id: offer,
    call_id: "call",
    registration_id: reg,
    caller_number: "+14165550101",
    called_number: q.phone,
    queue_name: q.name,
    state: finished ? "finished" : accepted ? "connected" : "offered",
    call_state: finished ? "finished" : accepted ? "connected" : "offered",
  });
  await page.route("**/api/inbound/reception", (r) =>
    r.fulfill({
      json: { enabled: true, queues: [q], registration: null, active: null },
    }),
  );
  await page.route("**/api/inbound/reception/register", (r) =>
    r.fulfill({
      status: 201,
      json: { id: reg, token: "PRIVATE_INCOMING_TOKEN" },
    }),
  );
  await page.route(`**/api/inbound/reception/${reg}`, (r) =>
    r.fulfill({
      json: {
        available: r.request().postDataJSON().available,
        media_ready: true,
        active: active && !finished ? { ...row(), offer_id: offer } : null,
      },
    }),
  );
  await page.route(`**/api/inbound/reception/offers/${offer}`, (r) => {
    if (r.request().method() === "POST") {
      expect(r.request().postDataJSON()).toEqual({
        registration_id: reg,
        accept: true,
      });
      accepted++;
    }
    return r.fulfill({ json: row() });
  });
  await page.route("**/assets/twilio-*.js", (r) =>
    r.fulfill({
      contentType: "text/javascript",
      body: `
  window.incomingProof={disconnected:0,destroyed:0};
  export class Device {
   state='unregistered'; handlers=new Map(); audio={setInputDevice:async()=>{},unsetInputDevice:async()=>{}};
   constructor(){window.incomingProof.device=this;}
   on(e,f){this.handlers.set(e,f);}
   async register(){this.state='registered';this.handlers.get('registered')?.();}
   updateToken(){}
   destroy(){window.incomingProof.destroyed++;}
  }
  window.ringIncoming=()=>{const h=new Map(); const call={customParameters:new Map([['Offer','${offer}']]),on:(e,f)=>h.set(e,f),accept:()=>h.get('accept')?.(),reject:()=>{},disconnect:()=>{window.incomingProof.disconnected++;h.get('disconnect')?.();}};window.incomingProof.device.handlers.get('incoming')(call);};
 `,
    }),
  );
  await page.goto("/appels-entrants");
  await page
    .getByRole("button", { name: "Recevoir les appels", exact: true })
    .click();
  await expect(
    page.getByText("Réception ouverte", { exact: true }),
  ).toBeVisible();
  active = true;
  await page.evaluate(() =>
    (window as unknown as { ringIncoming: () => void }).ringIncoming(),
  );
  const bar = page.getByRole("complementary", {
    name: "Appel entrant en cours",
    exact: true,
  });
  await expect(bar).toContainText("+14165550101");
  await bar.getByRole("button", { name: "Répondre", exact: true }).click();
  await expect(bar).toContainText("En conversation");
  expect(accepted).toBe(1);
  await page
    .getByRole("button", { name: "Mettre la réception en pause", exact: true })
    .click();
  await expect(bar).toContainText("En conversation");
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { incomingProof: { disconnected: number } })
          .incomingProof.disconnected,
    ),
  ).toBe(0);
  await page.route("**/api/telephony/calls*", (r) =>
    r.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.getByRole("link", { name: "Conversations", exact: true }).click();
  await expect(bar).toContainText("En conversation");
  await bar.getByRole("button", { name: "Raccrocher", exact: true }).click();
  await expect(bar).toContainText("Vérification de l’appel");
  finished = true;
  await bar
    .getByRole("button", { name: "Vérifier l’appel", exact: true })
    .click();
  await expect(bar).toHaveCount(0);
  expect(
    await page.evaluate(
      () => JSON.stringify(sessionStorage) + JSON.stringify(localStorage),
    ),
  ).not.toContain("PRIVATE_INCOMING_TOKEN");
});
