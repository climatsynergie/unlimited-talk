import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { spawnSync } from "node:child_process";
import path from "node:path";

declare global {
  interface Window {
    audioProof: {
      streams: MediaStream[];
      requests: MediaStreamConstraints[];
      mode: "normal" | "denied" | "pending";
      resolve?: () => void;
    };
  }
}

// Native Chromium media, with a synthetic device instead of operator hardware.
// No mock can establish the user's physical headset quality.
test.use({
  launchOptions: {
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  },
});

test.beforeEach(async ({ page }) => {
  await page.route("**/api/telephony/calls*", (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.addInitScript(() => {
    window.audioProof = { streams: [], requests: [], mode: "normal" };
    const original = navigator.mediaDevices.getUserMedia.bind(
      navigator.mediaDevices,
    );
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const proof = window.audioProof;
      proof.requests.push(constraints ?? {});
      if (proof.mode === "denied")
        throw new DOMException("", "NotAllowedError");
      if (proof.mode === "pending")
        await new Promise<void>((resolve) => {
          proof.resolve = resolve;
        });
      const stream = await original(constraints);
      proof.streams.push(stream);
      return stream;
    };
  });
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      json: {
        user: {
          id: "00000000-0000-0000-0000-000000000001",
          email: "audio@example.invalid",
          display_name: "Agent audio",
          role: "agent",
          is_active: true,
        },
        mfa_enrollment_required: false,
      },
    }),
  );
});

test("agent : vrai microphone simulé, indicateur, son, arrêt et navigation", async ({
  page,
}) => {
  const errors: string[] = [];
  const commands: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.method() !== "GET") commands.push(request.url());
  });
  const response = await page.goto("/poste-appel");
  expect(response?.headers()["permissions-policy"]).toBe(
    "microphone=(self), camera=()",
  );
  expect(response?.headers()["content-security-policy"]).toContain(
    "connect-src 'self'",
  );
  await expect(
    page.getByRole("heading", { name: "Poste d’appel", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Poste d’appel", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  expect(await page.evaluate(() => window.audioProof.requests.length)).toBe(0);
  await expect(
    page.getByText(
      "Les appels seront disponibles après leur activation pour votre compte.",
      {
        exact: false,
      },
    ),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Tester mon microphone", exact: true })
    .click();
  await expect(
    page.getByRole("status").filter({ hasText: "Microphone actif" }),
  ).toBeVisible();
  await expect(
    page.getByText("Un signal audio a été détecté pendant le test.", {
      exact: true,
    }),
  ).toBeVisible();
  expect(await page.evaluate(() => window.audioProof.requests[0].video)).toBe(
    false,
  );
  await expect
    .poll(async () => page.locator("#microphone-choice option").count())
    .toBeGreaterThan(1);
  await page
    .getByRole("button", { name: "Écouter un son de test", exact: true })
    .click();
  const confirmation = page.getByRole("checkbox", {
    name: "J’ai entendu le son dans mon casque",
    exact: true,
  });
  await expect(confirmation).toBeEnabled();
  await confirmation.check();
  await expect(
    page.getByText("Écoute confirmée.", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Arrêter le microphone", exact: true })
    .click();
  expect(
    await page.evaluate(() =>
      window.audioProof.streams.every((stream) =>
        stream.getTracks().every((track) => track.readyState === "ended"),
      ),
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Tester mon microphone", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Arrêter le microphone", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Mon compte", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Mon compte.", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(() =>
      window.audioProof.streams.every((stream) =>
        stream.getTracks().every((track) => track.readyState === "ended"),
      ),
    ),
  ).toBe(true);
  expect(commands).toEqual([]);
  expect(errors).toEqual([]);
});

test("refus d’autorisation lisible, puis nouvelle tentative", async ({
  page,
}) => {
  await page.goto("/poste-appel");
  await page.evaluate(() => {
    window.audioProof.mode = "denied";
  });
  await page
    .getByRole("button", { name: "Tester mon microphone", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "L’accès au microphone est bloqué",
  );
  expect(await page.evaluate(() => window.audioProof.streams.length)).toBe(0);
  await page.evaluate(() => {
    window.audioProof.mode = "normal";
  });
  await page
    .getByRole("button", { name: "Tester mon microphone", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Arrêter le microphone", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Arrêter le microphone", exact: true })
    .click();
});

test("autorisation tardive après annulation : aucune capture persistante", async ({
  page,
}) => {
  await page.goto("/poste-appel");
  await page.evaluate(() => {
    window.audioProof.mode = "pending";
  });
  await page
    .getByRole("button", { name: "Tester mon microphone", exact: true })
    .click();
  await expect
    .poll(() => page.evaluate(() => Boolean(window.audioProof.resolve)))
    .toBe(true);
  await page
    .getByRole("button", { name: "Annuler le test du micro", exact: true })
    .click();
  await page.evaluate(() => window.audioProof.resolve?.());
  await expect
    .poll(() => page.evaluate(() => window.audioProof.streams.length))
    .toBe(1);
  await expect
    .poll(() =>
      page.evaluate(() =>
        window.audioProof.streams[0]
          .getTracks()
          .every((track) => track.readyState === "ended"),
      ),
    )
    .toBe(true);
  await expect(
    page.getByRole("button", { name: "Tester mon microphone", exact: true }),
  ).toBeVisible();
});

test("arrêt automatique et déconnexion du périphérique", async ({ page }) => {
  await page.goto("/poste-appel");
  await page.clock.install();
  await page
    .getByRole("button", { name: "Tester mon microphone", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Arrêter le microphone", exact: true }),
  ).toBeVisible();
  await page.clock.fastForward(30_100);
  await expect(
    page.getByRole("status").filter({ hasText: "arrêté après 30 secondes" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() =>
      window.audioProof.streams[0]
        .getTracks()
        .every((track) => track.readyState === "ended"),
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Tester mon microphone", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Arrêter le microphone", exact: true }),
  ).toBeVisible();
  await page.evaluate(() => {
    window.audioProof.streams[1]
      .getAudioTracks()[0]
      .dispatchEvent(new Event("ended"));
  });
  await expect(page.getByRole("alert")).toContainText(
    "Le microphone a été déconnecté",
  );
  expect(
    await page.evaluate(() =>
      window.audioProof.streams[1]
        .getTracks()
        .every((track) => track.readyState === "ended"),
    ),
  ).toBe(true);
});

test("écran mobile accessible et accès avec une vraie session d’agent", async ({
  page,
}) => {
  await page.unroute("**/api/auth/me");
  await page.unroute("**/api/telephony/calls*");
  const result = spawnSync(
    "python3",
    [path.resolve("..", "tests/browser-fixtures.py")],
    {
      input: JSON.stringify({ op: "agent" }),
      encoding: "utf8",
      env: process.env,
    },
  );
  expect(result.status).toBe(0);
  const seed = JSON.parse(result.stdout) as { email: string; password: string };
  await page.goto("/poste-appel");
  await expect(
    page.getByRole("heading", { name: "Heureux de vous retrouver." }),
  ).toBeVisible();
  await page.getByLabel("Adresse courriel", { exact: true }).fill(seed.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(seed.password);
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await page.getByRole("link", { name: "Poste d’appel", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Poste d’appel", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Poste d’appel", exact: true }),
  ).toBeVisible();
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
      targets: v.nodes.map((n) => n.target),
    })),
  ).toEqual([]);
  await page
    .getByRole("button", { name: "Tester mon microphone", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Arrêter le microphone", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Se déconnecter", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Heureux de vous retrouver." }),
  ).toBeVisible();
  expect(
    await page.evaluate(() =>
      window.audioProof.streams.every((stream) =>
        stream.getTracks().every((track) => track.readyState === "ended"),
      ),
    ),
  ).toBe(true);
});
