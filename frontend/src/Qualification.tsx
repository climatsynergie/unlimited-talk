import type { ChangeEvent, FormEvent, InvalidEvent } from "react";

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
};
export type SavedQualification = {
  revision: string;
  qualification: QualificationValue;
};

export function visibleField(
  field: QualificationField,
  answers: Record<string, string>,
) {
  return (
    !field.condition ||
    field.condition[1].includes(answers[field.condition[0]] || "")
  );
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
  function change(key: string, answer: string) {
    const answers = { ...value.answers, [key]: answer };
    for (const field of schema.fields)
      if (!visibleField(field, answers)) delete answers[field.key];
    onChange({ schema_version: schema.schema_version, answers });
  }
  return (
    <fieldset className="qualification-fields" disabled={disabled}>
      <legend>Qualification du client</legend>
      <p className="subtle">
        Les champs marqués d’un astérisque sont obligatoires pour confirmer un
        rendez-vous.{" "}
        {draftSaveAvailable
          ? "Vous pouvez enregistrer une fiche incomplète pendant l’appel."
          : "Les réponses sont enregistrées avec le rendez-vous."}
      </p>
      {Object.entries({
        logement: "Le logement",
        equipement: "Chauffage et isolation",
        adresse: "Adresse de la visite",
        conseiller: "Informations pour le conseiller",
      }).map(([group, title]) => (
        <fieldset className="qualification-group" key={group}>
          <legend>{title}</legend>
          <div className="qualification-grid">
            {schema.fields
              .filter(
                (field) =>
                  field.group === group && visibleField(field, value.answers),
              )
              .map((field) => {
                const props = {
                  value: value.answers[field.key] || "",
                  required: required && field.required,
                  "aria-label": field.label,
                  onChange: (
                    event: ChangeEvent<
                      HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
                    >,
                  ) => change(field.key, event.target.value),
                  onInvalid: (
                    event: InvalidEvent<
                      HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
                    >,
                  ) =>
                    event.currentTarget.setCustomValidity(
                      "Veuillez renseigner ce champ.",
                    ),
                  onInput: (
                    event: FormEvent<
                      HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
                    >,
                  ) => event.currentTarget.setCustomValidity(""),
                };
                return (
                  <label
                    key={field.key}
                    className={
                      field.key === "comments" ? "qualification-wide" : ""
                    }
                  >
                    <span>
                      {field.label}
                      {field.required ? " *" : ""}
                    </span>
                    {field.options ? (
                      <select {...props}>
                        <option value="">Choisir…</option>
                        {field.options.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                    ) : [
                        "comments",
                        "insulation",
                        "heating_comment",
                        "heat_pump_comment",
                      ].includes(field.key) ? (
                      <textarea {...props} maxLength={2000} rows={3} />
                    ) : (
                      <input {...props} maxLength={2000} type="text" />
                    )}
                  </label>
                );
              })}
          </div>
        </fieldset>
      ))}
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
        {schema.fields
          .filter(
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
