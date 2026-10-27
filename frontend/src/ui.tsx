import { useId, useRef, useState } from "react";
import brandLogo from "./assets/unlimited-talks.svg";
import type { ReactNode, InputHTMLAttributes } from "react";

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        <img src={brandLogo} alt="" width="80" height="80" />
      </span>
      {compact ? null : (
        <span>
          Unlimited<span className="brand-light"> Talks</span>
        </span>
      )}
    </div>
  );
}
export function Icon({
  name,
}: {
  name:
    | "users"
    | "mail"
    | "shield"
    | "logout"
    | "arrow"
    | "check"
    | "home"
    | "campaign";
}) {
  const paths = {
    campaign: "M3 4h18v16H3zM9 4v16M15 4v16M5 8h2M11 8h2M17 8h2M5 12h2M11 12h2",
    users:
      "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 3a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.87M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
    mail: "M4 5h16v14H4zM4 6l8 7 8-7",
    shield: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3zM8 12l3 3 5-6",
    logout: "M9 21H4V3h5M14 7l5 5-5 5M8 12h11",
    arrow: "M5 12h14M13 6l6 6-6 6",
    check: "M5 12l4 4L19 6",
    home: "M3 10l9-7 9 7M5 9v12h14V9M9 21v-7h6v7",
  };
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
function localizeValidity(input: HTMLInputElement) {
  const state = input.validity;
  const text = state.valueMissing
    ? "Veuillez renseigner ce champ."
    : state.typeMismatch && input.type === "email"
      ? "Saisissez une adresse courriel valide."
      : state.tooShort
        ? `Saisissez au moins ${input.minLength} caractères.`
        : state.tooLong
          ? `Saisissez au maximum ${input.maxLength} caractères.`
          : state.patternMismatch
            ? "Respectez le format indiqué pour ce champ."
            : "Vérifiez la valeur saisie.";
  input.setCustomValidity(text);
}

export function Field({
  label,
  hint,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        {...props}
        id={id}
        onInvalid={(event) => {
          localizeValidity(event.currentTarget);
          props.onInvalid?.(event);
        }}
        onInput={(event) => {
          event.currentTarget.setCustomValidity("");
          props.onInput?.(event);
        }}
        aria-describedby={hint ? `${id}-hint` : undefined}
      />
      {hint ? <small id={`${id}-hint`}>{hint}</small> : null}
    </div>
  );
}
export function Password({
  label = "Mot de passe",
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label?: string }) {
  const [visible, setVisible] = useState(false);
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="password-wrap">
        <input
          {...props}
          id={id}
          type={visible ? "text" : "password"}
          onInvalid={(event) => {
            localizeValidity(event.currentTarget);
            props.onInvalid?.(event);
          }}
          onInput={(event) => {
            event.currentTarget.setCustomValidity("");
            props.onInput?.(event);
          }}
        />

        <button
          type="button"
          className="password-toggle"
          onClick={() => setVisible(!visible)}
          aria-label={
            visible ? "Masquer le mot de passe" : "Afficher le mot de passe"
          }
          aria-pressed={visible}
        >
          {visible ? "Masquer" : "Afficher"}
        </button>
      </div>
    </div>
  );
}
export function Notice({
  children,
  error = false,
}: {
  children: ReactNode;
  error?: boolean;
}) {
  return (
    <div
      className={`notice ${error ? "notice-error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {children}
    </div>
  );
}
export function Submit({
  busy,
  disabled = false,
  children,
}: {
  busy: boolean;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      className="button primary"
      type="submit"
      disabled={busy || disabled}
      aria-busy={busy}
    >
      {busy ? "Veuillez patienter…" : children}
      <Icon name="arrow" />
    </button>
  );
}
export function Modal({
  title,
  children,
  onClose,
  busy = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  return (
    <dialog
      ref={(node) => {
        ref.current = node;
        if (node && !node.open) node.showModal();
      }}
      aria-labelledby={id}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
      onClose={onClose}
    >
      <div className="modal-heading">
        <h2 id={id}>{title}</h2>
        <button
          type="button"
          className="close"
          aria-label="Fermer la fenêtre"
          onClick={onClose}
          disabled={busy}
        >
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}
