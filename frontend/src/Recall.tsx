import { useId } from "react";
import { usePhone } from "./Phone";
import { Icon, Notice } from "./ui";

export type RecallPhone = ReturnType<typeof usePhone>;

export function RecallButton({
  phone,
  number,
  blocked = false,
  name,
  label = "Rappeler",
  onOpen,
}: {
  phone: RecallPhone;
  number: string | null;
  blocked?: boolean;
  name?: string;
  label?: string;
  onOpen?: () => void;
}) {
  const { controller, state, busy } = phone;
  const hint = useId();
  const reason = blocked
    ? "Ne pas contacter"
    : !/^\+[1-9][0-9]{8,14}$/.test(number || "")
      ? "Numéro masqué ou invalide"
      : !state.loaded
        ? "Chargement du téléphone…"
        : !state.enabled
          ? "Téléphone indisponible"
          : busy
            ? "Un appel est déjà en cours"
            : state.automaticRunning
              ? "Mettez l’enchaînement en pause"
              : "";
  return (
    <div className="recall-action">
      <button
        type="button"
        className="button success recall-button"
        aria-label={name ? `${label} ${name}` : label}
        aria-describedby={reason ? hint : undefined}
        disabled={Boolean(reason)}
        onClick={() => {
          if (reason) return;
          onOpen?.();
          void controller.start(undefined, number!);
        }}
      >
        <Icon name="headset" />
        {label}
      </button>
      {reason ? (
        <small id={hint} className="recall-hint">
          {reason}
        </small>
      ) : null}
    </div>
  );
}

export function RecallControls({
  number,
  blocked = false,
  label,
}: {
  number: string | null;
  blocked?: boolean;
  label?: string;
}) {
  const phone = usePhone();
  const { controller, state } = phone;
  return (
    <div className="recall-controls">
      {state.error ? <Notice error>{state.error}</Notice> : null}
      <div className="actions contact-actions">
        <RecallButton
          phone={phone}
          number={number}
          blocked={blocked}
          label={label}
        />
        {state.local && state.destination === number ? (
          <>
            <button
              type="button"
              className="button danger"
              onClick={() => controller.hangup()}
            >
              Raccrocher
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={
                !state.intent ||
                state.voicemailPending.includes(state.intent.id)
              }
              onClick={() => void controller.voicemail()}
            >
              Boîte vocale
            </button>
          </>
        ) : null}
        {state.automaticRunning ? (
          <button
            type="button"
            className="button secondary"
            onClick={() => void controller.pauseAutomatic()}
          >
            Mettre l’enchaînement en pause
          </button>
        ) : null}
        <button
          type="button"
          className="text-button"
          onClick={() => void controller.refresh()}
        >
          Actualiser le téléphone
        </button>
      </div>
    </div>
  );
}
