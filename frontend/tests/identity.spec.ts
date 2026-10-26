import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { spawnSync } from "node:child_process";
import { mkdir } from "node:fs/promises";
import path from "node:path";

function fixture<T>(payload: object): T {
  const result = spawnSync(
    "python3",
    [path.resolve("..", "tests/browser-fixtures.py")],
    { input: JSON.stringify(payload), encoding: "utf8", env: process.env },
  );
  if (result.status !== 0) throw new Error("Synthetic browser fixture failed");
  return JSON.parse(result.stdout) as T;
}
type Seed = {
  email: string;
  password: string;
  factor: string;
  codes: string[];
};
async function login(page: Page, email: string, password: string, factor = "") {
  await page.goto("/connexion");
  await page.getByLabel("Adresse courriel", { exact: true }).fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(password);
  await page
    .getByLabel("Code d’authentification ou de récupération", { exact: true })
    .fill(factor);
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
}
async function accessible(page: Page) {
  const report = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    report.violations.map((item) => ({
      id: item.id,
      targets: item.nodes.map((node) => node.target),
    })),
  ).toEqual([]);
}
async function screenshot(page: Page, name: string) {
  if (!process.env.UI_SCREENSHOTS_DIR) return;
  await mkdir(process.env.UI_SCREENSHOTS_DIR, { recursive: true, mode: 0o700 });
  await page.screenshot({
    path: path.join(process.env.UI_SCREENSHOTS_DIR, name),
    fullPage: true,
  });
}
async function invite(page: Page, email: string, name: string, role = "agent") {
  await page
    .getByRole("button", { name: "Inviter un membre", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Nom complet", { exact: true }).fill(name);
  await dialog.getByLabel("Adresse courriel", { exact: true }).fill(email);
  await dialog.getByLabel("Rôle", { exact: true }).selectOption(role);
  await dialog
    .getByRole("button", { name: "Créer l’invitation", exact: true })
    .click();
  await expect(dialog.getByLabel("Lien privé")).toBeVisible();
  const link = await dialog.getByLabel("Lien privé").inputValue();
  expect(new URL(link).search).toBe("");
  expect(Boolean(new URL(link).hash)).toBe(true);
  await dialog.getByRole("button", { name: "Fermer", exact: true }).click();
  return link;
}
async function accept(page: Page, link: string, password: string) {
  await page.goto(link);
  await expect(
    page.getByRole("heading", { name: "Bienvenue dans l’équipe." }),
  ).toBeVisible();
  await expect.poll(() => page.evaluate(() => location.hash)).toBe("");
  await page.getByLabel("Nouveau mot de passe", { exact: true }).fill(password);
  await page
    .getByLabel("Confirmer le mot de passe", { exact: true })
    .fill(password);
  await page
    .getByRole("button", { name: "Accepter l’invitation", exact: true })
    .click();
}

test("connexion, accessibilité, sécurité des routes et écran mobile", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const response = await page.goto("/connexion");
  expect(response?.headers()["content-security-policy"]).toContain(
    "script-src 'self'",
  );
  expect(response?.headers()["content-security-policy"]).not.toContain(
    "unsafe-inline",
  );
  await expect(
    page.getByRole("heading", { name: "Heureux de vous retrouver." }),
  ).toBeVisible();
  await expect(page.getByText("PRÉPRODUCTION", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  const validation = await page
    .getByLabel("Adresse courriel", { exact: true })
    .evaluate((input: HTMLInputElement) => input.validationMessage);
  expect(validation).toBe("Veuillez renseigner ce champ.");
  await accessible(page);
  await screenshot(page, "connexion-desktop.png");
  const unknown = await page.request.get("/api/not-a-real-route");
  expect(unknown.status()).toBe(404);
  expect(unknown.headers()["content-type"]).toContain("application/json");
  const asset = await page.locator("script[src]").getAttribute("src");
  expect(asset?.startsWith("/assets/")).toBe(true);
  const resource = await page.request.get(asset!);
  expect(resource.status()).toBe(200);
  expect(resource.headers()["cache-control"]).toContain("immutable");
  await page.getByRole("button", { name: "Mot de passe oublié ?" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Votre administrateur" }),
  ).toContainText("Votre administrateur");
  await page.setViewportSize({ width: 390, height: 844 });
  await accessible(page);
  await screenshot(page, "connexion-mobile.png");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.goto("/invitation");
  await expect(page.getByRole("alert")).toContainText("Ce lien est incomplet");
  expect(errors).toEqual([]);
});

test("admin invite un agent, réinitialise son mot de passe et révoque son accès", async ({
  page,
  browser,
}) => {
  const seed = fixture<Seed>({ op: "seed" });
  await login(page, seed.email, seed.password, seed.factor);
  await expect(
    page.getByRole("heading", { name: /Les bonnes personnes/ }),
  ).toBeVisible();
  await accessible(page);
  await screenshot(page, "administration-desktop.png");
  const cookie = (await page.context().cookies()).find(
    (value) => value.name === "__Host-ut_session",
  );
  expect(
    Boolean(cookie?.secure && cookie.httpOnly && cookie.sameSite === "Strict"),
  ).toBe(true);
  const email = `agent-ui-${Date.now()}@example.invalid`;
  const password = "Agent2026!ab";
  const link = await invite(page, email, "Agent navigateur");
  const context = await browser.newContext({
    baseURL: process.env.UI_TEST_URL,
    ignoreHTTPSErrors: true,
  });
  try {
    const agent = await context.newPage();
    const urls: string[] = [];
    agent.on("request", (request) => urls.push(request.url()));
    await accept(agent, link, password);
    await expect(
      agent.getByRole("heading", { name: "Bonjour, Agent." }),
    ).toBeVisible();
    expect((await context.request.get("/api/admin/users")).status()).toBe(403);
    expect(
      await agent
        .getByRole("link", { name: "Utilisateurs", exact: true })
        .count(),
    ).toBe(0);
    const token = new URLSearchParams(new URL(link).hash.slice(1)).get(
      "token",
    )!;
    expect(urls.some((url) => url.includes(token))).toBe(false);
    expect(
      await agent.evaluate(() => localStorage.length + sessionStorage.length),
    ).toBe(0);
    await agent.reload();
    await expect(
      agent.getByRole("heading", { name: "Bonjour, Agent." }),
    ).toBeVisible();
    await agent.setViewportSize({ width: 390, height: 844 });
    await accessible(agent);
    expect(
      await agent.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await agent.getByRole("link", { name: "Mon compte", exact: true }).click();
    await expect(
      agent.getByRole("heading", { name: "Mon compte.", exact: true }),
    ).toBeVisible();
    await agent
      .getByLabel("Mot de passe actuel", { exact: true })
      .fill("Un mot de passe incorrect");
    const changed = "Autre2026!ab";
    await agent
      .getByLabel("Nouveau mot de passe", { exact: true })
      .fill(changed);
    await agent
      .getByLabel("Confirmer le mot de passe", { exact: true })
      .fill(changed);
    await agent
      .getByRole("button", { name: "Enregistrer le mot de passe", exact: true })
      .click();
    await expect(agent.getByRole("alert")).toContainText(
      "Identifiants invalides",
    );
    await agent
      .getByLabel("Mot de passe actuel", { exact: true })
      .fill(password);
    await agent
      .getByRole("button", { name: "Enregistrer le mot de passe", exact: true })
      .click();
    await expect(agent.getByRole("status")).toContainText(
      "Votre mot de passe a été modifié",
    );
    await page.getByRole("link", { name: "Utilisateurs", exact: true }).click();
    await page.getByLabel("Rechercher un utilisateur").fill(email);
    await page.getByRole("button", { name: "Rechercher", exact: true }).click();
    const row = page.getByRole("row").filter({ hasText: email });
    await row.locator("summary").click();
    await row
      .getByRole("button", {
        name: "Réinitialiser le mot de passe",
        exact: true,
      })
      .click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Créer le lien privé", exact: true })
      .click();
    const resetLink = await page
      .getByRole("dialog")
      .getByLabel("Lien privé")
      .inputValue();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Fermer", exact: true })
      .click();
    await agent.reload();
    await expect(
      agent.getByRole("button", { name: "Se connecter", exact: true }),
    ).toBeVisible();
    await agent.goto(resetLink);
    const recovered = "Retour26!abc";
    await agent
      .getByLabel("Nouveau mot de passe", { exact: true })
      .fill(recovered);
    await agent
      .getByLabel("Confirmer le mot de passe", { exact: true })
      .fill(recovered);
    await agent
      .getByRole("button", {
        name: "Enregistrer mon mot de passe",
        exact: true,
      })
      .click();
    await expect(
      agent.getByRole("heading", { name: "Bonjour, Agent." }),
    ).toBeVisible();
    await row.locator("summary").click();
    await row
      .getByRole("button", { name: "Désactiver le compte", exact: true })
      .click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Confirmer", exact: true })
      .click();
    await expect(row).toContainText("Désactivé");
    await agent.reload();
    await expect(
      agent.getByRole("heading", { name: "Heureux de vous retrouver." }),
    ).toBeVisible();
    await page
      .getByRole("link", { name: "Journal d’audit", exact: true })
      .click();
    await expect(
      page
        .getByRole("cell", { name: "Accès du compte modifiés", exact: true })
        .first(),
    ).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  } finally {
    await context.close().catch(() => {});
  }
});

test("invitation admin, QR code MFA, codes de récupération et expiration de session", async ({
  page,
  browser,
}) => {
  const seed = fixture<Seed>({ op: "seed" });
  await login(page, seed.email, seed.password, seed.factor);
  await expect(
    page.getByRole("heading", { name: /Les bonnes personnes/ }),
  ).toBeVisible();
  const email = `admin-ui-${Date.now()}@example.invalid`;
  const password = "Admin2026!ab";
  const link = await invite(page, email, "Admin invité", "admin");
  const context = await browser.newContext({
    baseURL: process.env.UI_TEST_URL,
    ignoreHTTPSErrors: true,
  });
  try {
    const newcomer = await context.newPage();
    await accept(newcomer, link, password);
    await expect(
      newcomer.getByRole("heading", { name: "Une sécurité en plus." }),
    ).toBeVisible();
    expect((await context.request.get("/api/admin/users")).status()).toBe(403);
    await newcomer
      .getByRole("button", {
        name: "Configurer la double authentification",
        exact: true,
      })
      .click();
    await expect(
      newcomer.getByAltText(
        "Code QR à scanner dans votre application d’authentification",
      ),
    ).toBeVisible();
    const secret = (await newcomer.locator(".secret-key").textContent())!;
    const factor = fixture<{ code: string }>({ op: "otp", secret }).code;
    await newcomer
      .getByLabel("Code à 6 chiffres", { exact: true })
      .fill(factor);
    await newcomer
      .getByRole("button", { name: "Activer la protection", exact: true })
      .click();
    await expect(
      newcomer.getByRole("heading", { name: "Gardez une porte de secours." }),
    ).toBeVisible();
    const codes = await newcomer
      .locator(".recovery-codes code")
      .allTextContents();
    expect(codes.length).toBe(8);
    const next = newcomer.getByRole("button", {
      name: "Accéder à mon espace",
      exact: true,
    });
    await expect(next).toBeDisabled();
    await newcomer
      .getByRole("checkbox", {
        name: "J’ai enregistré mes codes de récupération.",
      })
      .check();
    await next.click();
    await expect(
      newcomer.getByRole("heading", { name: /Les bonnes personnes/ }),
    ).toBeVisible();
    await expect(newcomer.locator(".recovery-codes")).toHaveCount(0);
    await newcomer
      .getByRole("button", { name: "Se déconnecter", exact: true })
      .click();
    await login(newcomer, email, password);
    await expect(newcomer.getByRole("alert")).toContainText(
      "Identifiants invalides",
    );
    await login(newcomer, email, password, codes[0]);
    await expect(
      newcomer.getByRole("heading", { name: /Les bonnes personnes/ }),
    ).toBeVisible();
    fixture({ op: "expire", email });
    await newcomer.reload();
    await expect(
      newcomer.getByRole("heading", { name: "Heureux de vous retrouver." }),
    ).toBeVisible();
    expect(
      await newcomer.evaluate(
        () => localStorage.length + sessionStorage.length,
      ),
    ).toBe(0);
  } finally {
    await context.close().catch(() => {});
  }
});
