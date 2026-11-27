import { useEffect, useState } from "react";
import { useIncomingPhone } from "./Phone";
import { InboundBooking } from "./InboundBooking";
import { Modal, Notice } from "./ui";
const labels = {
  idle: "Prêt à recevoir",
  registering: "Connexion du téléphone…",
  ringing: "Appel entrant",
  connecting: "Connexion de l’appel…",
  connected: "En conversation",
  reconnecting: "Rétablissement de la connexion…",
  checking: "Vérification de l’appel…",
};
export function ReceptionStatus({
  enabled,
  showErrors,
}: {
  enabled: boolean;
  showErrors: boolean;
}) {
  const { controller, state } = useIncomingPhone();
  useEffect(() => {
    if (enabled && !state.loaded) void controller.prepare();
  }, [controller, enabled, state.loaded]);
  if (!state.loaded || (!enabled && !state.enabled && !state.queues.length))
    return null;
  const ready = state.wanted && state.registered && !state.recovering;
  const connecting = state.phase === "registering";
  return (
    <div
      className={`reception-presence ${ready ? "is-ready" : "is-paused"}`}
      role="group"
      aria-label="État de la réception"
    >
      <span className="reception-presence-dot" aria-hidden="true" />
      <span role="status">
        {ready
          ? "Réception active"
          : connecting || state.wanted
            ? "Connexion de la réception…"
            : "Réception suspendue"}
      </span>
      <button
        type="button"
        className="text-button"
        disabled={(!enabled && !state.enabled) || connecting}
        onClick={() =>
          void (state.wanted ? controller.pause() : controller.start())
        }
      >
        {state.wanted ? "Suspendre la réception" : "Activer la réception"}
      </button>
      {showErrors && state.error ? (
        <span role="alert" className="reception-presence-error">
          {state.error}
        </span>
      ) : null}
    </div>
  );
}
export function ReceptionControl() {
  const { controller, state } = useIncomingPhone();
  useEffect(() => {
    void controller.prepare();
  }, [controller]);
  return (
    <section className="panel reception-control" aria-label="Votre réception">
      <div>
        <span className="eyebrow">VOTRE TÉLÉPHONE</span>
        <h2>Recevoir les appels</h2>
        <p className="muted">
          Les appels des lignes qui vous sont attribuées sonnent ici. La
          réception reste ouverte lorsque vous changez de page.
        </p>
        <p role="status">
          {state.wanted &&
          (state.recovering || !state.registered) &&
          state.phase !== "registering"
            ? "Reconnexion automatique…"
            : state.wanted && state.registered
              ? "Réception ouverte"
              : state.phase === "registering"
                ? labels.registering
                : "Réception en pause"}
        </p>
        {state.queues.length ? (
          <small>{state.queues.map((q) => q.name).join(" · ")}</small>
        ) : null}
      </div>
      <div className="actions">
        {state.wanted ? (
          <button
            className="button secondary"
            onClick={() => void controller.pause()}
          >
            Mettre la réception en pause
          </button>
        ) : (
          <button
            className="button primary"
            disabled={
              !state.loaded || !state.enabled || state.phase === "registering"
            }
            onClick={() => void controller.start()}
          >
            Recevoir les appels
          </button>
        )}
        <button
          className="text-button"
          onClick={() => void controller.prepare()}
        >
          Vérifier la réception
        </button>
      </div>
      {state.loaded && !state.enabled ? (
        <p className="muted">
          Une ligne connectée et une attribution à votre compte sont nécessaires
          pour recevoir les appels.
        </p>
      ) : null}
      {state.error ? <Notice error>{state.error}</Notice> : null}
    </section>
  );
}
export function IncomingPhoneBar() {
  const { controller, state } = useIncomingPhone();
  const [qualification, setQualification] = useState<{
    id: string;
    number: string;
  } | null>(null);
  const [qualificationBusy, setQualificationBusy] = useState(false);
  if (!state.offer && !state.local && !qualification) return null;
  return (
    <>
      {state.offer || state.local ? (
        <aside
          className="phone-bar incoming-phone-bar"
          aria-label="Appel entrant en cours"
        >
          <div>
            <span className="eyebrow">
              APPEL ENTRANT · {state.offer?.queue_name}
            </span>
            <strong>
              {state.offer?.caller_number ||
                (state.offer
                  ? "Numéro masqué"
                  : "Identification de l’appelant…")}
            </strong>
            <p role="status">{labels[state.phase]}</p>
            {state.offer ? (
              <small>Ligne : {state.offer.called_number}</small>
            ) : null}
          </div>
          <div className="actions">
            {state.local && state.offer?.caller_number ? (
              <button
                className="button success"
                onClick={() =>
                  setQualification({
                    id: state.offer!.call_id,
                    number: state.offer!.caller_number!,
                  })
                }
              >
                Fiche client / Prendre rendez-vous
              </button>
            ) : null}
            {state.phase === "ringing" ? (
              <>
                <button
                  className="button primary"
                  onClick={() => void controller.accept()}
                >
                  Répondre
                </button>
                <button
                  className="button secondary"
                  onClick={() => controller.reject()}
                >
                  Refuser
                </button>
              </>
            ) : state.local ? (
              <button
                className="button danger"
                onClick={() => controller.hangup()}
              >
                Raccrocher
              </button>
            ) : null}
            <button
              className="button secondary"
              onClick={() => void controller.tick()}
            >
              Vérifier l’appel
            </button>
          </div>
          {state.error ? <p role="alert">{state.error}</p> : null}
        </aside>
      ) : null}
      {qualification ? (
        <Modal
          title={`Qualification — ${qualification.number}`}
          onClose={() => setQualification(null)}
          busy={qualificationBusy}
        >
          <InboundBooking
            key={qualification.id}
            id={qualification.id}
            source="calls"
            initiallyOpen
            allowed
            onBusy={setQualificationBusy}
            onBooked={() => {
              setQualificationBusy(false);
              setQualification(null);
            }}
          />
        </Modal>
      ) : null}
    </>
  );
}
