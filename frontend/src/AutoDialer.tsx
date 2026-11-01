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
  const [contact, setContact] = useState<{
    campaign: string;
    id: string;
  } | null>(null);
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
  const shownCampaign = contact?.campaign || active?.campaign_id;
  const shownContact = contact?.id || active?.contact_id;
  const editingContact = useCallback(
    (editing: boolean) => {
      setContact((previous) => {
        if (!editing || !shownCampaign || !shownContact) return null;
        if (
          previous?.campaign === shownCampaign &&
          previous.id === shownContact
        )
          return previous;
        return { campaign: shownCampaign, id: shownContact };
      });
    },
    [shownCampaign, shownContact],
  );
  const previousContact =
    !!contact &&
    !!active &&
    (contact.campaign !== active.campaign_id ||
      contact.id !== active.contact_id);
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
      <p>
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
      <label>
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
          className="button primary dialer-start"
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
      {previousContact ? (
        <Notice>
          Vous complétez encore la fiche du contact précédent. Enregistrez la
          note, enregistrez la qualification ou terminez le formulaire pour
          afficher le contact de l’appel en cours.
        </Notice>
      ) : null}
      {shownCampaign && shownContact ? (
        <CallContactDialog
          key={`${shownCampaign}-${shownContact}`}
          campaignId={shownCampaign}
          contactId={shownContact}
          admin={admin}
          inline
          onEditingChange={editingContact}
          onClose={() => setContact(null)}
        />
      ) : null}
    </section>
  );
}
