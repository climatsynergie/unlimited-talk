import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useState,
  useSyncExternalStore,
} from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import { PhoneController } from "./phone-controller";
import type {
  Intent,
  Session,
  MediaDevice,
  AutomaticTransport,
} from "./phone-controller";
import { createPhoneDevice } from "./phone-device";
import { Field, Notice } from "./ui";

const Context = createContext<PhoneController | null>(null);
export function makePhoneController(
  factory: (token: string) => Promise<MediaDevice> = createPhoneDevice,
) {
  return new PhoneController(
    {
      session: (signal) =>
        api<Session>("/telephony/test/session", {
          signal: AbortSignal.any([signal, AbortSignal.timeout(10000)]),
        }),
      reserve: (id, signal, destination, campaignId) =>
        api<{ intent: Intent; token: string }>("/telephony/test/intents", {
          method: "POST",
          body: {
            id,
            destination,
            ...(campaignId ? { campaign_id: campaignId } : {}),
          },
          signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]),
        }),
      cancel: (id, signal) =>
        api<Intent>(`/telephony/test/intents/${id}/cancel`, {
          method: "POST",
          body: {},
          signal: AbortSignal.any([signal, AbortSignal.timeout(10000)]),
        }),
      history: (id, signal) =>
        api<{ intent: Intent }>(`/telephony/test/intents/${id}`, {
          signal: AbortSignal.any([signal, AbortSignal.timeout(10000)]),
        }),
    },
    factory,
    {
      session: (signal) => api("/telephony/dialer/session", { signal }),
      control: (body, signal) =>
        api("/telephony/dialer/control", { method: "POST", body, signal }),
      heartbeat: (body, signal) =>
        api("/telephony/dialer/heartbeat", {
          method: "POST",
          body,
          signal: AbortSignal.any([signal, AbortSignal.timeout(10000)]),
        }),
      next: (body, signal) =>
        api("/telephony/dialer/next", {
          method: "POST",
          body,
          signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]),
        }),
    } satisfies AutomaticTransport,
  );
}
export function PhoneProvider({
  children,
  create = makePhoneController,
}: {
  children: ReactNode;
  create?: () => PhoneController;
}) {
  const [controller] = useState(create);
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  const active = state.phase !== "idle";
  useLayoutEffect(() => {
    controller.activate();
    function leaving() {
      controller.dispose();
    }
    function restored(event: PageTransitionEvent) {
      if (event.persisted) {
        controller.activate();
        if (controller.state.loaded) void controller.refresh();
      }
    }
    window.addEventListener("pagehide", leaving);
    window.addEventListener("pageshow", restored);
    window.addEventListener("ut-session-expired", leaving);
    return () => {
      window.removeEventListener("pagehide", leaving);
      window.removeEventListener("pageshow", restored);
      window.removeEventListener("ut-session-expired", leaving);
      controller.dispose();
    };
  }, [controller]);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void controller.refresh(), 2000);
    function warning(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    if (state.local) window.addEventListener("beforeunload", warning);
    return () => {
      clearInterval(timer);
      window.removeEventListener("beforeunload", warning);
    };
  }, [active, state.local, controller]);
  useEffect(() => {
    if (!state.automaticRunning && state.automatic?.mode !== "booking") return;
    void controller.automaticTick();
    const timer = window.setInterval(
      () => void controller.automaticTick(),
      2000,
    );
    return () => clearInterval(timer);
  }, [controller, state.automaticRunning, state.automatic?.mode]);
  return <Context.Provider value={controller}>{children}</Context.Provider>;
}
export function usePhone() {
  const controller = usePhoneController();
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  return { controller, state, busy: state.phase !== "idle" };
}
export function usePhoneController() {
  const controller = useContext(Context);
  if (!controller) throw new Error("Téléphone indisponible");
  return controller;
}
const labels = {
  idle: "Prêt",
  preparing: "Préparation de l’appel…",
  connecting: "Connexion de l’appel…",
  ringing: "Sonnerie chez le correspondant…",
  connected: "En conversation",
  reconnecting: "Connexion interrompue, rétablissement en cours…",
  ending: "Raccrochage demandé, confirmation en cours…",
  checking: "Vérification de l’appel en cours…",
};
const results: Record<string, string> = {
  completed: "Appel terminé.",
  busy: "Le correspondant est occupé.",
  "no-answer": "Le correspondant n’a pas répondu.",
  failed: "L’appel n’a pas abouti.",
  canceled: "Appel annulé.",
  cancelled: "Préparation annulée.",
  expired: "Préparation expirée.",
  finished: "Appel terminé.",
};
export function PhoneBar() {
  const { state, controller, busy } = usePhone();
  if (!busy) return null;
  return (
    <aside className="phone-bar" aria-label="Appel en cours">
      <div>
        <strong>{state.destination || "Appel téléphonique"}</strong>
        <p role="status">{labels[state.phase]}</p>
        {state.intent?.caller_number ? (
          <small>Numéro émetteur : {state.intent.caller_number}</small>
        ) : null}
      </div>
      {state.local ? (
        <button
          type="button"
          className="button danger"
          onClick={() => controller.hangup()}
        >
          Raccrocher
        </button>
      ) : null}
      <button
        type="button"
        className="button secondary"
        onClick={() => void controller.refresh()}
      >
        Vérifier l’appel
      </button>
    </aside>
  );
}
export function PhonePanel({
  input,
  beforeStart,
}: {
  input: string;
  beforeStart: () => void;
}) {
  const { state, controller, busy } = usePhone();
  useEffect(() => {
    void controller.refresh();
  }, [controller]);
  return (
    <section
      className="panel audio-panel audio-call-status"
      aria-labelledby="calls-heading"
    >
      <h2 id="calls-heading">Appels téléphoniques</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (
            !state.loaded ||
            !state.enabled ||
            busy ||
            state.automaticRunning ||
            !state.dialNumber.trim()
          )
            return;
          beforeStart();
          void controller.start(input);
        }}
      >
        <Field
          label="Numéro à appeler"
          name="dial_number"
          type="tel"
          autoComplete="off"
          inputMode="tel"
          placeholder="+1 514 555 0123"
          maxLength={40}
          value={state.dialNumber}
          disabled={busy}
          onChange={(event) => controller.setDialNumber(event.target.value)}
          hint="Saisissez le numéro avec son indicatif : +1 pour le Canada, +44 pour le Royaume-Uni."
        />
        {!state.loaded ? (
          <p role="status">Vérification du téléphone…</p>
        ) : !state.enabled ? (
          <p>Les appels ne sont pas encore activés.</p>
        ) : null}
        {state.enabled ? (
          <p className="audio-hint">
            Durée maximale par appel :{" "}
            {Math.floor(state.maxDurationSeconds / 60)} minutes. Les
            conversations sont enregistrées.
          </p>
        ) : null}
        {state.error ? <Notice error>{state.error}</Notice> : null}
        {state.result ? (
          <p role="status">{results[state.result] || "Appel terminé."}</p>
        ) : null}
        {busy && !state.local ? (
          <p>
            Une réservation est conservée. Aucun nouvel appel ne sera lancé
            avant sa résolution.
          </p>
        ) : null}
        <div className="audio-actions">
          <button
            type="submit"
            className="button success"
            disabled={
              !state.loaded ||
              !state.enabled ||
              busy ||
              state.automaticRunning ||
              !state.dialNumber.trim()
            }
          >
            Appeler
          </button>
          <button
            type="button"
            className="button secondary"
            onClick={() => void controller.refresh()}
          >
            Actualiser le téléphone
          </button>
          {state.intent?.state === "reserved" &&
          !state.local &&
          state.intent.owned_session !== false ? (
            <button
              type="button"
              className="button secondary"
              onClick={() => void controller.cancelPreparation()}
            >
              Annuler la préparation
            </button>
          ) : null}
        </div>
        {busy ? (
          <p className="audio-hint">
            Vous pouvez consulter les contacts et le calendrier pendant la
            conversation.
          </p>
        ) : null}
      </form>
    </section>
  );
}
