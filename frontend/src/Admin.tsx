import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, date, message, privateLink } from "./api";
import type { AuditEvent, Invitation, Role, User } from "./api";
import { Field, Icon, Modal, Notice, Submit } from "./ui";

const PAGE_SIZE = 25;
function useRemote<T>(path: string, revision: number) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api<T>(path, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(message(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, revision]);
  return { data, loading, error };
}
function Loading() {
  return (
    <p className="loading" role="status">
      Chargement de votre équipe…
    </p>
  );
}
function RoleBadge({ role }: { role: Role }) {
  return (
    <span
      className={`badge ${role === "admin" ? "badge-purple" : "badge-neutral"}`}
    >
      {role === "admin" ? "Administrateur" : "Agent"}
    </span>
  );
}
function Pagination({
  offset,
  total,
  onPage,
  busy,
}: {
  offset: number;
  total: number;
  onPage: (offset: number) => void;
  busy: boolean;
}) {
  return (
    <div className="pagination">
      <span>
        {total
          ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} sur ${total}`
          : "Aucun résultat"}
      </span>
      <div>
        <button
          className="button secondary small"
          type="button"
          disabled={busy || !offset}
          onClick={() => onPage(Math.max(0, offset - PAGE_SIZE))}
        >
          Précédent
        </button>
        <button
          className="button secondary small"
          type="button"
          disabled={busy || offset + PAGE_SIZE >= total}
          onClick={() => onPage(offset + PAGE_SIZE)}
        >
          Suivant
        </button>
      </div>
    </div>
  );
}
function Retry({ error, retry }: { error: string; retry: () => void }) {
  return (
    <Notice error>
      {error}
      <button className="text-button" type="button" onClick={retry}>
        Réessayer
      </button>
    </Notice>
  );
}

export function ShareLink({
  value,
  onClose,
}: {
  value: { link: string; heading: string; duration: string };
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  async function copy() {
    try {
      await navigator.clipboard.writeText(value.link);
      setCopied(true);
      setError("");
    } catch {
      setError(
        "La copie automatique est indisponible. Sélectionnez et copiez le lien ci-dessous.",
      );
    }
  }
  return (
    <Modal title={value.heading} onClose={onClose}>
      <p className="intro">
        Transmettez ce lien directement à la personne concernée, par un canal
        privé. Aucun courriel n’est envoyé automatiquement.
      </p>
      <span className="badge badge-purple">Valable {value.duration}</span>
      <label className="share-label" htmlFor="private-link">
        Lien privé
      </label>
      <textarea
        id="private-link"
        className="share-link"
        readOnly
        rows={4}
        value={value.link}
        onFocus={(event) => event.currentTarget.select()}
      />
      {error ? <Notice error>{error}</Notice> : null}
      {copied ? <Notice>Lien copié.</Notice> : null}
      <div className="modal-actions">
        <button className="button secondary" type="button" onClick={onClose}>
          Fermer
        </button>
        <button className="button primary" type="button" onClick={copy}>
          Copier le lien
        </button>
      </div>
      <p className="muted small-text">
        Ce lien ne sera plus affiché après fermeture. Vous pourrez en créer un
        nouveau si nécessaire.
      </p>
    </Modal>
  );
}

export function InviteForm({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (token: string) => void;
}) {
  const [role, setRole] = useState<Role>("agent");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const fields = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const result = await api<{ token: string }>("/admin/invitations", {
        method: "POST",
        body: {
          email: fields.get("email"),
          display_name: fields.get("name"),
          role,
        },
      });
      onCreated(result.token);
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Inviter un membre" onClose={onClose} busy={busy}>
      <p className="intro">
        Un accès personnel pour chaque membre de votre équipe.
      </p>
      {error ? <Notice error>{error}</Notice> : null}
      <form method="post" onSubmit={submit}>
        <Field
          label="Nom complet"
          name="name"
          autoComplete="name"
          required
          maxLength={200}
        />
        <Field
          label="Adresse courriel"
          name="email"
          type="email"
          autoComplete="email"
          required
          maxLength={254}
        />
        <div className="field">
          <label htmlFor="invite-role">Rôle</label>
          <select
            id="invite-role"
            value={role}
            onChange={(event) => setRole(event.target.value as Role)}
          >
            <option value="agent">Agent</option>
            <option value="admin">Administrateur</option>
          </select>
        </div>
        {role === "admin" ? (
          <Notice>
            Ce membre devra activer la double authentification avant d’accéder à
            l’administration.
          </Notice>
        ) : null}
        <Submit busy={busy}>Créer l’invitation</Submit>
      </form>
    </Modal>
  );
}

type UserAction = "role" | "active" | "sessions" | "reset";
function ManageUser({
  target,
  action,
  onClose,
  onDone,
}: {
  target: User;
  action: UserAction;
  onClose: () => void;
  onDone: (token?: string) => void;
}) {
  const [role, setRole] = useState<Role>(target.role);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const title =
    action === "role"
      ? "Modifier le rôle"
      : action === "active"
        ? target.is_active
          ? "Désactiver ce compte ?"
          : "Réactiver ce compte ?"
        : action === "sessions"
          ? "Déconnecter ce membre ?"
          : "Réinitialiser le mot de passe";
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (action === "role" || action === "active")
        await api(`/admin/users/${target.id}`, {
          method: "PATCH",
          body: action === "role" ? { role } : { is_active: !target.is_active },
        });
      else if (action === "sessions")
        await api(`/admin/users/${target.id}/revoke-sessions`, {
          method: "POST",
          body: {},
        });
      else {
        const result = await api<{ token: string }>(
          `/admin/users/${target.id}/password-reset`,
          { method: "POST", body: {} },
        );
        onDone(result.token);
        return;
      }
      onDone();
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={title} onClose={onClose} busy={busy}>
      <div className="person-summary">
        <strong>{target.display_name}</strong>
        <span>{target.email}</span>
      </div>
      {error ? <Notice error>{error}</Notice> : null}
      <form method="post" onSubmit={submit}>
        {action === "role" ? (
          <div className="field">
            <label htmlFor="new-role">Rôle du membre</label>
            <select
              id="new-role"
              value={role}
              onChange={(event) => setRole(event.target.value as Role)}
            >
              <option value="agent">Agent</option>
              <option value="admin">Administrateur</option>
            </select>
          </div>
        ) : null}
        <p className="intro">
          {action === "reset"
            ? "Un lien privé permettra à ce membre de choisir son nouveau mot de passe. Sa double authentification reste nécessaire."
            : action === "active" && !target.is_active
              ? "Ce membre pourra à nouveau se connecter avec ses identifiants."
              : "Cette action déconnectera ce membre de tous ses appareils."}
        </p>
        <div className="modal-actions">
          <button
            className="button secondary"
            type="button"
            onClick={onClose}
            disabled={busy}
          >
            Annuler
          </button>
          <button
            type="submit"
            className={`button ${action === "active" && target.is_active ? "danger" : "primary"}`}
            disabled={busy}
          >
            {busy
              ? "En cours…"
              : action === "reset"
                ? "Créer le lien privé"
                : "Confirmer"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function Users({
  me,
  invite,
  onSessionEnded,
}: {
  me: User;
  invite: () => void;
  onSessionEnded: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [revision, setRevision] = useState(0);
  const [manage, setManage] = useState<{
    target: User;
    action: UserAction;
  } | null>(null);
  const [share, setShare] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const { data, loading, error } = useRemote<{ users: User[]; total: number }>(
    `/admin/users?limit=${PAGE_SIZE}&offset=${offset}&q=${encodeURIComponent(search)}`,
    revision,
  );
  function done(token?: string) {
    const self = manage?.target.id === me.id;
    setManage(null);
    setRevision((value) => value + 1);
    if (self) {
      onSessionEnded();
      return;
    }
    if (token) setShare(privateLink("reinitialisation", token));
    else setNotice("Les accès de ce membre ont été mis à jour.");
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">VOTRE ÉQUIPE</span>
          <h1>
            Les bonnes personnes,
            <br className="desktop-break" /> au bon endroit.
          </h1>
          <p>Gérez les comptes et les accès de votre équipe.</p>
        </div>
        <button type="button" className="button primary" onClick={invite}>
          <Icon name="mail" />
          Inviter un membre
        </button>
      </div>
      {notice ? <Notice>{notice}</Notice> : null}
      <section className="panel">
        <div className="panel-toolbar">
          <h2>Utilisateurs</h2>
          <form
            className="search"
            onSubmit={(event) => {
              event.preventDefault();
              setSearch(
                String(
                  new FormData(event.currentTarget).get("search") ?? "",
                ).trim(),
              );
              setOffset(0);
            }}
          >
            <label className="sr-only" htmlFor="user-search">
              Rechercher un utilisateur
            </label>
            <input
              id="user-search"
              name="search"
              type="search"
              placeholder="Nom ou adresse courriel"
              maxLength={100}
            />
            <button className="button secondary small" type="submit">
              Rechercher
            </button>
          </form>
        </div>
        {error ? (
          <Retry
            error={error}
            retry={() => setRevision((value) => value + 1)}
          />
        ) : loading ? (
          <Loading />
        ) : (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Membre</th>
                    <th>Rôle</th>
                    <th>Statut</th>
                    <th>
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data?.users.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <div className="person">
                          <span
                            className={`avatar ${user.role === "admin" ? "avatar-purple" : ""}`}
                          >
                            {user.display_name.slice(0, 2).toUpperCase()}
                          </span>
                          <div>
                            <strong>
                              {user.display_name}
                              {user.id === me.id ? (
                                <span className="you">Vous</span>
                              ) : null}
                            </strong>
                            <span>{user.email}</span>
                          </div>
                        </div>
                      </td>
                      <td>
                        <RoleBadge role={user.role} />
                      </td>
                      <td>
                        <span
                          className={`status ${user.is_active ? "" : "inactive"}`}
                        >
                          <span />
                          {user.is_active ? "Actif" : "Désactivé"}
                        </span>
                      </td>
                      <td>
                        <details className="row-menu">
                          <summary>
                            Gérer <span aria-hidden="true">⌄</span>
                          </summary>
                          <div>
                            {(
                              ["role", "active", "sessions", "reset"] as const
                            ).map((action) => (
                              <button
                                key={action}
                                type="button"
                                disabled={
                                  action === "reset" &&
                                  (!user.is_active || user.id === me.id)
                                }
                                onClick={(event) => {
                                  event.currentTarget
                                    .closest("details")
                                    ?.removeAttribute("open");
                                  setManage({ target: user, action });
                                }}
                              >
                                {action === "role"
                                  ? "Modifier le rôle"
                                  : action === "active"
                                    ? user.is_active
                                      ? "Désactiver le compte"
                                      : "Réactiver le compte"
                                    : action === "sessions"
                                      ? "Déconnecter les appareils"
                                      : "Réinitialiser le mot de passe"}
                              </button>
                            ))}
                          </div>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data?.users.length ? (
              <div className="empty">
                <Icon name="users" />
                <h3>Aucun membre trouvé</h3>
                <p>Essayez une autre recherche ou invitez votre équipe.</p>
              </div>
            ) : null}
            <Pagination
              offset={offset}
              total={data?.total ?? 0}
              onPage={setOffset}
              busy={loading}
            />
          </>
        )}
      </section>
      {manage ? (
        <ManageUser
          target={manage.target}
          action={manage.action}
          onClose={() => setManage(null)}
          onDone={done}
        />
      ) : null}
      {share ? (
        <ShareLink
          value={{
            link: share,
            heading: "Lien de réinitialisation prêt",
            duration: "30 minutes",
          }}
          onClose={() => setShare(null)}
        />
      ) : null}
    </>
  );
}

function invitationStatus(invitation: Invitation) {
  return invitation.used_at
    ? "Acceptée"
    : invitation.revoked_at
      ? "Révoquée"
      : new Date(invitation.expires_at.replace(" ", "T")).getTime() <=
          Date.now()
        ? "Expirée"
        : "En attente";
}
export function Invitations({
  invite,
  revision,
}: {
  invite: () => void;
  revision: number;
}) {
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [target, setTarget] = useState<Invitation | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const { data, loading, error } = useRemote<{
    invitations: Invitation[];
    total: number;
  }>(
    `/admin/invitations?limit=${PAGE_SIZE}&offset=${offset}`,
    revision + refresh,
  );
  async function revoke() {
    if (!target || busy) return;
    setBusy(true);
    setActionError("");
    try {
      await api(`/admin/invitations/${target.id}`, { method: "DELETE" });
      setTarget(null);
      setRefresh((value) => value + 1);
    } catch (error) {
      setActionError(message(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">GRANDIR ENSEMBLE</span>
          <h1>Une place dans l’équipe.</h1>
          <p>Suivez les invitations et gardez la maîtrise des accès.</p>
        </div>
        <button className="button primary" type="button" onClick={invite}>
          <Icon name="mail" />
          Inviter un membre
        </button>
      </div>
      <section className="panel">
        <div className="panel-toolbar">
          <h2>Invitations</h2>
          <span className="muted small-text">Valables 24 heures</span>
        </div>
        {error ? (
          <Retry error={error} retry={() => setRefresh((value) => value + 1)} />
        ) : loading ? (
          <Loading />
        ) : (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Destinataire</th>
                    <th>Rôle</th>
                    <th>Statut</th>
                    <th>Expiration</th>
                    <th>
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data?.invitations.map((invitation) => (
                    <tr key={invitation.id}>
                      <td>
                        <div className="person-text">
                          <strong>{invitation.display_name}</strong>
                          <span>{invitation.email}</span>
                        </div>
                      </td>
                      <td>
                        <RoleBadge role={invitation.role} />
                      </td>
                      <td>
                        <span className="badge badge-neutral">
                          {invitationStatus(invitation)}
                        </span>
                      </td>
                      <td>{date(invitation.expires_at)}</td>
                      <td>
                        {invitationStatus(invitation) === "En attente" ? (
                          <button
                            className="text-button"
                            type="button"
                            onClick={() => {
                              setTarget(invitation);
                              setActionError("");
                            }}
                          >
                            Révoquer
                          </button>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data?.invitations.length ? (
              <div className="empty">
                <Icon name="mail" />
                <h3>Votre équipe commence ici.</h3>
                <p>Créez une invitation pour accueillir un nouveau membre.</p>
              </div>
            ) : null}
            <Pagination
              offset={offset}
              total={data?.total ?? 0}
              onPage={setOffset}
              busy={loading}
            />
          </>
        )}
      </section>
      {target ? (
        <Modal
          title="Révoquer cette invitation ?"
          onClose={() => setTarget(null)}
          busy={busy}
        >
          <p className="intro">
            Le lien transmis à <strong>{target.email}</strong> ne permettra plus
            de créer un compte.
          </p>
          {actionError ? <Notice error>{actionError}</Notice> : null}
          <div className="modal-actions">
            <button
              className="button secondary"
              type="button"
              onClick={() => setTarget(null)}
              disabled={busy}
            >
              Annuler
            </button>
            <button
              className="button danger"
              type="button"
              onClick={revoke}
              disabled={busy}
            >
              {busy ? "En cours…" : "Révoquer l’invitation"}
            </button>
          </div>
        </Modal>
      ) : null}
    </>
  );
}

const ACTIONS: Record<string, string> = {
  "contacts.source_uploaded": "Fichier CSV déposé",
  "contacts.import_confirmed": "Import CSV confirmé",
  "contacts.import_completed": "Import CSV terminé",
  "session.login": "Connexion",
  "session.login_failed": "Connexion refusée",
  "session.logout": "Déconnexion",
  "session.all_revoked": "Tous les appareils déconnectés",
  "session.admin_revoked": "Appareils déconnectés par un administrateur",
  "user.permissions_changed": "Accès du compte modifiés",
  "user.password_changed": "Mot de passe modifié",
  "user.password_reset_issued": "Lien de réinitialisation créé",
  "user.password_reset_completed": "Mot de passe réinitialisé",
  "invitation.created": "Invitation créée",
  "invitation.accepted": "Invitation acceptée",
  "invitation.revoked": "Invitation révoquée",
  "mfa.enrollment_started":
    "Configuration de la double authentification commencée",
  "mfa.enrolled": "Double authentification activée",
  "mfa.recovery_used": "Code de récupération utilisé",
  "user.bootstrap_admin": "Premier administrateur créé",
};
export function Audit() {
  const [pages, setPages] = useState<(string | null)[]>([null]);
  const [revision, setRevision] = useState(0);
  const before = pages[pages.length - 1];
  const { data, loading, error } = useRemote<{ events: AuditEvent[] }>(
    `/admin/audit?limit=${PAGE_SIZE}${before ? `&before=${before}` : ""}`,
    revision,
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">CONFIANCE & TRANSPARENCE</span>
          <h1>Une trace des actions importantes.</h1>
          <p>
            Retrouvez l’historique des connexions et des changements d’accès.
          </p>
        </div>
        <button
          className="button secondary"
          type="button"
          onClick={() => {
            setPages([null]);
            setRevision((value) => value + 1);
          }}
        >
          Actualiser
        </button>
      </div>
      <section className="panel">
        <div className="panel-toolbar">
          <h2>Journal d’audit</h2>
          <span className="muted small-text">
            Heures affichées dans votre fuseau local
          </span>
        </div>
        {error ? (
          <Retry
            error={error}
            retry={() => setRevision((value) => value + 1)}
          />
        ) : loading ? (
          <Loading />
        ) : (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Action</th>
                    <th>Effectuée par</th>
                    <th>Concernant</th>
                    <th>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.events.map((event) => (
                    <tr key={event.id}>
                      <td>
                        <span className="audit-action">
                          <Icon name="shield" />
                          {ACTIONS[event.action] ?? "Action du compte"}
                        </span>
                      </td>
                      <td>
                        {event.actor_email ??
                          (event.actor_id
                            ? "Compte indisponible"
                            : "Visiteur non connecté")}
                      </td>
                      <td>{event.subject_label ?? "—"}</td>
                      <td className="nowrap">{date(event.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data?.events.length ? (
              <div className="empty">
                <h3>Aucune action à afficher</h3>
                <p>Les prochaines actions importantes apparaîtront ici.</p>
              </div>
            ) : null}
            <div className="pagination">
              <span>Page {pages.length}</span>
              <div>
                <button
                  className="button secondary small"
                  type="button"
                  disabled={pages.length <= 1}
                  onClick={() => setPages((value) => value.slice(0, -1))}
                >
                  Précédent
                </button>
                <button
                  className="button secondary small"
                  type="button"
                  disabled={data?.events.length !== PAGE_SIZE}
                  onClick={() => {
                    const id = data?.events.at(-1)?.id;
                    if (id) setPages((value) => [...value, id]);
                  }}
                >
                  Suivant
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </>
  );
}
