import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, message } from "./api";
import { Field, Modal, Notice, Submit } from "./ui";

type NumberItem = {
  id: string;
  number: string;
  name: string;
  country: string;
  voice_enabled: boolean;
  is_present: boolean;
  is_active: boolean;
  fresh: boolean;
};
type Window = { weekday: number; start: number; end: number };
type Rule = { number_id: string; country: string; prefix: string };
type Settings = {
  version: number;
  enabled: boolean;
  default_number_id: string | null;
  hours: Window[];
  rules: Rule[];
};
type Directory = {
  items: NumberItem[];
  configured: boolean;
  sync: {
    synchronized_at: string | null;
    last_error_code: string | null;
    syncing: boolean;
  } | null;
};
const days = [
  "Lundi",
  "Mardi",
  "Mercredi",
  "Jeudi",
  "Vendredi",
  "Samedi",
  "Dimanche",
];
const clock = (minute: number) =>
  `${String(Math.floor(minute / 60) % 24).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
const minutes = (value: string) => {
  const [h, m] = value.split(":").map(Number);
  return h * 60 + m;
};
const usable = (number: NumberItem) =>
  number.voice_enabled && number.is_present && number.is_active && number.fresh;

export function CallingSettingsDialog({
  campaignId,
  onClose,
}: {
  campaignId: string;
  onClose: () => void;
}) {
  const [directory, setDirectory] = useState<Directory | null>(null);
  const [version, setVersion] = useState(0);
  const [enabled, setEnabled] = useState(false);
  const [defaultNumber, setDefaultNumber] = useState("");
  const [hours, setHours] = useState<(Window & { key: string })[]>([]);
  const [rules, setRules] = useState<(Rule & { key: string })[]>([]);
  const [zone, setZone] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const lifetime = useRef<AbortController | null>(null);
  const requestId = useRef(crypto.randomUUID());
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    let refreshing = false;
    Promise.all([
      api<{ settings: Settings; timezone: string }>(
        `/telephony/campaigns/${campaignId}/calling`,
        { signal: controller.signal },
      ),
      api<Directory>("/telephony/numbers", { signal: controller.signal }),
    ])
      .then(([result, numbers]) => {
        if (controller.signal.aborted) return;
        const settings = result.settings;
        setVersion(settings.version);
        setEnabled(settings.enabled);
        setDefaultNumber(settings.default_number_id || "");
        setHours(
          settings.hours.map((h) => ({ ...h, key: crypto.randomUUID() })),
        );
        setRules(
          settings.rules.map((r) => ({ ...r, key: crypto.randomUUID() })),
        );
        setDirectory(numbers);
        setZone(result.timezone);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    const timer = window.setInterval(async () => {
      if (refreshing || document.visibilityState === "hidden") return;
      refreshing = true;
      try {
        const result = await api<Directory>("/telephony/numbers", {
          signal: controller.signal,
        });
        if (!controller.signal.aborted) setDirectory(result);
      } catch {
        /* Keep the existing directory visible; save independently revalidates it. */
      } finally {
        refreshing = false;
      }
    }, 5000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [campaignId]);
  function changed() {
    requestId.current = crypto.randomUUID();
    setNotice("");
  }
  async function synchronize() {
    const signal = lifetime.current?.signal;
    if (!signal || signal.aborted) return;
    setSyncing(true);
    setError("");
    try {
      await api("/telephony/numbers/synchronize", {
        method: "POST",
        body: {},
        signal,
      });
      if (!signal.aborted)
        setNotice(
          "Synchronisation demandée. La liste se mettra à jour automatiquement.",
        );
    } catch (e) {
      if (!signal.aborted) setError(message(e));
    } finally {
      if (!signal.aborted) setSyncing(false);
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    const signal = lifetime.current?.signal;
    if (busy || !signal || signal.aborted) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ settings: Settings }>(
        `/telephony/campaigns/${campaignId}/calling`,
        {
          method: "PUT",
          signal,
          body: {
            request_id: requestId.current,
            version,
            enabled,
            default_number_id: defaultNumber || null,
            hours: hours.map(({ weekday, start, end }) => ({
              weekday,
              start,
              end,
            })),
            rules: rules.map(({ number_id, country, prefix }) => ({
              number_id,
              country,
              prefix,
            })),
          },
        },
      );
      if (signal.aborted) return;
      setVersion(result.settings.version);
      requestId.current = crypto.randomUUID();
      setNotice("Réglages téléphoniques enregistrés.");
    } catch (e) {
      if (!signal.aborted) setError(message(e));
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  }
  function options() {
    return directory?.items.map((number) => (
      <option key={number.id} value={number.id} disabled={!usable(number)}>
        {number.number} · {number.name || number.country}
        {usable(number) ? "" : " · indisponible"}
      </option>
    ));
  }
  return (
    <Modal title="Téléphonie de la campagne" onClose={onClose} busy={busy}>
      {error ? <Notice error>{error}</Notice> : null}
      {notice ? <Notice>{notice}</Notice> : null}
      {loading ? (
        <p>Chargement des réglages…</p>
      ) : !directory ? (
        <p>
          Les réglages n’ont pas pu être chargés. Fermez puis rouvrez cette
          fenêtre pour réessayer.
        </p>
      ) : (
        <>
          <p>
            Les numéros proviennent de votre compte Twilio. Leur sélection
            conserve les routes téléphoniques existantes.
          </p>
          <button
            type="button"
            className="button secondary"
            disabled={!directory?.configured || syncing || busy}
            onClick={() => void synchronize()}
          >
            {syncing ? "Demande en cours…" : "Actualiser les numéros Twilio"}
          </button>
          {!directory?.configured ? (
            <Notice>
              La connexion Twilio doit être activée pour récupérer les numéros.
            </Notice>
          ) : null}
          {directory?.sync?.last_error_code ? (
            <Notice error>
              La synchronisation des numéros a échoué. La dernière liste reste
              affichée ; une reprise est prévue.
            </Notice>
          ) : null}
          {directory?.configured && !directory.items.length ? (
            <p>
              Aucun numéro vérifié disponible. Lancez la synchronisation avant
              de configurer les appels.
            </p>
          ) : null}
          <form className="campaign-form" onSubmit={save}>
            <fieldset disabled={busy}>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => {
                    changed();
                    setEnabled(e.target.checked);
                  }}
                />
                Autoriser le composeur automatique pour cette campagne
              </label>
              <label>
                Numéro émetteur par défaut
                <select
                  value={defaultNumber}
                  onChange={(e) => {
                    changed();
                    setDefaultNumber(e.target.value);
                  }}
                  required={enabled}
                >
                  <option value="">Choisir un numéro</option>
                  {options()}
                </select>
              </label>
              <h3>Horaires d’appel</h3>
              <p>
                Fuseau de la campagne : {zone}. Deux tentatives maximum par
                numéro et par jour ; deux heures minimum entre tentatives.
              </p>
              {hours.map((window, index) => (
                <div className="confirmation-panel" key={window.key}>
                  <label>
                    Jour de la plage {index + 1}
                    <select
                      value={window.weekday}
                      onChange={(e) => {
                        changed();
                        setHours((old) =>
                          old.map((h) =>
                            h.key === window.key
                              ? { ...h, weekday: Number(e.target.value) }
                              : h,
                          ),
                        );
                      }}
                    >
                      {days.map((day, i) => (
                        <option key={day} value={i}>
                          {day}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Field
                    label={`Début de la plage ${index + 1}`}
                    type="time"
                    required
                    value={clock(window.start)}
                    onChange={(e) => {
                      changed();
                      setHours((old) =>
                        old.map((h) =>
                          h.key === window.key
                            ? { ...h, start: minutes(e.target.value) }
                            : h,
                        ),
                      );
                    }}
                  />
                  <Field
                    label={`Fin de la plage ${index + 1}`}
                    type="time"
                    required
                    value={clock(window.end)}
                    onChange={(e) => {
                      changed();
                      setHours((old) =>
                        old.map((h) =>
                          h.key === window.key
                            ? { ...h, end: minutes(e.target.value) || 1440 }
                            : h,
                        ),
                      );
                    }}
                  />
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => {
                      changed();
                      setHours((old) =>
                        old.filter((h) => h.key !== window.key),
                      );
                    }}
                  >
                    Supprimer la plage {index + 1}
                  </button>
                </div>
              ))}
              <p className="audio-hint">
                Une fin à 00:00 signifie la fin de cette journée. Séparez une
                plage de nuit en deux journées.
              </p>
              <button
                type="button"
                className="button secondary"
                disabled={hours.length >= 14}
                onClick={() => {
                  changed();
                  setHours((old) => [
                    ...old,
                    {
                      key: crypto.randomUUID(),
                      weekday: 0,
                      start: 540,
                      end: 1020,
                    },
                  ]);
                }}
              >
                Ajouter une plage horaire
              </button>
              <h3>Numéros par région</h3>
              <p>
                Le préfixe le plus précis est prioritaire. Sans correspondance,
                le numéro par défaut est utilisé.
              </p>
              {rules.map((rule, index) => (
                <div className="confirmation-panel" key={rule.key}>
                  <Field
                    label={`Pays de la règle ${index + 1} (optionnel)`}
                    maxLength={2}
                    placeholder="CA, GB, US…"
                    value={rule.country}
                    onChange={(e) => {
                      changed();
                      setRules((old) =>
                        old.map((r) =>
                          r.key === rule.key
                            ? { ...r, country: e.target.value.toUpperCase() }
                            : r,
                        ),
                      );
                    }}
                  />
                  <Field
                    label={`Préfixe de la règle ${index + 1} (optionnel)`}
                    type="tel"
                    maxLength={15}
                    placeholder="+1514 ou +44"
                    value={rule.prefix}
                    onChange={(e) => {
                      changed();
                      setRules((old) =>
                        old.map((r) =>
                          r.key === rule.key
                            ? { ...r, prefix: e.target.value }
                            : r,
                        ),
                      );
                    }}
                  />
                  <label>
                    Numéro de la règle {index + 1}
                    <select
                      required
                      value={rule.number_id}
                      onChange={(e) => {
                        changed();
                        setRules((old) =>
                          old.map((r) =>
                            r.key === rule.key
                              ? { ...r, number_id: e.target.value }
                              : r,
                          ),
                        );
                      }}
                    >
                      <option value="">Choisir un numéro</option>
                      {options()}
                    </select>
                  </label>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => {
                      changed();
                      setRules((old) => old.filter((r) => r.key !== rule.key));
                    }}
                  >
                    Supprimer la règle {index + 1}
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="button secondary"
                disabled={rules.length >= 50}
                onClick={() => {
                  changed();
                  setRules((old) => [
                    ...old,
                    {
                      key: crypto.randomUUID(),
                      country: "",
                      prefix: "",
                      number_id: "",
                    },
                  ]);
                }}
              >
                Ajouter une règle régionale
              </button>
            </fieldset>
            <Submit busy={busy}>Enregistrer la téléphonie</Submit>
          </form>
        </>
      )}
    </Modal>
  );
}
