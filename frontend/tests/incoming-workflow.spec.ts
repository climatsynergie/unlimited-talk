import { test, expect } from "./qa-observer";
import { join } from "node:path";

type MediaProof = { created: number; disconnected: number };
type IncomingWindow = Window & {
  incomingWorkflowProof: MediaProof;
  ringIncomingWorkflow: (offer: string) => void;
};
type DurableState = {
  calls: {
    id: string;
    state: string;
    outcome: string | null;
    agent_id: string | null;
    followup_id: string | null;
  }[];
  offers: {
    id: string;
    state: string;
    accepted_at: string | null;
    connected_at: string | null;
    terminal_at: string | null;
  }[];
  followups: { id: string; stage: string; caller_number: string }[];
};

test("API réelle : recevoir, répondre, naviguer, raccrocher et retrouver un appel manqué", async ({
  page,
  context,
  baseURL,
}) => {
  test.skip(
    process.env.QA_REAL_INCOMING_WORKFLOW !== "1",
    "Requires isolated synthetic incoming provider fixture.",
  );
  const headers = { "X-QA-Control": process.env.QA_FIXTURE_TOKEN! };
  const bootstrap = await page.request.post("/api/__qa/incoming/bootstrap", {
    headers,
  });
  expect(bootstrap.status()).toBe(200);
  const fixture = (await bootstrap.json()) as {
    token: string;
    csrf: string;
    actor: string;
    queue: string;
    queue_name: string;
  };
  await context.addCookies([
    {
      name: "__Host-ut_session",
      value: fixture.token,
      url: baseURL!,
      httpOnly: true,
      secure: true,
      sameSite: "Strict",
    },
    {
      name: "__Host-ut_csrf",
      value: fixture.csrf,
      url: baseURL!,
      httpOnly: false,
      secure: true,
      sameSite: "Strict",
    },
  ]);
  const errors: string[] = [];
  const external: string[] = [];
  page.on("pageerror", (error) => errors.push(error.name));
  await page.route("**/*", (route) => {
    const host = new URL(route.request().url()).hostname;
    if (host !== "localhost" && host !== "127.0.0.1") {
      external.push(host);
      return route.abort();
    }
    return route.continue();
  });
  await page.routeWebSocket("**", (socket) => {
    external.push("websocket");
    socket.close();
  });
  // Replace only Twilio's media/signalling device. All business API responses,
  // cookies, registration, authorization and database transitions stay real.
  await page.route("**/assets/twilio-*.js", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: `
    window.incomingWorkflowProof={created:0,disconnected:0};
    export class Device {
      state='unregistered'; handlers=new Map(); audio={setInputDevice:async()=>{},unsetInputDevice:async()=>{}};
      constructor(){window.incomingWorkflowProof.created++;window.incomingWorkflowDevice=this;}
      on(event,callback){this.handlers.set(event,callback);}
      async register(){this.state='registered';this.handlers.get('registered')?.();}
      updateToken(){}
      destroy(){}
    }
    window.ringIncomingWorkflow=(offer)=>{
      const handlers=new Map();
      const call={customParameters:new Map([['Offer',offer]]),on:(event,callback)=>handlers.set(event,callback),accept:()=>handlers.get('accept')?.(),reject:()=>{},disconnect:()=>{window.incomingWorkflowProof.disconnected++;handlers.get('disconnect')?.();}};
      window.incomingWorkflowDevice.handlers.get('incoming')(call);
    };
  `,
    }),
  );
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () =>
      ({ getTracks: () => [{ stop() {} }] }) as unknown as MediaStream;
  });
  async function state(): Promise<DurableState> {
    const response = await page.request.get(
      `/api/__qa/incoming/${fixture.actor}/state`,
      { headers },
    );
    expect(response.status()).toBe(200);
    return response.json();
  }
  async function control(path: string) {
    const response = await page.request.post(
      `/api/__qa/incoming/${fixture.actor}/${path}`,
      { headers },
    );
    expect(response.status()).toBe(200);
    return response.json();
  }
  await page.goto("/appels-entrants");
  await expect(
    page.getByRole("combobox", { name: "File de réception", exact: true }),
  ).toHaveValue(fixture.queue);
  const registered = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/inbound/reception/register") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Recevoir les appels", exact: true })
    .click();
  expect((await registered).status()).toBe(201);
  await expect(
    page.getByText("Réception ouverte", { exact: true }),
  ).toBeVisible();
  const ringing = (await control("ring")) as {
    call_id: string;
    offer_id: string;
    caller: string;
  };
  await page.evaluate(
    (offer) => (window as IncomingWindow).ringIncomingWorkflow(offer),
    ringing.offer_id,
  );
  const bar = page.getByRole("complementary", {
    name: "Appel entrant en cours",
    exact: true,
  });
  await expect(bar).toContainText(ringing.caller);
  await expect(bar).toContainText(fixture.queue_name);
  const chosen = page.waitForResponse(
    (response) =>
      response
        .url()
        .endsWith(`/api/inbound/reception/offers/${ringing.offer_id}`) &&
      response.request().method() === "POST",
  );
  await bar.getByRole("button", { name: "Répondre", exact: true }).click();
  expect((await chosen).status()).toBe(200);
  await control(`calls/${ringing.call_id}/answer`);
  await expect(bar).toContainText("En conversation");
  const connected = await state();
  expect(connected.calls[0].state).toBe("connected");
  expect(connected.calls[0].agent_id).toBe(fixture.actor);
  expect(connected.offers[0].accepted_at).not.toBeNull();
  expect(connected.offers[0].connected_at).not.toBeNull();
  const beforeNavigation = await page.evaluate(
    () => (window as IncomingWindow).incomingWorkflowProof.created,
  );
  await page.getByRole("link", { name: "Calendrier", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Calendrier", exact: true }),
  ).toBeVisible();
  await expect(bar).toContainText("En conversation");
  expect(
    await page.evaluate(
      () => (window as IncomingWindow).incomingWorkflowProof.created,
    ),
  ).toBe(beforeNavigation);
  const evidence = process.env.QA_INCOMING_EVIDENCE_DIR;
  if (evidence)
    await page.screenshot({
      path: join(evidence, "incoming-browser-connected.png"),
    });
  await bar.getByRole("button", { name: "Raccrocher", exact: true }).click();
  await expect
    .poll(() =>
      page.evaluate(
        () => (window as IncomingWindow).incomingWorkflowProof.disconnected,
      ),
    )
    .toBe(1);
  // The browser hangup alone cannot free a real provider reservation.
  expect((await state()).calls[0].state).toBe("connected");
  await control(`calls/${ringing.call_id}/finish`);
  await expect(bar).toHaveCount(0);
  expect((await state()).calls[0]).toMatchObject({
    state: "finished",
    outcome: "answered",
  });
  await page
    .getByRole("link", { name: "Appels entrants", exact: true })
    .click();
  const paused = page.waitForResponse(
    (response) =>
      /\/api\/inbound\/reception\/[a-f0-9-]{36}$/.test(response.url()) &&
      response.request().method() === "PATCH" &&
      response.request().postDataJSON().available === false,
  );
  await page
    .getByRole("button", { name: "Mettre la réception en pause", exact: true })
    .click();
  expect((await paused).status()).toBe(200);
  await expect(
    page.getByText("Réception en pause", { exact: true }),
  ).toBeVisible();
  const missed = (await control("missed")) as {
    followup_id: string;
    caller: string;
  };
  await page.getByRole("button", { name: "Actualiser", exact: true }).click();
  const followups = page.getByRole("region", {
    name: "Liste des suivis",
    exact: true,
  });
  await expect(
    followups.getByText(missed.caller, { exact: true }),
  ).toBeVisible();
  expect((await state()).followups).toEqual([
    { id: missed.followup_id, stage: "pending", caller_number: missed.caller },
  ]);
  if (evidence)
    await page.screenshot({
      path: join(evidence, "incoming-browser-missed.png"),
    });
  expect(external).toEqual([]);
  expect(errors).toEqual([]);
});
