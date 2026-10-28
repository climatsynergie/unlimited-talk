import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError, message, privateLink } from "./api";
import type { Identity } from "./api";
import { AuthForm, AuthLayout, Enrollment, Recovery } from "./Auth";
import type { PrivateEntry } from "./Auth";
import { Audit, Invitations, InviteForm, ShareLink, Users } from "./Admin";
import { Calendar } from "./Calendar";
import { Campaigns } from "./Campaigns";
import { Contacts, Imports } from "./Contacts";
import { Brand, Field, Icon, Notice, Password, Submit } from "./ui";

type Page =
  | "home"
  | "users"
  | "invitations"
  | "audit"
  | "account"
  | "contacts"
  | "imports"
  | "campaigns"
  | "calendar";
const PATHS: Record<Page, string> = {
  home: "/accueil",
  users: "/admin/utilisateurs",
  invitations: "/admin/invitations",
  audit: "/admin/journal",
  account: "/compte",
  contacts: "/admin/contacts",
  imports: "/admin/imports",
  campaigns: "/campagnes",
  calendar: "/calendrier",
};
function currentPage(): Page | null {
  return (
    (Object.keys(PATHS) as Page[]).find(
      (page) => PATHS[page] === window.location.pathname,
    ) ?? null
  );
}

function Account({
  identity,
  onIdentity,
  onLogoutAll,
}: {
  identity: Identity;
  onIdentity: (value: Identity) => void;
  onLogoutAll: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function password(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    if (fields.get("new_password") !== fields.get("confirmation")) {
      setError("Les mots de passe doivent être identiques.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const value = await api<Identity>("/auth/password", {
        method: "POST",
        authenticated: false,
        body: {
          current_password: fields.get("current_password"),
          new_password: fields.get("new_password"),
          factor: String(fields.get("factor") ?? "").trim(),
        },
      });
      form.reset();
      onIdentity(value);
      setNotice(
        "Votre mot de passe a été modifié. Vos autres appareils ont été déconnectés.",
      );
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === 401 &&
        error.message === "Connexion requise"
      )
        window.dispatchEvent(new Event("ut-session-expired"));
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">VOTRE ACCÈS PERSONNEL</span>
          <h1>Mon compte.</h1>
          <p>Vos informations et la sécurité de votre connexion.</p>
        </div>
      </div>
      <div className="account-grid">
        <section className="panel account-summary">
          <span className="avatar avatar-purple avatar-large">
            {identity.user.display_name.slice(0, 2).toUpperCase()}
          </span>
          <h2>{identity.user.display_name}</h2>
          <p>{identity.user.email}</p>
          <span className="badge badge-purple">
            {identity.user.role === "admin" ? "Administrateur" : "Agent"}
          </span>
          <div className="account-security">
            <Icon name="shield" />
            <div>
              <strong>Un accès personnel</strong>
              <p>
                Gardez vos identifiants et vos codes de récupération dans votre
                gestionnaire de mots de passe.
              </p>
            </div>
          </div>
          <button
            className="button secondary"
            type="button"
            onClick={async () => {
              try {
                await onLogoutAll();
              } catch (error) {
                setError(message(error));
              }
            }}
          >
            Déconnecter tous mes appareils
          </button>
        </section>
        <section className="panel account-form">
          <h2>Modifier mon mot de passe</h2>
          <p className="muted">
            Choisissez une phrase d’au moins 12 caractères.
          </p>
          {error ? <Notice error>{error}</Notice> : null}
          {notice ? <Notice>{notice}</Notice> : null}
          <form method="post" onSubmit={password}>
            <input
              className="sr-only"
              name="username"
              value={identity.user.email}
              autoComplete="username"
              readOnly
              tabIndex={-1}
            />
            <Password
              label="Mot de passe actuel"
              name="current_password"
              required
              autoComplete="current-password"
              maxLength={128}
            />
            <Password
              label="Nouveau mot de passe"
              name="new_password"
              required
              autoComplete="new-password"
              minLength={12}
              maxLength={128}
            />
            <Password
              label="Confirmer le mot de passe"
              name="confirmation"
              required
              autoComplete="new-password"
              minLength={12}
              maxLength={128}
            />
            <Field
              label="Code d’authentification ou de récupération"
              name="factor"
              maxLength={64}
              autoComplete="one-time-code"
              hint="Nécessaire si votre compte est protégé par la double authentification."
            />
            <Submit busy={busy}>Enregistrer le mot de passe</Submit>
          </form>
        </section>
      </div>
    </>
  );
}

function Workspace({
  identity,
  setIdentity,
  onSessionEnded,
  onLogout,
}: {
  identity: Identity;
  setIdentity: (value: Identity) => void;
  onSessionEnded: () => void;
  onLogout: (all?: boolean) => Promise<void>;
}) {
  const [page, setPage] = useState<Page>(
    () => currentPage() ?? (identity.user.role === "admin" ? "users" : "home"),
  );
  const [invite, setInvite] = useState(false);
  const [share, setShare] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const admin = identity.user.role === "admin";
  const selected =
    !admin &&
    ["users", "invitations", "audit", "contacts", "imports"].includes(page)
      ? "home"
      : page;
  useEffect(() => {
    function pop() {
      setPage(currentPage() ?? "home");
    }
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  function navigate(next: Page) {
    setPage(next);
    window.history.pushState(null, "", PATHS[next]);
    setError("");
  }
  const items: {
    page: Page;
    title: string;
    icon: "home" | "users" | "mail" | "shield" | "campaign" | "calendar";
  }[] = admin
    ? [
        { page: "campaigns", title: "Campagnes", icon: "campaign" },
        { page: "calendar", title: "Calendrier", icon: "calendar" },
        { page: "contacts", title: "Contacts", icon: "users" },
        { page: "imports", title: "Imports CSV", icon: "mail" },
        { page: "users", title: "Utilisateurs", icon: "users" },
        { page: "invitations", title: "Invitations", icon: "mail" },
        { page: "audit", title: "Journal d’audit", icon: "shield" },
      ]
    : [
        { page: "campaigns", title: "Mes campagnes", icon: "campaign" },
        { page: "calendar", title: "Calendrier", icon: "calendar" },
        { page: "home", title: "Mon espace", icon: "home" },
      ];
  return (
    <div className="workspace">
      <a className="skip-link" href="#main">
        Aller au contenu
      </a>
      <aside className="sidebar">
        <Brand />
        <div className="workspace-label">
          <span className="workspace-initial">U</span>
          <div>
            <strong>Unlimited Talks</strong>
            <span>Espace de l’équipe</span>
          </div>
          <span className="workspace-dot" />
        </div>
        <span className="nav-label">
          {admin ? "ADMINISTRATION" : "VOTRE ESPACE"}
        </span>
        <nav aria-label="Navigation principale">
          {items.map((item) => (
            <a
              key={item.page}
              href={PATHS[item.page]}
              className={
                selected === item.page ? "nav-item selected" : "nav-item"
              }
              aria-current={selected === item.page ? "page" : undefined}
              onClick={(event) => {
                if (event.ctrlKey || event.metaKey || event.shiftKey) return;
                event.preventDefault();
                navigate(item.page);
              }}
            >
              <Icon name={item.icon} />
              {item.title}
              {selected === item.page ? (
                <span className="nav-indicator" />
              ) : null}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="team-note">
            <Icon name="shield" />
            <strong>Un espace de confiance.</strong>
            <p>Des accès individuels pour avancer ensemble.</p>
          </div>
          <a
            className={
              selected === "account" ? "nav-item selected" : "nav-item"
            }
            href="/compte"
            aria-label="Mon compte"
            onClick={(event) => {
              event.preventDefault();
              navigate("account");
            }}
          >
            <span className="avatar avatar-small">
              {identity.user.display_name.slice(0, 2).toUpperCase()}
            </span>
            <span className="sidebar-person">
              <strong>{identity.user.display_name}</strong>
              <span>{admin ? "Administrateur" : "Agent"}</span>
            </span>
          </a>
          <button
            className="nav-item logout"
            type="button"
            onClick={async () => {
              try {
                await onLogout();
              } catch (error) {
                setError(message(error));
              }
            }}
          >
            <Icon name="logout" />
            Se déconnecter
          </button>
        </div>
      </aside>
      <div className="workspace-body">
        <header className="topbar">
          <span>
            {selected === "account"
              ? "Mon compte"
              : admin
                ? "Administration de l’équipe"
                : "Mon espace"}
          </span>
          <div>
            <span
              className="avatar avatar-small avatar-purple"
              aria-hidden="true"
            >
              {identity.user.display_name.slice(0, 2).toUpperCase()}
            </span>
          </div>
        </header>
        <main id="main" className="workspace-main">
          {error ? <Notice error>{error}</Notice> : null}
          <div className="reauth-note">
            <span>
              Besoin de confirmer votre identité pour une action sensible ?
            </span>
            <button
              type="button"
              className="text-button"
              onClick={onSessionEnded}
            >
              Se reconnecter
            </button>
          </div>
          {selected === "campaigns" ? (
            <Campaigns admin={admin} />
          ) : selected === "calendar" ? (
            <Calendar userId={identity.user.id} />
          ) : selected === "contacts" ? (
            <Contacts />
          ) : selected === "imports" ? (
            <Imports />
          ) : selected === "users" ? (
            <Users
              me={identity.user}
              invite={() => setInvite(true)}
              onSessionEnded={onSessionEnded}
            />
          ) : selected === "invitations" ? (
            <Invitations invite={() => setInvite(true)} revision={revision} />
          ) : selected === "audit" ? (
            <Audit />
          ) : selected === "account" ? (
            <Account
              identity={identity}
              onIdentity={setIdentity}
              onLogoutAll={() => onLogout(true)}
            />
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <span className="eyebrow">VOTRE ESPACE</span>
                  <h1>Bonjour, {identity.user.display_name.split(" ")[0]}.</h1>
                  <p>Bienvenue dans votre espace Unlimited Talks.</p>
                </div>
              </div>
              <section className="welcome-panel">
                <div className="section-symbol">
                  <Icon name="check" />
                </div>
                <h2>Votre accès personnel est prêt.</h2>
                <p>
                  Vous êtes connecté avec votre compte agent. Retrouvez vos
                  informations et vos réglages de sécurité dans Mon compte.
                </p>
                <button
                  type="button"
                  className="button primary"
                  onClick={() => navigate("account")}
                >
                  Gérer mon compte
                  <Icon name="arrow" />
                </button>
              </section>
            </>
          )}
        </main>
        <footer className="workspace-footer">
          <span>Unlimited Talks</span>
          <span>Un accès personnel. Une équipe connectée.</span>
        </footer>
      </div>
      {invite ? (
        <InviteForm
          onClose={() => setInvite(false)}
          onCreated={(token) => {
            setInvite(false);
            setShare(privateLink("invitation", token));
            setRevision((value) => value + 1);
          }}
        />
      ) : null}
      {share ? (
        <ShareLink
          value={{
            link: share,
            heading: "Votre invitation est prête",
            duration: "24 heures",
          }}
          onClose={() => setShare(null)}
        />
      ) : null}
    </div>
  );
}

export function App({ initialEntry }: { initialEntry: PrivateEntry }) {
  const [entry, setEntry] = useState<PrivateEntry>(initialEntry);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [loading, setLoading] = useState(!initialEntry);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [retry, setRetry] = useState(0);
  function signedOut(
    text = "Votre session est terminée. Connectez-vous pour continuer.",
  ) {
    setIdentity(null);
    setCodes(null);
    setNotice(text);
    setEntry(null);
    window.history.replaceState(null, "", "/connexion");
  }
  useEffect(() => {
    if (initialEntry && retry === 0) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api<Identity>("/auth/me", {
      signal: controller.signal,
      authenticated: false,
    })
      .then((value) => {
        if (!controller.signal.aborted) setIdentity(value);
      })
      .catch((error) => {
        if (
          !controller.signal.aborted &&
          (!(error instanceof ApiError) || error.status !== 401)
        )
          setError(message(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [initialEntry, retry]);
  useEffect(() => {
    const expired = () => signedOut();
    window.addEventListener("ut-session-expired", expired);
    const channel =
      "BroadcastChannel" in window ? new BroadcastChannel("ut-identity") : null;
    if (channel)
      channel.onmessage = (event) => {
        if (event.data === "signed-out") signedOut();
      };
    return () => {
      window.removeEventListener("ut-session-expired", expired);
      channel?.close();
    };
  }, []);
  useEffect(() => {
    if (!identity) return;
    let controller: AbortController | null = null;
    const refresh = () => {
      if (document.hidden) return;
      controller?.abort();
      controller = new AbortController();
      api<Identity>("/auth/me", { signal: controller.signal })
        .then(setIdentity)
        .catch(() => {
          /* 401 already ends the session; a network failure is not a logout. */
        });
    };
    document.addEventListener("visibilitychange", refresh);
    return () => {
      controller?.abort();
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [identity?.user.id]);
  function authenticated(value: Identity) {
    setEntry(null);
    setIdentity(value);
    setNotice("");
    setError("");
    if (value.recovery_codes) setCodes(value.recovery_codes);
    window.history.replaceState(
      null,
      "",
      value.user.role === "admin" ? "/admin/utilisateurs" : "/accueil",
    );
  }
  async function logout(all = false) {
    await api(all ? "/auth/logout-all" : "/auth/logout", {
      method: "POST",
      body: {},
    });
    signedOut("Vous avez été déconnecté.");
    if ("BroadcastChannel" in window) {
      const channel = new BroadcastChannel("ut-identity");
      channel.postMessage("signed-out");
      channel.close();
    }
  }
  if (loading)
    return (
      <main className="session-loading" aria-busy="true">
        <Brand />
        <p role="status">Ouverture de votre espace…</p>
      </main>
    );
  if (error)
    return (
      <AuthLayout>
        <h2>Retrouvons votre connexion.</h2>
        <Notice error>{error}</Notice>
        <button
          className="button primary"
          type="button"
          onClick={() => setRetry((value) => value + 1)}
        >
          Réessayer
        </button>
      </AuthLayout>
    );
  if (codes)
    return (
      <AuthLayout>
        <Recovery codes={codes} onContinue={() => setCodes(null)} />
      </AuthLayout>
    );
  if (identity?.mfa_enrollment_required)
    return (
      <AuthLayout>
        <Enrollment
          onIdentity={authenticated}
          onLogout={() => {
            logout().catch((error) => setError(message(error)));
          }}
        />
      </AuthLayout>
    );
  if (identity)
    return (
      <Workspace
        identity={identity}
        setIdentity={setIdentity}
        onSessionEnded={() =>
          signedOut("Reconnectez-vous pour confirmer votre identité.")
        }
        onLogout={logout}
      />
    );
  return (
    <AuthLayout>
      <AuthForm
        key={entry?.kind ?? "login"}
        entry={entry}
        notice={notice}
        onIdentity={authenticated}
        onCancel={() => {
          setEntry(null);
          setNotice("");
          window.history.replaceState(null, "", "/connexion");
        }}
      />
    </AuthLayout>
  );
}
