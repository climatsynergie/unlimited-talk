import { useEffect } from "react";
import { useIncomingPhone } from "./Phone";
import { Notice } from "./ui";
const labels = {
  idle: "Prêt à recevoir",
  registering: "Connexion du téléphone…",
  ringing: "Appel entrant",
  connecting: "Connexion de l’appel…",
  connected: "En conversation",
  reconnecting: "Rétablissement de la connexion…",
  checking: "Vérification de l’appel…",
};
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
          {state.wanted && state.registered
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
  if (!state.offer && !state.local) return null;
  return (
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
            (state.offer ? "Numéro masqué" : "Identification de l’appelant…")}
        </strong>
        <p role="status">{labels[state.phase]}</p>
        {state.offer ? (
          <small>Ligne : {state.offer.called_number}</small>
        ) : null}
      </div>
      <div className="actions">
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
          <button className="button danger" onClick={() => controller.hangup()}>
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
  );
}
