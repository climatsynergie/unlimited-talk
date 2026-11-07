import { useCallback, useEffect, useRef, useState } from "react";
import { api, message } from "./api";
import { usePhone } from "./Phone";
import { CallingSettingsDialog } from "./CallingSettings";
import { CallContactDialog } from "./Campaigns";
import { Notice } from "./ui";

type Campaign = {
  id: string;
  name: string;
  timezone: string;
  automatic_enabled: boolean;
};

type ContactSheet = {
  campaign: string;
  id: string;
  call: string;
  destination: string;
};

function AgentCallSheet({
  entry,
  current,
  admin,
  onEditingChange,
}: {
  entry: ContactSheet;
  current: boolean;
  admin: boolean;
  onEditingChange: (entry: ContactSheet, editing: boolean) => void;
}) {
  const { campaign, id, call, destination } = entry;
  const editing = useCallback(
    (value: boolean) =>
      onEditingChange({ campaign, id, call, destination }, value),
    [campaign, id, call, destination, onEditingChange],
  );
  return (
    <details
      className={current ? "current-call-sheet" : "previous-call-sheet"}
      open={current ? true : undefined}
    >
      <summary>
        {current
          ? "Fiche actuelle"
          : `Fiche précédente · ${destination} · À terminer`}
      </summary>
      <CallContactDialog
        campaignId={campaign}
        contactId={id}
        callId={call}
        admin={admin}
        inline
        onEditingChange={editing}
        onClose={() => editing(false)}
      />
    </details>
  );
}

export function AutoDialerPanel({
  admin,
  beforeStart,
}: {
  admin: boolean;
  beforeStart: () => void;
}) {
  const { controller, state, busy } = usePhone();
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [preparing, setPreparing] = useState(false);
  const [settings, setSettings] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, ContactSheet>>({});
  const [revision, setRevision] = useState(0);
  const lifetime = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    let pending = false;
    const refresh = () => {
      if (
        pending ||
        controller.signal.aborted ||
        document.visibilityState === "hidden"
      )
        return;
      pending = true;
      api<{ items: Campaign[] }>("/telephony/dialer/campaigns", {
        signal: controller.signal,
      })
        .then((result) => {
          if (!controller.signal.aborted) setCampaigns(result.items);
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError(message(e));
        })
        .finally(() => {
          pending = false;
          if (!controller.signal.aborted) setLoading(false);
        });
    };
    refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [revision]);
  useEffect(() => {
    void controller.refreshAutomatic();
    return () => {
      lifetime.current += 1;
    };
  }, [controller]);
  async function start() {
    if (preparing || !state.campaignId) return;
    const epoch = ++lifetime.current;
    setPreparing(true);
    setError("");
    beforeStart();
    try {
      // Ask on the explicit start gesture and release the probe immediately.
      // A denied/late microphone permission cannot start a server dialer run.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: state.inputDevice
          ? { deviceId: { exact: state.inputDevice } }
          : true,
        video: false,
      });
      stream.getTracks().forEach((track) => track.stop());
      if (epoch !== lifetime.current) return;
      await controller.startAutomatic(state.campaignId);
    } catch {
      if (epoch === lifetime.current)
        setError(
          "Autorisez et vérifiez le microphone avant de démarrer le composeur.",
        );
    } finally {
      if (epoch === lifetime.current) setPreparing(false);
    }
  }
  const mode = state.automatic?.mode || "stopped";
  const labels = {
    running: state.automaticRunning
      ? "Enchaînement actif"
      : "Actif dans une autre fenêtre ou à reprendre explicitement",
    paused: "En pause",
    stopped: "Arrêté",
    booking: "Suspendu pendant la saisie du rendez-vous",
  };
  const active = state.intent || state.lastIntent;
  const currentContact: ContactSheet | null =
    active?.campaign_id && active.contact_id
      ? {
          campaign: active.campaign_id,
          id: active.contact_id,
          call: active.id,
          destination: active.destination || "",
        }
      : null;
  const editingContact = useCallback(
    (entry: ContactSheet, editing: boolean) => {
      setDrafts((previous) => {
        if (!editing) {
          if (!previous[entry.call]) return previous;
          const next = { ...previous };
          delete next[entry.call];
          return next;
        }
        if (
          previous[entry.call]?.id === entry.id &&
          previous[entry.call]?.campaign === entry.campaign
        )
          return previous;
        return { ...previous, [entry.call]: entry };
      });
    },
    [],
  );
  const previousContacts = Object.values(drafts).filter(
    (entry) => entry.call !== currentContact?.call,
  );
  // Stable keys preserve each previous form when React moves it beneath the
  // current call. No field or late response can be transferred to another lead.
  const sheets = currentContact
    ? [currentContact, ...previousContacts]
    : previousContacts;
  const selectedCampaign = campaigns.find(
    (campaign) => campaign.id === state.campaignId,
  );
  const needsSettings =
    !!selectedCampaign && !selectedCampaign.automatic_enabled;
  return (
    <section
      className="panel audio-panel automatic-panel"
      aria-labelledby="automatic-heading"
    >
      <div className="automatic-title">
        <div>
          <span className="eyebrow">VOS APPELS SORTANTS</span>
          <h2 id="automatic-heading">Composeur automatique</h2>
        </div>
        <span className={`dialer-status dialer-status-${mode}`}>
          {labels[mode]}
        </span>
      </div>
      <p className="automatic-description">
        Les rappels dus de vos campagnes sont prioritaires. Les autres contacts
        suivent la file de la campagne choisie.
      </p>
      {error ? <Notice error>{error}</Notice> : null}
      {state.automaticError ? (
        <Notice error>{state.automaticError}</Notice>
      ) : null}
      {needsSettings ? (
        <Notice>
          {admin
            ? "Choisissez le numéro émetteur dans « Régler la téléphonie » pour démarrer cette campagne."
            : "Un administrateur doit choisir le numéro émetteur de cette campagne. La liste se met à jour automatiquement après son enregistrement."}
        </Notice>
      ) : null}
      <label className="automatic-campaign">
        Campagne d’appel
        <select
          value={state.campaignId}
          disabled={
            state.automaticRunning ||
            busy ||
            preparing ||
            state.automaticBusy ||
            loading
          }
          onChange={(e) => controller.setCampaignId(e.target.value)}
        >
          <option value="">Choisir une campagne</option>
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
              {c.automatic_enabled ? "" : " · composeur à configurer"}
            </option>
          ))}
        </select>
      </label>
      {loading ? (
        <p>Chargement des campagnes…</p>
      ) : !campaigns.length ? (
        <p>Aucune campagne active ne vous est attribuée.</p>
      ) : null}
      <p role="status" className="sr-only">
        {labels[mode]}
      </p>
      {state.automaticMessage ? <p>{state.automaticMessage}</p> : null}
      <div className="audio-actions">
        {preparing ? (
          <button
            type="button"
            className="button secondary"
            onClick={() => {
              lifetime.current += 1;
              setPreparing(false);
            }}
          >
            Annuler la vérification du microphone
          </button>
        ) : null}
        <button
          type="button"
          className="button success dialer-start"
          disabled={
            !state.enabled ||
            !state.loaded ||
            !state.automaticLoaded ||
            state.automaticBusy ||
            preparing ||
            busy ||
            !state.campaignId ||
            needsSettings ||
            state.automaticRunning
          }
          onClick={() => void start()}
        >
          {preparing
            ? "Vérification du microphone…"
            : mode === "paused" || mode === "booking"
              ? "Reprendre les appels"
              : "Démarrer les appels"}
        </button>
        <button
          type="button"
          className="button secondary"
          disabled={
            (!state.automaticRunning && mode !== "booking") ||
            state.automaticBusy
          }
          onClick={() => void controller.pauseAutomatic()}
        >
          Mettre en pause
        </button>
        <button
          type="button"
          className="button secondary"
          disabled={mode === "stopped" || state.automaticBusy}
          onClick={() => void controller.pauseAutomatic(true)}
        >
          Arrêter l’enchaînement
        </button>
        <button
          type="button"
          className="button secondary"
          disabled={preparing || state.automaticBusy}
          onClick={() => {
            setRevision((n) => n + 1);
            void controller.refreshAutomatic();
          }}
        >
          Actualiser le composeur
        </button>
        {admin ? (
          <button
            type="button"
            className="button secondary"
            disabled={!state.campaignId || state.automaticRunning}
            onClick={() => setSettings(true)}
          >
            Régler la téléphonie
          </button>
        ) : null}
      </div>
      <p className="audio-hint">
        Pause et arrêt empêchent le prochain appel. Utilisez « Raccrocher » pour
        terminer la conversation actuelle.
      </p>
      {active ? (
        <div className="confirmation-panel">
          <h3>{state.intent ? "Contact de l’appel" : "Dernier appel"}</h3>
          <p>
            {active.destination}
            {active.callback_id ? " · rappel programmé" : ""}
          </p>
          {active.caller_number ? (
            <p>Numéro émetteur : {active.caller_number}</p>
          ) : null}
        </div>
      ) : (
        <p className="audio-hint">
          La fiche du client apparaîtra ici dès le début d’un appel.
        </p>
      )}
      {settings && state.campaignId ? (
        <CallingSettingsDialog
          campaignId={state.campaignId}
          onClose={() => {
            setSettings(false);
            setRevision((n) => n + 1);
          }}
        />
      ) : null}
      {previousContacts.length ? (
        <p className="audio-hint" role="status">
          {previousContacts.length} fiche(s) précédente(s) à terminer, sous la
          fiche actuelle.
        </p>
      ) : null}
      {sheets.map((entry) => (
        <AgentCallSheet
          key={entry.call}
          entry={entry}
          current={entry.call === currentContact?.call}
          admin={admin}
          onEditingChange={editingContact}
        />
      ))}
    </section>
  );
}
