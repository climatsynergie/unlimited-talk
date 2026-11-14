import { useId } from "react";
import type { ChangeEvent, FormEvent, InvalidEvent } from "react";
import { Icon } from "./ui";

export type QualificationValue = {
  schema_version: number;
  answers: Record<string, string>;
};
export type QualificationField = {
  key: string;
  label: string;
  options: string[] | null;
  required: boolean;
  condition: [string, string[]] | null;
  group: string;
};
export type QualificationSchema = {
  schema_version: number;
  fields: QualificationField[];
  previous_versions?: QualificationSchema[];
};
export type SavedQualification = {
  revision: string;
  qualification: QualificationValue;
};

const GROUPS = [
  {
    key: "proprietaires",
    title: "Propriétaires et présences",
    hint: "Confirmer les personnes attendues au rendez-vous.",
    icon: "users",
  },
  {
    key: "logement",
    title: "Le logement",
    hint: "Les caractéristiques du bien à visiter.",
    icon: "home",
  },
  {
    key: "equipement",
    title: "Chauffage et thermopompe",
    hint: "Identifier les équipements et leur ancienneté.",
    icon: "home",
  },
  {
    key: "isolation",
    title: "Isolation et consommation",
    hint: "Les travaux réalisés et la facture d’électricité.",
    icon: "shield",
  },
  {
    key: "adresse",
    title: "Adresse de la visite",
    hint: "Vérifier les coordonnées avec le client.",
    icon: "home",
  },
  {
    key: "conseiller",
    title: "À transmettre au conseiller",
    hint: "Les précisions utiles pour préparer sa visite.",
    icon: "conversation",
  },
] as const;

export function visibleField(
  field: QualificationField,
  answers: Record<string, string>,
) {
  return (
    !field.condition ||
    field.condition[1].includes(answers[field.condition[0]] || "")
  );
}

function schemaForValue(
  schema: QualificationSchema,
  value: QualificationValue,
) {
  return value.schema_version === schema.schema_version
    ? schema
    : schema.previous_versions?.find(
        (previous) => previous.schema_version === value.schema_version,
      ) || schema;
}

export function upgradeQualification(
  schema: QualificationSchema,
  value: QualificationValue,
): QualificationValue {
  if (
    value.schema_version >= schema.schema_version ||
    !schema.previous_versions?.some(
      (previous) => previous.schema_version === value.schema_version,
    )
  )
    return value;
  const answers = { ...value.answers };
  const insulation = answers.insulation?.trim();
  if (
    value.schema_version === 1 &&
    insulation &&
    !schema.fields
      .find((field) => field.key === "insulation")
      ?.options?.includes(insulation)
  ) {
    // Keep the original words, without guessing whether work was carried out.
    answers.insulation_comment = [answers.insulation_comment, insulation]
      .filter(Boolean)
      .join("\n");
    delete answers.insulation;
  }
  return { schema_version: schema.schema_version, answers };
}

export function initialQualification(
  schema: QualificationSchema,
  profile: Record<string, string>,
): QualificationValue {
  const address = (profile.address || "").trim();
  const match = address.match(/^([0-9]+[A-Za-z]?(?:[- ][0-9]+)?)\s+(.+)$/);
  return {
    schema_version: schema.schema_version,
    answers: {
      civic_number: match?.[1] || "",
      street: match?.[2] || address,
      city: profile.city || "",
      postal_code: profile.postal_code || "",
    },
  };
}

function answered(field: QualificationField, answers: Record<string, string>) {
  const answer = answers[field.key]?.trim();
  return !!answer && (!field.options || field.options.includes(answer));
}

type ControlEvent = ChangeEvent<
  HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
>;
type ValidityEvent = InvalidEvent<
  HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
>;
type InputEvent = FormEvent<
  HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
>;

export function QualificationFields({
  schema,
  value,
  onChange,
  required = false,
  disabled = false,
  draftSaveAvailable = true,
}: {
  schema: QualificationSchema;
  value: QualificationValue;
  onChange: (value: QualificationValue) => void;
  required?: boolean;
  disabled?: boolean;
  draftSaveAvailable?: boolean;
}) {
  const formId = useId();
  const formSchema = schemaForValue(schema, value);
  const fields = formSchema.fields.filter((field) =>
    visibleField(field, value.answers),
  );
  const essentials = fields.filter((field) => field.required);
  const completed = essentials.filter((field) =>
    answered(field, value.answers),
  ).length;
  function change(key: string, answer: string) {
    const answers = { ...value.answers, [key]: answer };
    for (const field of formSchema.fields)
      if (!visibleField(field, answers)) delete answers[field.key];
    onChange({ schema_version: formSchema.schema_version, answers });
  }
  function invalid(event: ValidityEvent) {
    event.currentTarget.setCustomValidity("Veuillez renseigner ce champ.");
  }
  function input(event: InputEvent) {
    event.currentTarget.setCustomValidity("");
  }
  return (
    <fieldset className="qualification-fields" disabled={disabled}>
      <legend>
        <Icon name="shield" /> Qualification du client
      </legend>
      <div className="qualification-intro">
        <p>
          Préparez la visite avec le client. Les champs marqués{" "}
          <span aria-hidden="true">*</span> sont nécessaires pour confirmer un
          rendez-vous.
        </p>
        <div
          className={`qualification-progress${completed === essentials.length ? " is-complete" : ""}`}
        >
          <span>
            <strong>
              {completed} / {essentials.length}
            </strong>{" "}
            champs essentiels
          </span>
          <progress
            aria-label="Avancement de la qualification"
            value={completed}
            max={essentials.length || 1}
          />
        </div>
      </div>
      {GROUPS.filter((group) =>
        fields.some((field) => field.group === group.key),
      ).map((group, index) => {
        const groupFields = fields.filter((field) => field.group === group.key);
        if (!groupFields.length) return null;
        const groupRequired = groupFields.filter((field) => field.required);
        const complete =
          groupRequired.length > 0 &&
          groupRequired.every((field) => answered(field, value.answers));
        return (
          <fieldset
            className="qualification-group"
            key={group.key}
            data-complete={complete}
          >
            <legend>
              <span className="qualification-section-icon">
                <Icon name={complete ? "check" : group.icon} />
              </span>
              {group.title}
              <span className="qualification-section-number" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
            </legend>
            <p className="qualification-section-hint">{group.hint}</p>
            <div className="qualification-grid">
              {groupFields.map((field) => {
                const id = `${formId}-${field.key}`;
                const label = field.label.replace(/^\d+\.\s*/, "");
                const title = (
                  <>
                    {label}
                    {field.required ? (
                      <span
                        className="qualification-required"
                        aria-hidden="true"
                      >
                        {" "}
                        *
                      </span>
                    ) : (
                      <span className="qualification-optional">Facultatif</span>
                    )}
                  </>
                );
                if (field.options && field.options.length <= 3)
                  return (
                    <fieldset
                      className="qualification-field qualification-choice-field"
                      key={field.key}
                      aria-label={field.label}
                    >
                      <legend>{title}</legend>
                      <div className="qualification-choices">
                        {field.options.map((option) => (
                          <label
                            className="qualification-choice"
                            key={option}
                            data-positive={
                              option === "Oui" || option === "Refaite"
                            }
                          >
                            <input
                              type="radio"
                              name={id}
                              value={option}
                              checked={value.answers[field.key] === option}
                              required={required && field.required}
                              onInvalid={invalid}
                              onChange={(event) => {
                                event.currentTarget
                                  .closest("fieldset")
                                  ?.querySelectorAll("input")
                                  .forEach((control) =>
                                    control.setCustomValidity(""),
                                  );
                                change(field.key, option);
                              }}
                            />
                            <span>{option}</span>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  );
                const props = {
                  id,
                  value: value.answers[field.key] || "",
                  required: required && field.required,
                  "aria-label": field.label,
                  onChange: (event: ControlEvent) =>
                    change(field.key, event.target.value),
                  onInvalid: invalid,
                  onInput: input,
                };
                const multiline =
                  field.key === "comments" ||
                  field.key.endsWith("_comment") ||
                  field.key === "insulation";
                return (
                  <div
                    className={`qualification-field${field.key === "comments" || field.key === "insulation_comment" ? " qualification-wide" : ""}`}
                    key={field.key}
                  >
                    <label htmlFor={id}>{title}</label>
                    {field.options ? (
                      <select {...props}>
                        <option value="">Choisir…</option>
                        {field.options.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                    ) : multiline ? (
                      <textarea
                        {...props}
                        maxLength={2000}
                        rows={field.key === "comments" ? 3 : 2}
                      />
                    ) : (
                      <input
                        {...props}
                        maxLength={2000}
                        type="text"
                        placeholder={
                          field.key === "hydro_bill"
                            ? "Ex. : 150 $ / mois ou 1 800 $ / an"
                            : field.key === "construction_year"
                              ? "Ex. : 1970, vers 1970 ou inconnue"
                              : undefined
                        }
                        aria-describedby={
                          field.key === "hydro_bill" ? `${id}-hint` : undefined
                        }
                      />
                    )}
                    {field.key === "hydro_bill" ? (
                      <small id={`${id}-hint`}>
                        Précisez le montant et la période indiqués par le
                        client.
                      </small>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </fieldset>
        );
      })}
      <p className="qualification-save-hint">
        <Icon name="shield" />
        {draftSaveAvailable
          ? "Une fiche incomplète peut être enregistrée pendant l’appel."
          : "Les réponses seront enregistrées avec le rendez-vous."}
      </p>
    </fieldset>
  );
}

export function QualificationSummary({
  schema,
  value,
}: {
  schema: QualificationSchema;
  value: QualificationValue | null | undefined;
}) {
  if (!value)
    return <p>Aucune qualification enregistrée pour ce rendez-vous.</p>;
  return (
    <details className="qualification-summary" open>
      <summary>Qualification du rendez-vous</summary>
      <dl className="contact-profile">
        {schemaForValue(schema, value)
          .fields.filter(
            (field) =>
              visibleField(field, value.answers) && !!value.answers[field.key],
          )
          .map((field) => (
            <div key={field.key}>
              <dt>{field.label}</dt>
              <dd className="appointment-notes">{value.answers[field.key]}</dd>
            </div>
          ))}
      </dl>
    </details>
  );
}
