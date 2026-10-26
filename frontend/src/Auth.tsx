import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { api, message } from "./api";
import type { Identity } from "./api";
import { Brand, Field, Icon, Notice, Password, Submit } from "./ui";

export type PrivateEntry = {
  kind: "invitation" | "reinitialisation";
  token: string;
} | null;
export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="auth-layout">
      <aside className="auth-story">
        <Brand />
        <div className="story-copy">
          <span className="eyebrow">VOTRE ÉQUIPE. VOS CONVERSATIONS.</span>
          <h1>
            Les bonnes conversations
            <br />
            <em>commencent ici.</em>
          </h1>
          <p>
            Un espace commun pour votre équipe,
            <br />
            et une connexion qui vous appartient.
          </p>
          <div className="story-illustration" aria-hidden="true">
            <span className="orbit orbit-one" />
            <span className="orbit orbit-two" />
            <div className="conversation-card">
              <span className="avatar avatar-purple">UT</span>
              <div>
                <strong>Une équipe, un espace.</strong>
                <span>Unlimited Talks</span>
              </div>
              <span className="online-dot" />
            </div>
            <div className="security-card">
              <Icon name="shield" />
              <span>Un accès personnel et protégé</span>
            </div>
          </div>
        </div>
        <div className="story-footer">
          <span>Unlimited Talks</span>
          <span>Environnement de préproduction</span>
        </div>
      </aside>
      <main className="auth-main" id="main">
        <div className="mobile-brand">
          <Brand />
        </div>
        <div className="auth-top">
          <span className="environment">
            <span />
            PRÉPRODUCTION
          </span>
          <span className="subtle">Accès réservé à votre équipe</span>
        </div>
        <div className="auth-card">{children}</div>
        <footer className="auth-footer">
          <Icon name="shield" />
          Connexion sécurisée · Accès sur invitation
        </footer>
      </main>
    </div>
  );
}

export function AuthForm({
  entry,
  notice,
  onIdentity,
  onCancel,
}: {
  entry: PrivateEntry;
  notice: string;
  onIdentity: (identity: Identity) => void;
  onCancel: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [forgot, setForgot] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const password = String(fields.get("password") ?? "");
    if (entry && password !== fields.get("confirmation")) {
      setError("Les mots de passe doivent être identiques.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api<Identity>(
        entry?.kind === "invitation"
          ? "/auth/invitations/accept"
          : entry
            ? "/auth/password-reset"
            : "/auth/login",
        {
          method: "POST",
          authenticated: false,
          body: entry
            ? {
                token: entry.token,
                password,
                ...(entry.kind === "reinitialisation"
                  ? { factor: String(fields.get("factor") ?? "").trim() }
                  : {}),
              }
            : {
                email: fields.get("email"),
                password,
                factor: String(fields.get("factor") ?? "").trim(),
              },
        },
      );
      form.reset();
      onIdentity(result);
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  const title =
    entry?.kind === "invitation"
      ? "Bienvenue dans l’équipe."
      : entry
        ? "Un nouveau mot de passe."
        : "Heureux de vous retrouver.";
  return (
    <>
      <div className="section-symbol">
        <Icon name={entry?.kind === "invitation" ? "mail" : "shield"} />
      </div>
      <span className="eyebrow">VOTRE ESPACE UNLIMITED TALKS</span>
      <h2>{title}</h2>
      <p className="intro">
        {entry?.kind === "invitation"
          ? "Choisissez votre mot de passe personnel pour accepter votre invitation."
          : entry
            ? "Choisissez un nouveau mot de passe pour retrouver votre espace."
            : "Connectez-vous avec votre compte personnel."}
      </p>
      {notice ? <Notice>{notice}</Notice> : null}
      {error ? <Notice error>{error}</Notice> : null}
      {entry && !entry.token ? (
        <>
          <Notice error>
            Ce lien est incomplet. Demandez un nouveau lien privé à votre
            administrateur.
          </Notice>
          <button type="button" className="button primary" onClick={onCancel}>
            Retour à la connexion
          </button>
        </>
      ) : (
        <form method="post" onSubmit={submit}>
          {entry ? null : (
            <Field
              label="Adresse courriel"
              name="email"
              type="email"
              autoComplete="username"
              placeholder="vous@entreprise.com"
              maxLength={254}
              required
            />
          )}
          <Password
            name="password"
            autoComplete={entry ? "new-password" : "current-password"}
            minLength={entry ? 12 : 1}
            maxLength={128}
            required
            label={entry ? "Nouveau mot de passe" : "Mot de passe"}
          />
          {entry ? (
            <>
              <small className="password-hint">
                Au moins 12 caractères. Une phrase longue convient très bien.
              </small>
              <Password
                name="confirmation"
                label="Confirmer le mot de passe"
                autoComplete="new-password"
                minLength={12}
                maxLength={128}
                required
              />
            </>
          ) : null}
          {entry?.kind === "invitation" ? null : (
            <Field
              label="Code d’authentification ou de récupération"
              name="factor"
              type="text"
              autoComplete="one-time-code"
              maxLength={64}
              spellCheck={false}
              hint="Obligatoire pour les administrateurs ayant activé la double authentification."
            />
          )}
          <Submit busy={busy}>
            {entry?.kind === "invitation"
              ? "Accepter l’invitation"
              : entry
                ? "Enregistrer mon mot de passe"
                : "Se connecter"}
          </Submit>
        </form>
      )}
      {entry?.token ? (
        <button
          type="button"
          className="text-button centered"
          onClick={onCancel}
        >
          Revenir à la connexion
        </button>
      ) : entry ? null : (
        <>
          <button
            className="text-button centered"
            type="button"
            onClick={() => setForgot(!forgot)}
            aria-expanded={forgot}
          >
            Mot de passe oublié ?
          </button>
          {forgot ? (
            <Notice>
              Votre administrateur peut vous transmettre un lien privé de
              réinitialisation. Votre code d’authentification reste nécessaire
              si vous l’avez activé.
            </Notice>
          ) : null}
          <div className="invitation-note">
            <Icon name="mail" />
            <p>
              Vous rejoignez l’équipe ?<br />
              <span>
                Utilisez le lien d’invitation de votre administrateur.
              </span>
            </p>
          </div>
        </>
      )}
    </>
  );
}

export function Enrollment({
  onIdentity,
  onLogout,
}: {
  onIdentity: (identity: Identity) => void;
  onLogout: () => void;
}) {
  const [setup, setSetup] = useState<{
    secret: string;
    provisioning_uri: string;
  } | null>(null);
  const [qr, setQr] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function start() {
    setBusy(true);
    setError("");
    try {
      const data = await api<{ secret: string; provisioning_uri: string }>(
        "/auth/mfa/enroll",
        { method: "POST", body: {} },
      );
      setSetup(data);
      try {
        const QR = await import("qrcode");
        setQr(
          await QR.toDataURL(data.provisioning_uri, { width: 220, margin: 2 }),
        );
      } catch {
        /* Manual entry remains available. */
      }
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Identity>("/auth/mfa/confirm", {
        method: "POST",
        body: { code: new FormData(event.currentTarget).get("code") },
      });
      onIdentity(result);
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="section-symbol">
        <Icon name="shield" />
      </div>
      <span className="eyebrow">PROTÉGEZ VOTRE COMPTE</span>
      <h2>Une sécurité en plus.</h2>
      <p className="intro">
        Votre accès administrateur nécessite un code d’authentification en plus
        de votre mot de passe.
      </p>
      {error ? <Notice error>{error}</Notice> : null}
      {setup ? (
        <>
          <div className="mfa-setup">
            {qr ? (
              <img
                src={qr}
                width="220"
                height="220"
                alt="Code QR à scanner dans votre application d’authentification"
              />
            ) : null}
            <p>
              Scannez le QR code, ou saisissez cette clé dans votre application
              d’authentification :
            </p>
            <code className="secret-key">{setup.secret}</code>
          </div>
          <form method="post" onSubmit={confirm}>
            <Field
              label="Code à 6 chiffres"
              name="code"
              required
              inputMode="numeric"
              pattern="[0-9]{6}"
              minLength={6}
              maxLength={6}
              autoComplete="one-time-code"
            />
            <Submit busy={busy}>Activer la protection</Submit>
          </form>
        </>
      ) : (
        <>
          <ol className="setup-steps">
            <li>Ouvrez votre application d’authentification.</li>
            <li>Ajoutez votre compte Unlimited Talks.</li>
            <li>Confirmez le code affiché sur votre téléphone.</li>
          </ol>
          <button
            type="button"
            className="button primary"
            disabled={busy}
            onClick={start}
          >
            {busy ? "Préparation…" : "Configurer la double authentification"}
            <Icon name="arrow" />
          </button>
        </>
      )}
      <button type="button" className="text-button centered" onClick={onLogout}>
        Se déconnecter
      </button>
    </>
  );
}

export function Recovery({
  codes,
  onContinue,
}: {
  codes: string[];
  onContinue: () => void;
}) {
  const [saved, setSaved] = useState(false);
  return (
    <>
      <div className="section-symbol">
        <Icon name="check" />
      </div>
      <span className="eyebrow">PROTECTION ACTIVÉE</span>
      <h2>Gardez une porte de secours.</h2>
      <p className="intro">
        Enregistrez ces codes dans votre gestionnaire de mots de passe. Ils ne
        seront plus affichés après cette étape. Chaque code est utilisable une
        seule fois.
      </p>
      <div className="recovery-codes">
        {codes.map((code) => (
          <code key={code}>{code}</code>
        ))}
      </div>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={saved}
          onChange={(event) => setSaved(event.target.checked)}
        />
        J’ai enregistré mes codes de récupération.
      </label>
      <button
        type="button"
        className="button primary"
        disabled={!saved}
        onClick={onContinue}
      >
        Accéder à mon espace
        <Icon name="arrow" />
      </button>
    </>
  );
}
