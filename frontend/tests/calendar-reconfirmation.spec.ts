import { test, expect } from "./qa-observer";
import type { Page } from "@playwright/test";
import { disabledDialer } from "./fixtures/dialer-disabled";

const uuid = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
async function fixture(page: Page, status: string) {
  const appointment = {
    id: uuid(1),
    campaign_id: uuid(2),
    contact_id: uuid(3),
    created_by: uuid(4),
    creator_name: "Agent QA",
    starts_at: "2026-11-09T14:00:00Z",
    ends_at: "2026-11-09T14:30:00Z",
    timezone: "America/Toronto",
    notes: "",
    status,
    phase: undefined as string | undefined,
    version: 0,
    phone: "+14165550101",
    profile: { display_name: "Client QA" },
    campaign_name: "Campagne QA",
    qualification: null as unknown,
  };
  const schema = {
    schema_version: 1,
    fields: [
      {
        key: "owner",
        label: "Le client est-il propriétaire ?",
        options: ["Oui", "Non"],
        required: true,
        condition: null,
        group: "proprietaires",
      },
    ],
  };
  const proof = {
    writes: [] as Record<string, unknown>[],
    unexpected: [] as string[],
  };
  await page.route("**/api/**", (route) => {
    proof.unexpected.push(new URL(route.request().url()).pathname);
    return route.fulfill({
      status: 404,
      json: { detail: "Unexpected isolated test request" },
    });
  });
  await disabledDialer(page);
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      json: {
        user: {
          id: uuid(4),
          role: "admin",
          display_name: "Admin QA",
          email: "qa@example.invalid",
          is_active: true,
        },
        mfa_enrollment_required: false,
      },
    }),
  );
  await page.route("**/api/telephony/test/session", (route) =>
    route.fulfill({ json: { enabled: false, active: null } }),
  );
  await page.route("**/api/calendar?*", (route) =>
    route.fulfill({
      json: {
        items: [appointment],
        has_more: false,
        viewer_id: uuid(4),
        name: "Unlimited Talks",
      },
    }),
  );
  await page.route("**/api/calendar/resolve?*", (route) =>
    route.fulfill({
      json: {
        options: [
          { utc_offset_minutes: -300, starts_at: appointment.starts_at },
        ],
      },
    }),
  );
  await page.route(`**/api/calendar/${appointment.id}`, (route) => {
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON();
      proof.writes.push(body);
      appointment.status = body.status;
      appointment.phase = body.phase;
      appointment.qualification = body.qualification;
      return route.fulfill({ json: { appointment } });
    }
    return route.fulfill({
      json: {
        appointment,
        can_edit: true,
        events: [],
        has_more: false,
        qualification_schema: schema,
      },
    });
  });
  return proof;
}
for (const status of ["completed", "no_show", "cancelled"]) {
  for (const filled of [false, true]) {
    test(`reconfirmation ${status} : qualification ${filled ? "renseignée" : "vide"} acceptée`, async ({
      page,
    }) => {
      const proof = await fixture(page, status);
      await page.goto("/calendrier");
      await page
        .getByLabel("Aller à la date", { exact: true })
        .fill("2026-11-09");
      await page
        .getByRole("combobox", { name: "Statut", exact: true })
        .selectOption("all");
      await page.getByRole("button", { name: "Agenda", exact: true }).click();
      await page
        .locator(".appointment-card")
        .filter({ hasText: "Client QA" })
        .click();
      const dialog = page.getByRole("dialog");
      await dialog
        .getByRole("button", {
          name: "Modifier ou annuler le rendez-vous",
          exact: true,
        })
        .click();
      await dialog
        .getByRole("combobox", { name: "Statut", exact: true })
        .selectOption("booked");
      await expect(
        dialog.getByRole("radio", { name: "Oui", exact: true }),
      ).toBeVisible();
      const save = dialog.getByRole("button", {
        name: "Enregistrer les modifications",
        exact: true,
      });
      await expect(
        dialog.locator(".qualification-fields [required]"),
      ).toHaveCount(0);
      if (filled) {
        await dialog.getByRole("radio", { name: "Oui", exact: true }).check();
      }
      await save.click();
      await expect.poll(() => proof.writes.length).toBe(1);
      expect(proof.writes[0]).toMatchObject({
        status: "booked",
        qualification: {
          schema_version: 1,
          answers: filled ? { owner: "Oui" } : {},
        },
      });
      expect(proof.unexpected).toEqual([]);
    });
  }
}

for (const [phase, label, status, color] of [
  ["confirmed", "Confirmé", "booked", "rgb(220, 252, 231)"],
  ["sold", "Vendu", "completed", "rgb(219, 234, 254)"],
  ["cancelled", "Annulé", "cancelled", "rgb(254, 226, 226)"],
  ["invalid", "Non Valide", "cancelled", "rgb(255, 228, 230)"],
  ["non_compliant", "Non Conforme", "cancelled", "rgb(254, 202, 202)"],
]) {
  test(`phase ${label} : enregistrement et couleur de la fenêtre`, async ({
    page,
  }) => {
    const proof = await fixture(page, "booked");
    await page.goto("/calendrier");
    await page
      .getByLabel("Aller à la date", { exact: true })
      .fill("2026-11-09");
    await page
      .getByRole("combobox", { name: "Statut", exact: true })
      .selectOption("all");
    await page.getByRole("button", { name: "Agenda", exact: true }).click();
    await page
      .locator(".appointment-card")
      .filter({ hasText: "Client QA" })
      .click();
    const dialog = page.getByRole("dialog");
    await dialog
      .getByRole("button", {
        name: "Modifier ou annuler le rendez-vous",
        exact: true,
      })
      .click();
    await dialog
      .getByRole("combobox", { name: "Statut", exact: true })
      .selectOption(phase);
    await dialog
      .getByRole("button", {
        name: "Enregistrer les modifications",
        exact: true,
      })
      .click();
    await expect.poll(() => proof.writes.length).toBe(1);
    expect(proof.writes[0]).toMatchObject({ phase, status });
    await expect(dialog).toHaveClass(new RegExp(`phase-${phase}`));
    await expect(dialog.locator(".appointment-phase-badge")).toHaveText(label);
    await expect(dialog.getByText(label, { exact: true })).toBeVisible();
    await expect(dialog.locator(".modal-heading")).toHaveCSS(
      "background-color",
      color,
    );
    expect(proof.unexpected).toEqual([]);
  });
}
