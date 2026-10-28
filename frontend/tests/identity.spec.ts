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
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  const validation = await page
    .getByLabel("Adresse courriel", { exact: true })
    .evaluate((input: HTMLInputElement) => input.validationMessage);
  expect(validation).toBe("Veuillez renseigner ce champ.");
  await accessible(page);
  await screenshot(page, "connexion-desktop.png");
  const unknown = await page.request.get("/api/not-a-real-route");
  expect(unknown.status()).toBe(404);
  expect((await unknown.json()).detail).toBe("Ressource introuvable.");
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

test("import CSV privé, aperçu, confirmation et contacts en français", async ({
  page,
}) => {
  const seed = fixture<Seed>({ op: "seed" });
  await login(page, seed.email, seed.password, seed.factor);
  await page.getByRole("link", { name: "Imports CSV", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Imports CSV", exact: true }),
  ).toBeVisible();
  await accessible(page);
  let localPhone = 5145550100;
  for (; localPhone < 5145550200; localPhone++) {
    const existing = await page.request.get(
      `/api/contacts?search=%2B1${localPhone}`,
    );
    if ((await existing.json()).items.length === 0) break;
  }
  expect(localPhone).toBeLessThan(5145550200);
  await page.getByLabel("Fichier CSV", { exact: true }).setInputFiles({
    name: "contacts-navigateur.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      `telephone,prenom,courriel\n${localPhone},Émilie,emilie@example.test\n${localPhone},,\ninvalide,Erreur,\n`,
    ),
  });
  await page
    .getByRole("button", { name: "Déposer le fichier", exact: true })
    .click();
  await expect(
    page.getByRole("group", { name: "Associer les colonnes" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Valider et afficher l’aperçu", exact: true })
    .click();
  await expect(
    page.getByText("2 lignes valides", { exact: false }),
  ).toBeVisible();
  const before = await page.request.get(
    `/api/contacts?search=%2B1${localPhone}`,
  );
  expect((await before.json()).items).toHaveLength(0);
  await accessible(page);
  let interruptedPoll = false;
  await page.route("**/api/imports/*", (route) => {
    if (
      !interruptedPoll &&
      route.request().method() === "GET" &&
      /\/api\/imports\/[a-f0-9-]{36}$/.test(
        new URL(route.request().url()).pathname,
      )
    ) {
      interruptedPoll = true;
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Interruption réseau temporaire." }),
      });
    }
    return route.continue();
  });
  await page
    .getByRole("button", {
      name: "Confirmer l’import de ces lignes",
      exact: true,
    })
    .click();
  await expect(
    page.getByText("3 / 3 lignes traitées", { exact: true }),
  ).toBeVisible({ timeout: 90000 });
  await expect(
    page.getByText(
      "1 contacts créés · 0 enrichis · 1 inchangés · 1 lignes invalides",
      { exact: true },
    ),
  ).toBeVisible();
  await page
    .getByLabel("Afficher uniquement les erreurs et avertissements")
    .check();
  await expect(
    page.getByRole("cell", {
      name: "Le numéro de téléphone n’est pas reconnu.",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Contacts", exact: true }).click();
  await page
    .getByLabel("Rechercher un contact", { exact: true })
    .fill(`+1${localPhone}`);
  await page.getByRole("button", { name: "Rechercher", exact: true }).click();
  expect(interruptedPoll).toBe(true);
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.getByRole("cell", { name: /^Émilie/ })).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "emilie@example.test", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: `Historique de +1${localPhone}`, exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Contact créé");
  await accessible(page);
  await page
    .getByRole("button", { name: "Fermer la fenêtre", exact: true })
    .click();
  await accessible(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await accessible(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await screenshot(page, "contacts-mobile.png");
});

test("campagne, pipeline, agent attribué et notes partagées", async ({
  page,
  browser,
}) => {
  const seed = fixture<Seed>({ op: "seed" });
  const assigned = fixture<{ email: string; password: string; id: string }>({
    op: "agent",
  });
  await login(page, seed.email, seed.password, seed.factor);
  await page.getByRole("link", { name: "Campagnes", exact: true }).click();
  await page
    .getByRole("button", { name: "Créer une campagne", exact: true })
    .click();
  const campaignName = `Campagne navigateur ${Date.now()}`;
  await page
    .getByLabel("Nom de la campagne", { exact: true })
    .fill(campaignName);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Créer la campagne", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: campaignName, exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Ajouter des contacts", exact: true })
    .click();
  const source = page.getByRole("combobox", {
    name: "Import terminé",
    exact: true,
  });
  await expect(
    source
      .locator("option")
      .filter({ hasText: "contacts-navigateur.csv" })
      .first(),
  ).toBeAttached();
  const importId = await source
    .locator("option")
    .filter({ hasText: "contacts-navigateur.csv" })
    .first()
    .getAttribute("value");
  await source.selectOption(importId!);
  await page
    .getByRole("button", { name: "Ajouter à la campagne", exact: true })
    .click();
  await expect(
    page.getByRole("status").filter({ hasText: "1 contacts ajoutés" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Terminer", exact: true }).click();
  await page
    .getByRole("button", { name: "Réglages de la campagne", exact: true })
    .click();
  // The label contains the unique synthetic email, independent of other agents.
  await page
    .getByRole("dialog")
    .locator("label")
    .filter({ hasText: assigned.email })
    .getByRole("checkbox")
    .check();
  await expect(
    page
      .getByRole("dialog")
      .locator("label")
      .filter({ hasText: assigned.email })
      .getByRole("checkbox"),
  ).toBeChecked();
  await page
    .getByRole("button", { name: "Ajouter une étape", exact: true })
    .click();
  await page
    .getByLabel("Nom de l’étape", { exact: true })
    .fill("Qualification");
  await page
    .getByRole("combobox", { name: "Couleur", exact: true })
    .selectOption("blue");
  await page
    .getByRole("button", { name: "Enregistrer l’étape", exact: true })
    .click();
  await expect(
    page.getByRole("dialog").getByText("Qualification", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Fermer la fenêtre", exact: true })
    .click();
  const initialColumn = page.getByRole("region", {
    name: "Étape À appeler",
    exact: true,
  });
  await initialColumn.getByRole("button").filter({ hasText: "Émilie" }).click();
  await page
    .getByRole("combobox", { name: "Étape du pipeline", exact: true })
    .selectOption({ label: "Qualification" });
  await page
    .getByRole("button", { name: "Déplacer vers cette étape", exact: true })
    .click();
  const qualified = page.getByRole("region", {
    name: "Étape Qualification",
    exact: true,
  });
  await expect(
    qualified.getByRole("button").filter({ hasText: "Émilie" }),
  ).toBeVisible();
  await accessible(page);
  await screenshot(page, "campagne-desktop.png");
  const context = await browser.newContext({
    baseURL: process.env.UI_TEST_URL,
    ignoreHTTPSErrors: true,
  });
  try {
    const agent = await context.newPage();
    await login(agent, assigned.email, assigned.password);
    await agent
      .getByRole("link", { name: "Mes campagnes", exact: true })
      .click();
    await agent.getByRole("button").filter({ hasText: campaignName }).click();
    await expect(
      agent.getByRole("button", {
        name: "Réglages de la campagne",
        exact: true,
      }),
    ).toHaveCount(0);
    await agent
      .getByRole("region", { name: "Étape Qualification", exact: true })
      .getByRole("button")
      .filter({ hasText: "Émilie" })
      .click();
    await agent
      .getByLabel("Ajouter une note", { exact: true })
      .fill("Rappel demandé, informations vérifiées.");
    await agent
      .getByRole("button", { name: "Enregistrer la note", exact: true })
      .click();
    await expect(agent.getByRole("dialog")).toContainText(
      "Rappel demandé, informations vérifiées.",
    );
    await accessible(agent);
    await agent
      .getByRole("button", { name: "Fermer la fenêtre", exact: true })
      .click();
    await agent.setViewportSize({ width: 390, height: 844 });
    await accessible(agent);
    expect(
      await agent.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await screenshot(agent, "campagne-agent-mobile.png");
  } finally {
    await context.close();
  }
  await qualified.getByRole("button").filter({ hasText: "Émilie" }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "Rappel demandé, informations vérifiées.",
  );
});

test("calendrier partagé, réservation, modification et annulation", async ({
  page,
}) => {
  const seed = fixture<Seed>({ op: "seed" });
  await login(page, seed.email, seed.password, seed.factor);
  // Use one previously imported synthetic contact. Browser fixtures never use managed PostgreSQL.
  await page.getByRole("link", { name: "Campagnes", exact: true }).click();
  await page
    .getByRole("button")
    .filter({ hasText: "Campagne navigateur" })
    .first()
    .click();
  await page
    .locator(".pipeline-card")
    .filter({ hasText: "Émilie" })
    .first()
    .click();
  await page
    .getByRole("button", { name: "Prendre rendez-vous", exact: true })
    .click();
  await page
    .getByLabel("Date et heure du rendez-vous", { exact: true })
    .fill("2026-11-02T10:00");
  await page
    .getByLabel("Notes du rendez-vous", { exact: true })
    .fill("Préparer la rencontre avec le client.");
  await page
    .getByRole("button", { name: "Confirmer le rendez-vous", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Étape RDV booké", exact: true }),
  ).toContainText("Émilie");
  await page.getByRole("link", { name: "Calendrier", exact: true }).click();
  await page
    .getByLabel("Semaine à partir du", { exact: true })
    .fill("2026-11-02");
  const card = page
    .locator(".appointment-card")
    .filter({ hasText: "Émilie" })
    .first();
  await expect(card).toBeVisible();
  await accessible(page);
  await card.click();
  await expect(page.getByRole("dialog")).toContainText(
    "Préparer la rencontre avec le client.",
  );
  await page
    .getByRole("button", {
      name: "Modifier ou annuler le rendez-vous",
      exact: true,
    })
    .click();
  await page
    .getByLabel("Date et heure du rendez-vous", { exact: true })
    .fill("2026-11-03T11:00");
  await page.getByLabel("Durée en minutes", { exact: true }).fill("45");
  await page
    .getByRole("button", { name: "Enregistrer les modifications", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("45 minutes");
  await accessible(page);
  await page
    .getByRole("button", {
      name: "Modifier ou annuler le rendez-vous",
      exact: true,
    })
    .click();
  await page
    .getByRole("combobox", { name: "Statut", exact: true })
    .last()
    .selectOption("cancelled");
  await page
    .getByRole("button", { name: "Enregistrer les modifications", exact: true })
    .click();
  await expect(
    page.getByRole("dialog").getByText("Annulé", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Fermer la fenêtre", exact: true })
    .click();
  await expect(
    page.locator(".appointment-card").filter({ hasText: "Émilie" }),
  ).toHaveCount(0);
  await page
    .getByRole("combobox", { name: "Statut", exact: true })
    .selectOption("all");
  await expect(card).toBeVisible();
  await page
    .getByRole("combobox", { name: "Affichage", exact: true })
    .selectOption("week");
  await page.setViewportSize({ width: 390, height: 844 });
  await accessible(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await screenshot(page, "calendrier-mobile.png");
});

test("rappel programmé, sauvegarde interrompue, reprogrammation et historique", async ({
  page,
}) => {
  const seed = fixture<Seed>({ op: "seed" });
  await login(page, seed.email, seed.password, seed.factor);
  await page.getByRole("link", { name: "Campagnes", exact: true }).click();
  await page
    .getByRole("button")
    .filter({ hasText: "Campagne navigateur" })
    .first()
    .click();
  await page
    .locator(".pipeline-card")
    .filter({ hasText: "Émilie" })
    .first()
    .click();
  await page
    .getByRole("button", { name: "Programmer un rappel", exact: true })
    .click();
  const future =
    new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10) + "T14:00";
  await page
    .getByLabel("Date et heure du rappel", { exact: true })
    .fill(future);
  await page
    .getByRole("textbox", { name: "Notes du rappel", exact: true })
    .fill("Le client demande un rappel l’après-midi.");
  let interrupted = false;
  await page.route("**/api/callbacks", async (route) => {
    if (route.request().method() === "POST" && !interrupted) {
      interrupted = true;
      await route.fulfill({
        status: 503,
        json: { detail: "Indisponibilité temporaire" },
      });
    } else await route.continue();
  });
  await page
    .getByRole("button", { name: "Confirmer le rappel", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Indisponibilité temporaire",
  );
  await expect(
    page.getByRole("textbox", { name: "Notes du rappel", exact: true }),
  ).toHaveValue("Le client demande un rappel l’après-midi.");
  await page
    .getByRole("button", { name: "Confirmer le rappel", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Étape À rappeler", exact: true }),
  ).toContainText("Émilie");
  await page.getByRole("link", { name: "Rappels", exact: true }).click();
  const card = page
    .locator(".callback-list .appointment-card")
    .filter({ hasText: "Émilie" })
    .first();
  await expect(card).toBeVisible();
  await card.click();
  await expect(page.getByRole("dialog")).toContainText(
    "Le client demande un rappel l’après-midi.",
  );
  await page
    .getByRole("button", {
      name: "Reprogrammer ou clôturer le rappel",
      exact: true,
    })
    .click();
  await page
    .getByRole("textbox", { name: "Notes du rappel", exact: true })
    .fill("Horaire confirmé par le client.");
  const rescheduled =
    new Date(Date.now() + 4 * 86400000).toISOString().slice(0, 10) + "T15:00";
  await page
    .getByLabel("Date et heure du rappel", { exact: true })
    .fill(rescheduled);
  await page
    .getByRole("button", { name: "Enregistrer le rappel", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Reprogrammer ou clôturer le rappel",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toContainText(
    "Horaire confirmé par le client.",
  );
  await accessible(page);
  await page
    .getByRole("button", {
      name: "Reprogrammer ou clôturer le rappel",
      exact: true,
    })
    .click();
  await page
    .getByRole("combobox", { name: "Statut du rappel", exact: true })
    .selectOption("completed");
  await page
    .getByRole("button", { name: "Enregistrer le rappel", exact: true })
    .click();
  await expect(
    page.getByRole("dialog").getByText("Traité", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Fermer la fenêtre", exact: true })
    .click();
  await expect(card).toHaveCount(0);
  await page
    .getByRole("combobox", { name: "Afficher les rappels", exact: true })
    .selectOption("history");
  await expect(card).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await accessible(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await screenshot(page, "rappels-mobile.png");
});
