import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { spawnSync } from "node:child_process";
import path from "node:path";

function fixture<T>(payload: object): T {
  const r = spawnSync(
    "python3",
    [path.resolve("..", "tests/browser-fixtures.py")],
    { input: JSON.stringify(payload), encoding: "utf8", env: process.env },
  );
  if (r.status !== 0) throw new Error("Synthetic inbound fixture failed");
  return JSON.parse(r.stdout) as T;
}
type Credentials = {
  id: string;
  email: string;
  password: string;
  factor?: string;
};
async function login(page: Page, c: Credentials) {
  await page.goto("/connexion");
  await page.getByLabel("Adresse courriel", { exact: true }).fill(c.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(c.password);
  if (c.factor)
    await page
      .getByLabel("Code d’authentification ou de récupération", { exact: true })
      .fill(c.factor);
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Appels entrants", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Appels entrants", exact: true })
    .click();
}
async function accessible(page: Page) {
  const r = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    r.violations.map((v) => ({
      id: v.id,
      targets: v.nodes.map((n) => n.target),
    })),
  ).toEqual([]);
}

test("réception : réglages admin, prise en charge, rappel et historique partagés en PostgreSQL", async ({
  page,
}) => {
  const admin = fixture<Credentials>({ op: "seed" });
  const agentName = "Agent réception " + crypto.randomUUID().slice(0, 8);
  const agent = fixture<Credentials>({ op: "agent", name: agentName });
  const queueName = "Réception UI " + crypto.randomUUID().slice(0, 8);
  const number = fixture<{ phone: string }>({ op: "inbound_number" }).phone;
  const caller = "+15145550777";
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, admin);
  await page
    .getByRole("button", { name: "Créer une file", exact: true })
    .click();
  let dialog = page.getByRole("dialog");
  await dialog.getByLabel("Nom de la file", { exact: true }).fill(queueName);
  await dialog.getByLabel("Numéro de réception", { exact: true }).fill(number);
  await dialog.getByLabel(agentName, { exact: true }).check();
  await dialog
    .getByRole("button", { name: "Ajouter une plage", exact: true })
    .click();
  await accessible(page);
  await dialog
    .getByRole("button", { name: "Enregistrer les réglages", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: queueName, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Numéro non connecté", { exact: true }),
  ).toBeVisible();
  const queueId = await page
    .getByRole("combobox", { name: "File de réception", exact: true })
    .inputValue();
  const followup = fixture<{ id: string }>({
    op: "inbound_call",
    queue_id: queueId,
    phone: caller,
  });
  await page.getByRole("button", { name: "Actualiser", exact: true }).click();
  await page.getByRole("button").filter({ hasText: caller }).click();
  dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: caller, exact: true }),
  ).toBeVisible();
  await dialog
    .getByLabel("Ajouter une note", { exact: true })
    .fill("Le client souhaite un rappel demain.");
  await dialog
    .getByRole("button", { name: "Enregistrer la note", exact: true })
    .click();
  await expect(
    dialog.getByText("Le client souhaite un rappel demain.", { exact: true }),
  ).toBeVisible();
  await dialog
    .getByRole("combobox", { name: "Étape du suivi", exact: true })
    .selectOption("claimed");
  await dialog
    .getByRole("combobox", { name: "Agent responsable", exact: true })
    .selectOption(agent.id);
  await dialog
    .getByRole("button", { name: "Enregistrer le suivi", exact: true })
    .click();
  await expect(
    dialog.locator("dd").filter({ hasText: agentName }),
  ).toBeVisible();
  await accessible(page);
  await dialog
    .getByRole("button", { name: "Fermer la fenêtre", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Se déconnecter", exact: true })
    .click();
  await login(page, agent);
  await expect(
    page.getByRole("button", { name: "Créer une file", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Modifier les réglages", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button").filter({ hasText: caller }).click();
  dialog = page.getByRole("dialog");
  await expect(
    dialog.getByText("Le client souhaite un rappel demain.", { exact: true }),
  ).toBeVisible();
  await dialog
    .getByRole("combobox", { name: "Étape du suivi", exact: true })
    .selectOption("callback");
  await dialog
    .getByLabel("Date et heure du rappel", { exact: true })
    .fill("2030-02-12T12:00");
  await expect(
    dialog.getByRole("button", { name: "Enregistrer le suivi", exact: true }),
  ).toBeEnabled();
  await dialog
    .getByRole("button", { name: "Enregistrer le suivi", exact: true })
    .click();
  await expect(
    dialog.getByText("Rappel manuel :", { exact: false }),
  ).toBeVisible();
  await dialog
    .getByRole("button", { name: "Fermer la fenêtre", exact: true })
    .click();
  await page.reload();
  const callback = page.getByRole("region", {
    name: "Rappel programmé",
    exact: true,
  });
  await callback.getByRole("button").filter({ hasText: caller }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByRole("combobox", { name: "Étape du suivi", exact: true })
    .selectOption("handled");
  await dialog
    .getByRole("button", { name: "Enregistrer le suivi", exact: true })
    .click();
  await expect(
    dialog.getByText("Ce suivi est clôturé.", { exact: false }),
  ).toBeVisible();
  await dialog
    .getByRole("button", { name: "Fermer la fenêtre", exact: true })
    .click();
  const second = fixture<{ id: string }>({
    op: "inbound_call",
    queue_id: queueId,
    phone: caller,
  });
  expect(second.id).not.toBe(followup.id);
  await page.getByRole("button", { name: "Actualiser", exact: true }).click();
  await expect(
    page
      .getByRole("region", { name: "À traiter", exact: true })
      .getByRole("button")
      .filter({ hasText: caller }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await accessible(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("erreur de chargement : aucune fausse liste vide ni création annoncée", async ({
  page,
}) => {
  const admin = fixture<Credentials>({ op: "seed" });
  await page.route("**/api/inbound/queues", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Le chargement des files est indisponible." },
    }),
  );
  await login(page, admin);
  await expect(page.getByRole("alert")).toContainText("chargement des files");
  await expect(
    page.getByRole("heading", { name: "Organiser la réception", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("Aucun suivi.", { exact: true })).toHaveCount(0);
});
