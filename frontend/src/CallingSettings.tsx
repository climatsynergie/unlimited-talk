import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, message } from "./api";
import { Modal, Notice, Submit } from "./ui";

type NumberItem = {
  id: string;
  number: string;
  name: string;
  country: string;
  voice_enabled: boolean;
  is_present: boolean;
  is_active: boolean;
  fresh: boolean;
  in_grace?: boolean;
};
type Window = { weekday: number; start: number; end: number };
type Rule = { number_id: string; country: string; prefix: string };
type Settings = {
  version: number;
  enabled: boolean;
  default_number_id: string | null;
  hours: Window[];
  rules: Rule[];
  policy?: {
    attempts_per_day: number;
    retry_minutes: number;
    ring_seconds: number;
  };
};
export type Directory = {
  items: NumberItem[];
  configured: boolean;
  warning?: { severity: string; message: string } | null;
  sync: {
    synchronized_at: string | null;
    last_error_code: string | null;
    syncing: boolean;
  } | null;
};
const usable = (number: NumberItem) =>
  number.voice_enabled &&
  number.is_present &&
  number.is_active &&
  (number.fresh || number.in_grace);

export function CallingSettingsDialog({
  campaignId,
  onClose,
}: {
  campaignId: string;
  onClose: () => void;
}) {
  const [directory, setDirectory] = useState<Directory | null>(null);
  const [version, setVersion] = useState(0);
  const [defaultNumber, setDefaultNumber] = useState("");
  const [policy, setPolicy] = useState({
    attempts_per_day: 2,
    retry_minutes: 120,
    ring_seconds: 35,
  });
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
        if (settings.policy) setPolicy(settings.policy);
        setDefaultNumber(
          settings.default_number_id || numbers.items.find(usable)?.id || "",
        );
        setDirectory(numbers);
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
            enabled: true,
            default_number_id: defaultNumber || null,
            hours: [],
            rules: [],
            policy,
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
      {directory?.warning ? (
        <Notice error={directory.warning.severity === "critical"}>
          {directory.warning.message}
        </Notice>
      ) : null}
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
            Choisissez le numéro qui sera affiché lors des appels de cette
            campagne.
          </p>
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
              <label>
                Numéro émetteur
                <select
                  value={defaultNumber}
                  onChange={(e) => {
                    changed();
                    setDefaultNumber(e.target.value);
                  }}
                  required
                >
                  <option value="">Choisir un numéro</option>
                  {options()}
                </select>
              </label>
              <details className="calling-policy">
                <summary>Tentatives et sonnerie</summary>
                <p>
                  Les tentatives et le délai concernent la prospection
                  automatique. La sonnerie s’applique aux appels de cette
                  campagne, y compris manuels. Les rappels programmés sont
                  prioritaires à l’heure choisie, lorsque l’agent est
                  disponible.
                </p>
                {(
                  [
                    [
                      "attempts_per_day",
                      "Tentatives maximum par numéro et par jour",
                      1,
                      20,
                    ],
                    [
                      "retry_minutes",
                      "Délai entre tentatives (minutes)",
                      0,
                      1440,
                    ],
                    ["ring_seconds", "Durée de sonnerie (secondes)", 15, 60],
                  ] as const
                ).map(([key, label, min, max]) => (
                  <label key={key}>
                    {label}
                    <input
                      type="number"
                      min={min}
                      max={max}
                      step={1}
                      required
                      value={Number.isNaN(policy[key]) ? "" : policy[key]}
                      onChange={(e) => {
                        changed();
                        setPolicy((old) => ({
                          ...old,
                          [key]:
                            e.target.value === ""
                              ? NaN
                              : Number(e.target.value),
                        }));
                      }}
                    />
                  </label>
                ))}
              </details>
            </fieldset>
            <Submit busy={busy}>Enregistrer la téléphonie</Submit>
          </form>
          <button
            type="button"
            className="text-button"
            disabled={!directory?.configured || syncing || busy}
            onClick={() => void synchronize()}
          >
            {syncing ? "Actualisation…" : "Actualiser la liste des numéros"}
          </button>
        </>
      )}
    </Modal>
  );
}
