import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, date, message } from "./api";
import { Modal, Notice, Submit } from "./ui";
import { local, when, Timezone } from "./Scheduling";

type Status = "scheduled" | "completed" | "cancelled";
type Callback = {
  id: string;
  campaign_id: string;
  contact_id: string;
  owner_id: string;
  due_at: string;
  timezone: string;
  notes: string;
  status: Status;
  version: number;
  phone: string;
  profile: Record<string, string>;
  campaign_name: string;
  owner_name: string;
  is_due: boolean;
  blocked_reason: string | null;
};
type Event = {
  id: string;
  action: string;
  actor_name: string;
  created_at: string;
  details: {
    before?: Partial<Callback>;
    after?: Partial<Callback>;
    reason?: string;
  };
};
type Detail = { callback: Callback; events: Event[]; has_more: boolean };
type Contact = {
  campaign_id: string;
  contact_id: string;
  membership_version: number;
  timezone: string;
};
type Choice = { starts_at: string; utc_offset_minutes: number; label: string };
const statuses: Record<Status, string> = {
  scheduled: "Programmé",
  completed: "Traité",
  cancelled: "Annulé",
};
const reasons: Record<string, string> = {
  restricted: "Contact non intéressé ou à ne pas contacter",
  inactive_owner: "Compte de l’agent désactivé",
  archived_campaign: "Campagne archivée",
  removed_contact: "Contact retiré de la campagne",
  unassigned: "Campagne non attribuée à l’agent",
  non_interested: "Contact non intéressé",
  do_not_contact: "Ne pas contacter",
  "appointment.booked": "Rendez-vous créé",
  "contact.removed": "Contact retiré de la campagne",
  manual: "Action manuelle",
};
const actions: Record<string, string> = {
  "callback.created": "Rappel programmé",
  "callback.updated": "Rappel modifié",
  "callback.completed": "Rappel marqué comme traité",
  "callback.cancelled": "Rappel annulé",
};
function name(row: Callback) {
  return (
    row.profile.display_name ||
    [row.profile.first_name, row.profile.last_name].filter(Boolean).join(" ") ||
    row.phone
  );
}

export function CallbackForm({
  contact,
  row,
  onSaved,
  onCancel,
}: {
  contact?: Contact;
  row?: Callback;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [start, setStart] = useState(
    row ? local(row.due_at, row.timezone) : "",
  );
  const [zone, setZone] = useState(
    row?.timezone || contact?.timezone || "America/Toronto",
  );
  const [notes, setNotes] = useState(row?.notes || "");
  const [status, setStatus] = useState<Status>(row?.status || "scheduled");
  const [choices, setChoices] = useState<Choice[]>([]);
  const [offset, setOffset] = useState("");
  const [resolving, setResolving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(crypto.randomUUID());
  const originalOffset = row
    ? (Date.parse(local(row.due_at, row.timezone) + "Z") -
        Date.parse(row.due_at)) /
      60000
    : null;
  useEffect(() => {
    setChoices([]);
    setOffset("");
    setError("");
    if (!start) {
      setResolving(false);
      return;
    }
    const controller = new AbortController();
    setResolving(true);
    api<{ options: Choice[] }>(
      `/scheduling/resolve?${new URLSearchParams({ local_start: start, timezone: zone })}`,
      { signal: controller.signal },
    )
      .then((r) => {
        setChoices(r.options);
        if (r.options.length === 1)
          setOffset(String(r.options[0].utc_offset_minutes));
        else if (
          row &&
          start === local(row.due_at, row.timezone) &&
          zone === row.timezone
        )
          setOffset(String(originalOffset));
        if (!r.options.length)
          setError(
            "Cette heure n’existe pas lors du changement d’heure. Choisissez une autre heure.",
          );
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setResolving(false);
      });
    return () => controller.abort();
  }, [start, zone, row, originalOffset]);
  async function save(e: FormEvent) {
    e.preventDefault();
    if (busy || resolving || !choices.length || offset === "") return;
    setBusy(true);
    setError("");
    try {
      const schedule = {
        local_start: start,
        timezone: zone,
        utc_offset_minutes: Number(offset),
        notes,
      };
      await api(row ? `/callbacks/${row.id}` : "/callbacks", {
        method: row ? "PATCH" : "POST",
        body: row
          ? { ...schedule, version: row.version, status }
          : { ...contact, ...schedule, id: requestId.current },
      });
      onSaved();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="campaign-form appointment-form" onSubmit={save}>
      {error ? <Notice error>{error}</Notice> : null}
      <fieldset disabled={busy}>
        <label>
          Date et heure du rappel
          <input
            type="datetime-local"
            min="2000-01-01T00:00"
            max="2100-12-31T23:59"
            required
            value={start}
            onChange={(e) => {
              setStart(e.target.value);
              requestId.current = crypto.randomUUID();
            }}
          />
        </label>
        <Timezone
          value={zone}
          onChange={(z) => {
            setZone(z);
            requestId.current = crypto.randomUUID();
          }}
        />
        {resolving ? (
          <p role="status">Vérification du fuseau horaire…</p>
        ) : null}
        {choices.length > 1 ? (
          <label>
            Cette heure se produit deux fois — choisissez le décalage UTC
            <select
              required
              value={offset}
              onChange={(e) => {
                setOffset(e.target.value);
                requestId.current = crypto.randomUUID();
              }}
            >
              <option value="">Choisir le décalage</option>
              {choices.map((c) => (
                <option key={c.utc_offset_minutes} value={c.utc_offset_minutes}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label>
          Notes du rappel
          <textarea
            maxLength={5000}
            value={notes}
            onChange={(e) => {
              setNotes(e.target.value);
              requestId.current = crypto.randomUUID();
            }}
          />
        </label>
        {row ? (
          <label>
            Statut du rappel
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as Status)}
            >
              {Object.entries(statuses).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p>
            Le rappel vous sera attribué. Le contact passera dans l’étape « À
            rappeler ».
          </p>
        )}
      </fieldset>
      <div className="actions">
        <Submit
          busy={busy}
          disabled={resolving || !choices.length || offset === ""}
        >
          {row ? "Enregistrer le rappel" : "Confirmer le rappel"}
        </Submit>
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={onCancel}
        >
          Annuler la saisie
        </button>
      </div>
    </form>
  );
}

function CallbackDetail({
  id,
  onClose,
  onChanged,
}: {
  id: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api<Detail>(`/callbacks/${id}`, { signal: controller.signal })
      .then(setData)
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      });
    return () => controller.abort();
  }, [id, revision]);
  async function more() {
    if (!data) return;
    setBusy(true);
    try {
      const r = await api<Detail>(
        `/callbacks/${id}?before=${data.events.at(-1)?.id}`,
      );
      setData({
        ...data,
        events: [...data.events, ...r.events],
        has_more: r.has_more,
      });
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  const row = data?.callback;
  return (
    <Modal title="Fiche du rappel" onClose={onClose} busy={editing || busy}>
      {error ? <Notice error>{error}</Notice> : null}
      {!row ? (
        <p role="status">Chargement du rappel…</p>
      ) : (
        <>
          <dl className="contact-profile">
            <div>
              <dt>Contact</dt>
              <dd>{name(row)}</dd>
            </div>
            <div>
              <dt>Téléphone</dt>
              <dd>{row.phone}</dd>
            </div>
            <div>
              <dt>Campagne d’origine</dt>
              <dd>{row.campaign_name}</dd>
            </div>
            <div>
              <dt>Agent chargé du rappel</dt>
              <dd>{row.owner_name}</dd>
            </div>
            <div>
              <dt>Date et heure</dt>
              <dd>
                {when(row.due_at, row.timezone)} · {row.timezone}
              </dd>
            </div>
            <div>
              <dt>Statut</dt>
              <dd>
                {statuses[row.status]}
                {row.status === "scheduled" && row.is_due
                  ? " — échéance atteinte"
                  : ""}
              </dd>
            </div>
            <div>
              <dt>Notes</dt>
              <dd className="appointment-notes">
                {row.notes || "Aucune note."}
              </dd>
            </div>
          </dl>
          {row.status === "scheduled" && row.blocked_reason ? (
            <Notice>
              Rappel bloqué :{" "}
              {reasons[row.blocked_reason] || "Vérification nécessaire"}. Un
              administrateur peut résoudre la situation ou annuler le rappel.
            </Notice>
          ) : null}
          {editing ? (
            <CallbackForm
              row={row}
              onCancel={() => setEditing(false)}
              onSaved={() => {
                setEditing(false);
                setData(null);
                setRevision((n) => n + 1);
                onChanged();
              }}
            />
          ) : row.status === "scheduled" ? (
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setEditing(true)}
            >
              Reprogrammer ou clôturer le rappel
            </button>
          ) : null}
          <h3>Historique du rappel</h3>
          <ul className="contact-notes">
            {data?.events.map((e) => (
              <li key={e.id}>
                <strong>{actions[e.action] || "Rappel modifié"}</strong>
                <small>
                  {e.actor_name} · {date(e.created_at)}
                </small>
                {e.details.before ? (
                  <p>
                    Avant :{" "}
                    {when(e.details.before.due_at!, e.details.before.timezone!)}{" "}
                    · {e.details.before.timezone} ·{" "}
                    {statuses[e.details.before.status!]}
                    {e.details.before.notes
                      ? `\nNotes : ${e.details.before.notes}`
                      : ""}
                  </p>
                ) : null}
                {e.details.after ? (
                  <p>
                    {e.details.before ? "Après" : "Prévu"} :{" "}
                    {when(e.details.after.due_at!, e.details.after.timezone!)} ·{" "}
                    {e.details.after.timezone} ·{" "}
                    {statuses[e.details.after.status!]}
                    {e.details.after.notes
                      ? `\nNotes : ${e.details.after.notes}`
                      : ""}
                  </p>
                ) : null}
                {e.details.reason ? (
                  <p>Motif : {reasons[e.details.reason] || "Mise à jour"}</p>
                ) : null}
              </li>
            ))}
          </ul>
          {data?.has_more ? (
            <button className="button secondary" disabled={busy} onClick={more}>
              Événements précédents
            </button>
          ) : null}
        </>
      )}
    </Modal>
  );
}

export function Callbacks({
  admin,
  userId,
}: {
  admin: boolean;
  userId: string;
}) {
  const [scope, setScope] = useState("upcoming");
  const [mine, setMine] = useState(false);
  const [items, setItems] = useState<Callback[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) setRevision((n) => n + 1);
    }, 30000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ scope, offset: String(offset) });
    if (mine) params.set("owner", userId);
    api<{ items: Callback[]; has_more: boolean }>(`/callbacks?${params}`, {
      signal: controller.signal,
    })
      .then((r) => {
        setItems(r.items);
        setHasMore(r.has_more);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [scope, mine, userId, offset, revision]);
  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>{admin ? "Rappels programmés" : "Mes rappels"}</h1>
          <p>Chaque rappel reste réservé à l’agent qui l’a programmé.</p>
        </div>
      </div>
      <div className="calendar-controls">
        <label>
          Afficher les rappels
          <select
            value={scope}
            onChange={(e) => {
              setScope(e.target.value);
              setOffset(0);
            }}
          >
            <option value="upcoming">En attente</option>
            <option value="due">Échéance atteinte</option>
            <option value="history">Historique</option>
            <option value="all">Tous les rappels</option>
          </select>
        </label>
        {admin ? (
          <label>
            Agent
            <select
              value={mine ? "mine" : "all"}
              onChange={(e) => {
                setMine(e.target.value === "mine");
                setOffset(0);
              }}
            >
              <option value="all">Tous les agents</option>
              <option value="mine">Mes rappels</option>
            </select>
          </label>
        ) : null}
        <button
          className="button secondary"
          onClick={() => setRevision((n) => n + 1)}
        >
          Actualiser
        </button>
      </div>
      <p>
        Pour programmer un rappel, ouvrez une fiche dans sa campagne. Les
        rappels arrivés à échéance sont présentés en premier.
      </p>
      {error ? <Notice error>{error}</Notice> : null}
      {loading && !items.length ? (
        <p role="status">Chargement des rappels…</p>
      ) : null}
      {!error && !loading && !items.length ? (
        <p className="empty-state">Aucun rappel dans cette liste.</p>
      ) : null}
      <div className="callback-list" aria-busy={loading}>
        {items.map((row) => (
          <button
            className={`appointment-card ${row.status === "cancelled" ? "status-cancelled" : row.status === "completed" ? "status-completed" : ""}`}
            key={row.id}
            onClick={() => setSelected(row.id)}
          >
            <strong>{name(row)}</strong>
            <span>
              {when(row.due_at, row.timezone)} · {row.timezone}
            </span>
            <span>
              {row.campaign_name} · {row.owner_name}
            </span>
            <small>
              {row.status === "scheduled" && row.blocked_reason
                ? `Bloqué : ${reasons[row.blocked_reason] || "Vérification nécessaire"}`
                : row.status === "scheduled" && row.is_due
                  ? "Échéance atteinte — rappel prioritaire pour cet agent"
                  : statuses[row.status]}
            </small>
          </button>
        ))}
      </div>
      <div className="actions">
        <button
          className="button secondary"
          disabled={!offset || loading}
          onClick={() => setOffset((n) => Math.max(0, n - 100))}
        >
          Résultats précédents
        </button>
        <button
          className="button secondary"
          disabled={!hasMore || loading}
          onClick={() => setOffset((n) => n + 100)}
        >
          Résultats suivants
        </button>
      </div>
      {hasMore ? (
        <p>D’autres rappels sont disponibles sur la page suivante.</p>
      ) : null}
      {selected ? (
        <CallbackDetail
          id={selected}
          onClose={() => setSelected(null)}
          onChanged={() => setRevision((n) => n + 1)}
        />
      ) : null}
    </section>
  );
}
