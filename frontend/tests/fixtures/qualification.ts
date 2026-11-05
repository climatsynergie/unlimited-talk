import { readFileSync } from "node:fs";
import type { Locator, Page } from "@playwright/test";
import type {
  QualificationSchema,
  QualificationValue,
} from "../../src/Qualification";

export const qualificationSchema: QualificationSchema = JSON.parse(
  readFileSync(
    new URL("../../../backend/app/qualification-v2.json", import.meta.url),
    "utf8",
  ),
);
qualificationSchema.previous_versions = [
  JSON.parse(
    readFileSync(
      new URL("../../../backend/app/qualification-v1.json", import.meta.url),
      "utf8",
    ),
  ),
];

export const validQualification: QualificationValue = JSON.parse(
  readFileSync(
    new URL("../../../tests/qualification-fixture.json", import.meta.url),
    "utf8",
  ),
);

export async function fillQualification(
  scope: Locator | Page,
  answers = validQualification.answers,
) {
  for (const field of qualificationSchema.fields) {
    if (
      field.condition &&
      !field.condition[1].includes(answers[field.condition[0]])
    )
      continue;
    if (!(field.key in answers)) continue;
    if (field.options && field.options.length <= 3)
      await scope
        .getByRole("group", { name: field.label, exact: true })
        .getByRole("radio", { name: answers[field.key], exact: true })
        .check();
    else if (field.options)
      await scope
        .getByRole("combobox", { name: field.label, exact: true })
        .selectOption(answers[field.key]);
    else
      await scope
        .getByRole("textbox", { name: field.label, exact: true })
        .fill(answers[field.key]);
  }
}
