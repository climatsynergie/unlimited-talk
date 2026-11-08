import { test, expect } from "./qa-observer";
import { readFileSync } from "node:fs";

for (const concurrentChange of [false, true]) {
  test(`API réelle : ${concurrentChange ? "modification concurrente préservée" : "fin d’appel automatique"}, Non intéressé et client suivant`, async ({
    page,
    context,
    baseURL,
  }) => {
    test.skip(
      process.env.QA_REAL_WORKFLOW !== "1",
      "Requires the isolated synthetic provider fixture.",
    );
    const headers = { "X-QA-Control": process.env.QA_FIXTURE_TOKEN! };
    const bootstrap = await page.request.post("/api/__qa/bootstrap", {
      headers,
    });
    expect(bootstrap.status()).toBe(200);
    const fixture = (await bootstrap.json()) as {
      token: string;
      csrf: string;
      actor: string;
      campaign: string;
      contacts: { id: string; name: string; phone: string }[];
      stages: Record<string, string>;
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
    let externalRequests = 0;
    await page.route("**/*", (route) => {
      const host = new URL(route.request().url()).hostname;
      if (host !== "localhost" && host !== "127.0.0.1") {
        externalRequests++;
        return route.abort();
      }
      return route.continue();
    });
    await page.routeWebSocket("**", (socket) => {
      externalRequests++;
      socket.close();
    });
    // Only the media device is replaced. Auth, campaigns, contacts, reservations,
    // dispositions, API errors and database writes use the real application.
    await page.route("**/assets/twilio-*.js", (route) =>
      route.fulfill({
        contentType: "text/javascript",
        body: readFileSync(
          new URL("./fixtures/phone-sdk.js", import.meta.url),
          "utf8",
        ),
      }),
    );
    await page.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = async () =>
        ({ getTracks: () => [{ stop() {} }] }) as unknown as MediaStream;
    });
    async function state() {
      const response = await page.request.get(
        `/api/__qa/state/${fixture.actor}`,
        { headers },
      );
      expect(response.status()).toBe(200);
      return response.json() as Promise<{
        contacts: {
          id: string;
          version: number;
          kind: string;
          non_interested: boolean;
        }[];
        calls: { id: string; contact_id: string; state: string }[];
      }>;
    }
    async function provider(id: string, action: string) {
      const response = await page.request.post(
        `/api/__qa/calls/${id}/${action}`,
        { headers },
      );
      expect(response.status()).toBe(200);
    }
    await page.goto("/poste-appel");
    await page
      .getByRole("combobox", { name: "Campagne d’appel", exact: true })
      .selectOption(fixture.campaign);
    await page
      .getByRole("button", { name: "Démarrer les appels", exact: true })
      .click();
    const current = page.locator(".current-call-sheet");
    await expect(
      current.getByRole("heading", {
        name: fixture.contacts[0].name,
        exact: true,
      }),
    ).toBeVisible();
    const first = (await state()).calls[0];
    await provider(first.id, "authorize");
    await page.evaluate(() => window.phoneProof.call!.emit("accept"));
    await page
      .getByRole("button", { name: "Mettre en pause", exact: true })
      .click();
    await current
      .getByRole("combobox", { name: "Étape du pipeline", exact: true })
      .selectOption(fixture.stages.non_interested);
    await current
      .getByRole("button", { name: "Déplacer vers cette étape", exact: true })
      .click();
    await provider(first.id, "finish");
    await page.evaluate(() => window.phoneProof.call!.emit("disconnect"));
    expect(
      (await state()).contacts.find((c) => c.id === fixture.contacts[0].id)
        ?.version,
    ).toBe(1);
    if (concurrentChange) {
      const changed = await page.request.post(
        `/api/campaigns/${fixture.campaign}/contacts/${fixture.contacts[0].id}/move`,
        {
          headers: {
            Origin: new URL(baseURL!).origin,
            "X-CSRF-Token": fixture.csrf,
          },
          data: {
            request_id: crypto.randomUUID(),
            stage_id: fixture.stages.other,
            version: 1,
          },
        },
      );
      expect(changed.status()).toBe(200);
    }
    const conflict = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/contacts/${fixture.contacts[0].id}/move`) &&
        response.status() === (concurrentChange ? 409 : 200),
    );
    await current
      .getByRole("button", {
        name: "Confirmer pour toutes les campagnes",
        exact: true,
      })
      .click();
    const result = await conflict;
    let accepted = result;
    if (concurrentChange) {
      expect(result.headers()["x-error-code"]).toBe("stale_campaign_contact");
      expect(result.headers()["x-request-id"]).toMatch(/^[a-f0-9]{32}$/);
      await expect(
        current.getByText(/La fiche a été actualisée/),
      ).toBeVisible();
      const confirmation = page.waitForResponse(
        (response) =>
          response.url().endsWith(`/contacts/${fixture.contacts[0].id}/move`) &&
          response.status() === 200,
      );
      await current
        .getByRole("button", {
          name: "Confirmer pour toutes les campagnes",
          exact: true,
        })
        .click();
      accepted = await confirmation;
    }
    await expect(
      current.getByText("Non intéressé — toutes les campagnes", {
        exact: true,
      }),
    ).toBeVisible();
    // A response lost in transit must not apply the restriction twice, including
    // the original version rebased over automatic completion.
    const replay = await page.request.post(accepted.url(), {
      headers: {
        Origin: new URL(baseURL!).origin,
        "X-CSRF-Token": fixture.csrf,
      },
      data: accepted.request().postDataJSON(),
    });
    expect(replay.status()).toBe(200);
    expect((await replay.json()).version).toBe((await accepted.json()).version);
    await expect(
      page.getByRole("button", { name: "Reprendre les appels", exact: true }),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Reprendre les appels", exact: true })
      .click();
    await expect(
      current.getByRole("heading", {
        name: fixture.contacts[1].name,
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.locator(".previous-call-sheet")).toHaveCount(0);
    // A call context must never authorize a disposition on another contact.
    const wrongContext = await page.request.post(
      `/api/campaigns/${fixture.campaign}/contacts/${fixture.contacts[1].id}/move`,
      {
        headers: {
          Origin: new URL(baseURL!).origin,
          "X-CSRF-Token": fixture.csrf,
        },
        data: {
          request_id: crypto.randomUUID(),
          stage_id: fixture.stages.non_interested,
          version: 0,
          source_intent_id: first.id,
        },
      },
    );
    expect(wrongContext.status()).toBe(403);
    expect(wrongContext.headers()["x-error-code"]).toBe(
      "call_context_mismatch",
    );
    const after = await state();
    expect(
      after.contacts.find((c) => c.id === fixture.contacts[0].id)
        ?.non_interested,
    ).toBe(true);
    expect(
      after.contacts.find((c) => c.id === fixture.contacts[1].id)
        ?.non_interested,
    ).toBe(false);
    const second = after.calls.find(
      (c) => c.contact_id === fixture.contacts[1].id,
    )!;
    await provider(second.id, "authorize");
    await page.evaluate(() => window.phoneProof.call!.emit("accept"));
    await page
      .getByRole("button", { name: "Mettre en pause", exact: true })
      .click();
    const marked = page.waitForResponse(
      (r) =>
        r.url().endsWith(`/intents/${second.id}/voicemail`) &&
        r.request().method() === "POST",
    );
    await page
      .getByRole("complementary", { name: "Appel en cours", exact: true })
      .getByRole("button", { name: "Boîte vocale", exact: true })
      .click();
    expect((await marked).status()).toBe(200);
    await provider(second.id, "finish");
    const transferred = page.waitForResponse(
      (r) =>
        r.url().endsWith(`/contacts/${fixture.contacts[1].id}/english`) &&
        r.request().method() === "POST",
    );
    await current
      .getByRole("button", { name: "Parle anglais", exact: true })
      .click();
    expect((await transferred).status()).toBe(200);
    await expect(
      current.getByText(/Transmis à « Contacts anglophones »/),
    ).toBeVisible();
    expect(externalRequests).toBe(0);
  });
}
