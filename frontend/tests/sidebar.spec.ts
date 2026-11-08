import { test, expect } from "./qa-observer";
import type { Page, Locator } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function administrator(page: Page) {
  const unexpected: string[] = [];
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const responses: Record<string, unknown> = {
      "/api/auth/me": {
        user: {
          id: "00000000-0000-0000-0000-000000000011",
          email: "navigation@example.invalid",
          display_name: "Administratrice de l’équipe Unlimited Talks",
          role: "admin",
          is_active: true,
        },
        mfa_enrollment_required: false,
      },
      "/api/reporting/presence": { ok: true },
      "/api/admin/users": { users: [], total: 0 },
      "/api/admin/audit": { events: [] },
      "/api/admin/invitations": { invitations: [], total: 0 },
      "/api/telephony/test/session": { enabled: false, active: null },
      "/api/telephony/dialer/session": {
        enabled: false,
        dialer: { mode: "stopped", generation: 0, campaign_id: null },
      },
    };
    if (!(path in responses))
      unexpected.push(`${route.request().method()} ${path}`);
    return route.fulfill({
      status: path in responses ? 200 : 404,
      json: responses[path] ?? { detail: "Fixture manquante" },
    });
  });
  await page.goto("/admin/utilisateurs");
  await expect(
    page.getByRole("navigation", { name: "Navigation principale" }),
  ).toBeVisible();
  return unexpected;
}

async function inViewport(page: Page, element: Locator) {
  const bounds = await element.boundingBox();
  expect(bounds).not.toBeNull();
  const viewport = page.viewportSize()!;
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width + 1);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height + 1);
}

test("menu administrateur : petit écran, molette et clavier atteignent tous les liens", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 600 });
  const unexpected = await administrator(page);
  const nav = page.getByRole("navigation", { name: "Navigation principale" });
  const account = page.getByRole("link", { name: "Mon compte", exact: true });
  const logout = page.getByRole("button", {
    name: "Se déconnecter",
    exact: true,
  });
  await inViewport(page, account);
  await inViewport(page, logout);
  await inViewport(
    page,
    nav.getByRole("link", { name: "Utilisateurs", exact: true }),
  );
  expect(await nav.getByRole("link").count()).toBe(12);
  await expect(
    nav.getByRole("link", { name: "Tableau de bord", exact: true }),
  ).toHaveCount(1);
  await nav.hover();
  await page.mouse.wheel(0, 900);
  await expect
    .poll(() => nav.evaluate((el) => el.scrollTop))
    .toBeGreaterThan(0);
  await inViewport(
    page,
    nav.getByRole("link", { name: "Journal d’audit", exact: true }),
  );
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await nav.getByRole("link", { name: "Journal d’audit", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/journal$/);
  await expect(
    nav.getByRole("link", { name: "Journal d’audit", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await nav.getByRole("link").first().focus();
  await inViewport(page, nav.getByRole("link").first());
  await nav.getByRole("link").last().focus();
  await page.keyboard.press("Tab");
  await expect(account).toBeFocused();
  await inViewport(page, account);
  await page.keyboard.press("Tab");
  await expect(logout).toBeFocused();
  await inViewport(page, logout);
  await account.click();
  await expect(page).toHaveURL(/\/compte$/);
  expect(unexpected).toEqual([]);
});

test("menu mobile et tablette : aucune sortie horizontale, même entre 700 et 760 pixels", async ({
  page,
}) => {
  const unexpected = await administrator(page);
  const nav = page.getByRole("navigation", { name: "Navigation principale" });
  for (const viewport of [
    { width: 320, height: 568 },
    { width: 390, height: 500 },
    { width: 740, height: 560 },
    { width: 800, height: 450 },
  ]) {
    await page.setViewportSize(viewport);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(viewport.width);
    for (const link of await nav.getByRole("link").all()) {
      await link.focus();
      await inViewport(page, link);
    }
    await inViewport(
      page,
      page.getByRole("link", { name: "Mon compte", exact: true }),
    );
    await inViewport(
      page,
      page.getByRole("button", { name: "Se déconnecter", exact: true }),
    );
    const next = page.getByRole("button", { name: "Suivant", exact: true });
    await next.scrollIntoViewIfNeeded();
    await inViewport(page, next);
    await page.evaluate(() => window.scrollTo(0, 0));
  }
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    result.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({
        target: n.target,
        summary: n.failureSummary,
      })),
    })),
  ).toEqual([]);
  expect(unexpected).toEqual([]);
});
