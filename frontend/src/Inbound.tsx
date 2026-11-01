import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, date, message } from "./api";
import { Field, Icon, Modal, Notice, Submit } from "./ui";
import { local, Timezone, when } from "./Scheduling";
import type { Directory } from "./CallingSettings";

type Stage = "pending" | "claimed" | "callback" | "handled";
type Member = {
  user_id: string;
  mode: "mixed";
  display_name?: string;
  account_active?: boolean;
};
type Hours = { weekday: number; start: number; end: number };
type Queue = {
  id: string;
  name: string;
  phone: string;
  timezone: string;
  hours: Hours[];
  max_wait_seconds: number;
  offer_seconds: number;
  is_active: boolean;
  version: number;
  open_count?: number;
  agents: Member[];
  routing_active: boolean;
};
type Followup = {
  id: string;
  queue_id: string;
  caller_number: string | null;
  profile: Record<string, string> | null;
  owner_id: string | null;
  owner_name: string | null;
  stage: Stage;
  version: number;
  callback_at: string | null;
  callback_timezone: string | null;
  do_not_contact: boolean;
  non_interested: boolean;
  call_count: number;
  created_at?: string;
};
type History = {
  id: string;
  action: string;
  actor_name: string | null;
  created_at: string;
  details: {
    content?: string;
    outcome?: string;
    after?: { stage: Stage; callback_at?: string; timezone?: string };
  };
};
type Column = {
  stage: Stage;
  name: string;
  count: number;
  items: Followup[];
  has_more: boolean;
};
type Call = {
  id: string;
  called_number: string;
  outcome: string;
  received_at: string;
  ended_at: string;
};
const stages: Record<Stage, string> = {
  pending: "À traiter",
  claimed: "Pris en charge",
  callback: "Rappel programmé",
  handled: "Traité",
};
const outcomes: Record<string, string> = {
  missed: "Sans réponse",
  abandoned: "Appel abandonné",
  outside_hours: "Hors horaires",
  overflowed: "Attente dépassée",
};
const weekdays = [
  "Lundi",
  "Mardi",
  "Mercredi",
  "Jeudi",
  "Vendredi",
  "Samedi",
  "Dimanche",
];
const time = (value: number) =>
  `${String(Math.floor((value % 1440) / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
const minutes = (value: string) =>
  Number(value.slice(0, 2)) * 60 + Number(value.slice(3));
function contact(row: Followup) {
  return (
    row.profile?.display_name ||
    [row.profile?.first_name, row.profile?.last_name]
      .filter(Boolean)
      .join(" ") ||
    row.caller_number ||
    "Numéro masqué"
  );
}
function useRequestId() {
  const current = useRef({ value: "", id: crypto.randomUUID() });
  return (value: unknown) => {
    const signature = JSON.stringify(value);
    if (current.current.value !== signature)
      current.current = { value: signature, id: crypto.randomUUID() };
    return current.current.id;
  };
}

function QueueForm({
  row,
  onClose,
  onSaved,
}: {
  row?: Queue;
  onClose: () => void;
  onSaved: (id: string) => void;
}) {
  const [zone, setZone] = useState(row?.timezone || "America/Toronto");
  const [hours, setHours] = useState<Hours[]>(row?.hours || []);
  const [members, setMembers] = useState<Member[]>(row?.agents || []);
  const [choices, setChoices] = useState<
    { id: string; display_name: string }[]
  >([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [directory, setDirectory] = useState<Directory | null>(null);
  const [numberLoading, setNumberLoading] = useState(true);
  const [numberError, setNumberError] = useState("");
  const [numberRevision, setNumberRevision] = useState(0);
  const [phone, setPhone] = useState(row?.phone || "");
  const [agentSearch, setAgentSearch] = useState("");
  const id = useRef(row?.id || crypto.randomUUID());
  const requestId = useRequestId();
  useEffect(() => {
    const controller = new AbortController();
    setNumberLoading(true);
    setNumberError("");
    api<Directory>("/telephony/numbers", { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setDirectory(result);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setNumberError(message(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setNumberLoading(false);
      });
    return () => controller.abort();
  }, [numberRevision]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api<{ items: { id: string; display_name: string }[]; has_more: boolean }>(
      `/inbound/agents?offset=${offset}`,
      { signal: controller.signal },
    )
      .then((r) => {
        setChoices((old) => (offset ? [...old, ...r.items] : r.items));
        setMore(r.has_more);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [offset]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || loading || numberLoading || !phone) return;
    const form = new FormData(event.currentTarget);
    const values = {
      name: form.get("name"),
      phone,
      timezone: zone,
      max_wait_seconds: Number(form.get("wait")),
      offer_seconds: Number(form.get("ring")),
      hours,
      agents: members.map((m) => ({ user_id: m.user_id, mode: m.mode })),
      is_active: form.get("active") === "on",
    };
    setBusy(true);
    setError("");
    try {
      const result = await api<{ id: string }>(
        row ? `/inbound/queues/${row.id}` : "/inbound/queues",
        {
          method: row ? "PATCH" : "POST",
          body: row
            ? { ...values, version: row.version, request_id: requestId(values) }
            : { ...values, id: id.current },
        },
      );
      onSaved(result.id);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  const allChoices = [
    ...choices,
    ...members
      .filter((m) => !choices.some((c) => c.id === m.user_id))
      .map((m) => ({
        id: m.user_id,
        display_name: m.display_name || "Compte attribué",
      })),
  ];
  const lines =
    directory?.items.filter(
      (number) => number.voice_enabled && number.is_present && number.is_active,
    ) || [];
  const shownAgents = allChoices.filter((agent) =>
    agent.display_name
      .toLocaleLowerCase("fr")
      .includes(agentSearch.trim().toLocaleLowerCase("fr")),
  );
  return (
    <Modal
      title={row ? "Réglages de la file" : "Créer une file de réception"}
      onClose={onClose}
      busy={busy}
    >
      {error ? <Notice error>{error}</Notice> : null}
      <form className="campaign-form" onSubmit={save}>
        <Field
          label="Nom de la file"
          name="name"
          required
          maxLength={120}
          defaultValue={row?.name}
          disabled={busy}
          placeholder="Réception principale"
          hint="Un nom pour votre équipe de réception."
        />
        <label>
          Numéro de réception
          <select
            name="phone"
            required
            value={phone}
            disabled={busy || numberLoading}
            onChange={(e) => setPhone(e.target.value)}
          >
            <option value="">Choisir une ligne de l’entreprise</option>
            {lines.map((number) => (
              <option key={number.id} value={number.number}>
                {number.number}
                {number.name ? ` · ${number.name}` : ""}
              </option>
            ))}
            {row && !lines.some((number) => number.number === row.phone) ? (
              <option value={row.phone}>{row.phone} · Ligne enregistrée</option>
            ) : null}
          </select>
        </label>
        <p className="muted">
          C’est le numéro de l’entreprise que les clients appellent. Choisissez
          une ligne existante de votre compte Twilio, puis les agents qui la
          recevront.
        </p>
        {numberLoading ? (
          <p role="status">Chargement des lignes de l’entreprise…</p>
        ) : null}
        {numberError ? <Notice error>{numberError}</Notice> : null}
        {!numberLoading && !numberError && directory && !lines.length ? (
          <Notice>
            Aucune ligne Twilio n’est disponible dans la liste actuelle.
            Vérifiez la synchronisation des numéros du compte avant de créer une
            file.
          </Notice>
        ) : null}
        <button
          type="button"
          className="text-button"
          disabled={busy || numberLoading}
          onClick={() => setNumberRevision((n) => n + 1)}
        >
          Actualiser les lignes disponibles
        </button>
        <Timezone value={zone} onChange={setZone} disabled={busy} />
        <details className="inbound-advanced">
          <summary>Attente, sonnerie et horaires</summary>
          <div className="form-grid">
            <Field
              label="Attente maximale (secondes)"
              name="wait"
              type="number"
              min={10}
              max={600}
              required
              defaultValue={row?.max_wait_seconds || 60}
              disabled={busy}
            />
            <Field
              label="Sonnerie par agent (secondes)"
              name="ring"
              type="number"
              min={5}
              max={60}
              required
              defaultValue={row?.offer_seconds || 20}
              disabled={busy}
            />
          </div>
          <fieldset className="inbound-fieldset" disabled={busy}>
            <legend>Horaires de réception</legend>
            <p className="muted">
              Sans plage horaire, la file reste hors horaires. Pour une
              ouverture de nuit, utilisez une plage sur chaque journée.
            </p>
            {hours.map((h, index) => (
              <div className="inbound-hours" key={index}>
                <label>
                  Jour
                  <select
                    value={h.weekday}
                    onChange={(e) =>
                      setHours(
                        hours.map((v, i) =>
                          i === index
                            ? { ...v, weekday: Number(e.target.value) }
                            : v,
                        ),
                      )
                    }
                  >
                    {weekdays.map((d, i) => (
                      <option value={i} key={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Début
                  <input
                    type="time"
                    required
                    value={time(h.start)}
                    onChange={(e) =>
                      setHours(
                        hours.map((v, i) =>
                          i === index
                            ? { ...v, start: minutes(e.target.value) }
                            : v,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  Fin (00:00 = minuit)
                  <input
                    type="time"
                    required
                    value={time(h.end)}
                    onChange={(e) =>
                      setHours(
                        hours.map((v, i) =>
                          i === index
                            ? { ...v, end: minutes(e.target.value) || 1440 }
                            : v,
                        ),
                      )
                    }
                  />
                </label>
                <button
                  type="button"
                  className="button secondary"
                  aria-label={`Retirer la plage ${index + 1}`}
                  onClick={() => setHours(hours.filter((_, i) => i !== index))}
                >
                  Retirer
                </button>
              </div>
            ))}
            <button
              type="button"
              className="button secondary"
              disabled={hours.length >= 14}
              onClick={() =>
                setHours([...hours, { weekday: 0, start: 540, end: 1020 }])
              }
            >
              Ajouter une plage
            </button>
          </fieldset>
        </details>
        <fieldset className="inbound-fieldset" disabled={busy}>
          <legend>Agents autorisés à recevoir les appels</legend>
          <p className="muted">
            Les attributions sont indépendantes des campagnes. Maximum : 20
            agents par file.
          </p>
          <label>
            Rechercher un agent
            <input
              type="search"
              value={agentSearch}
              onChange={(e) => setAgentSearch(e.target.value)}
            />
          </label>
          <p className="inbound-agent-count">
            {members.length} agent(s) sélectionné(s)
          </p>
          <div
            className="inbound-agent-options"
            tabIndex={0}
            role="region"
            aria-label="Agents disponibles"
          >
            {shownAgents.map((c) => {
              const chosen = members.find((m) => m.user_id === c.id);
              return (
                <div className="inbound-member" key={c.id}>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={Boolean(chosen)}
                      disabled={!chosen && members.length >= 20}
                      onChange={(e) =>
                        setMembers(
                          e.target.checked
                            ? [...members, { user_id: c.id, mode: "mixed" }]
                            : members.filter((m) => m.user_id !== c.id),
                        )
                      }
                    />
                    {c.display_name}
                    {chosen?.account_active === false
                      ? " — compte désactivé"
                      : ""}
                  </label>
                </div>
              );
            })}
          </div>
          {!loading && !shownAgents.length && allChoices.length ? (
            <p>Aucun agent ne correspond à la recherche.</p>
          ) : null}
          {loading ? (
            <p role="status">Chargement des agents…</p>
          ) : !allChoices.length && !error ? (
            <p>Aucun compte actif.</p>
          ) : null}
          {more ? (
            <button
              className="button secondary"
              type="button"
              disabled={loading}
              onClick={() => setOffset(offset + 100)}
            >
              Voir plus d’agents
            </button>
          ) : null}
        </fieldset>
        <label className="checkbox-label">
          <input
            type="checkbox"
            name="active"
            defaultChecked={row?.is_active ?? true}
            disabled={busy}
          />
          File disponible dans l’organisation
        </label>
        <p className="muted">
          L’enregistrement de ces réglages ne connecte pas encore le numéro à la
          réception d’appels.
        </p>
        <Submit busy={busy} disabled={loading || numberLoading || !phone}>
          Enregistrer les réglages
        </Submit>
      </form>
    </Modal>
  );
}

function FollowupAction({
  row,
  queue,
  admin,
  userId,
  onSaved,
  onBusy,
}: {
  row: Followup;
  queue: Queue;
  admin: boolean;
  userId: string;
  onSaved: () => Promise<void>;
  onBusy: (value: boolean) => void;
}) {
  const [stage, setStage] = useState<Stage>(row.stage);
  const [owner, setOwner] = useState(row.owner_id || userId);
  const [zone, setZone] = useState(row.callback_timezone || queue.timezone);
  const [start, setStart] = useState(
    row.callback_at ? local(row.callback_at, zone) : "",
  );
  const [choices, setChoices] = useState<
    { starts_at: string; utc_offset_minutes: number; label: string }[]
  >([]);
  const [offset, setOffset] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolved, setResolved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRequestId();
  const editable =
    row.stage !== "handled" &&
    (admin || !row.owner_id || row.owner_id === userId);
  useEffect(() => {
    setChoices([]);
    setOffset("");
    setResolved(false);
    if (stage !== "callback" || !start) {
      setResolving(false);
      return;
    }
    const controller = new AbortController();
    setResolving(true);
    api<{ options: typeof choices }>(
      `/scheduling/resolve?${new URLSearchParams({ local_start: start, timezone: zone })}`,
      { signal: controller.signal },
    )
      .then((r) => {
        setChoices(r.options);
        setResolved(true);
        if (r.options.length === 1)
          setOffset(String(r.options[0].utc_offset_minutes));
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setResolving(false);
      });
    return () => controller.abort();
  }, [stage, start, zone]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || !editable || resolving) return;
    const values = {
      version: row.version,
      stage,
      ...(admin && stage !== "pending" ? { owner_id: owner } : {}),
      ...(stage === "callback"
        ? {
            local_start: start,
            timezone: zone,
            utc_offset_minutes: Number(offset),
          }
        : {}),
    };
    setBusy(true);
    onBusy(true);
    setError("");
    try {
      await api(`/inbound/followups/${row.id}`, {
        method: "POST",
        body: { ...values, request_id: requestId(values) },
      });
      await onSaved();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
      onBusy(false);
    }
  }
  if (!editable)
    return (
      <p className="muted">
        {row.stage === "handled"
          ? "Ce suivi est clôturé. Son historique reste disponible."
          : "Ce suivi est pris en charge par un autre agent."}
      </p>
    );
  return (
    <form className="campaign-form" onSubmit={save}>
      {error ? <Notice error>{error}</Notice> : null}
      <label>
        Étape du suivi
        <select
          value={stage}
          disabled={busy}
          onChange={(e) => setStage(e.target.value as Stage)}
        >
          {Object.entries(stages).map(([k, v]) => (
            <option
              key={k}
              value={k}
              disabled={
                k === "callback" &&
                (!row.caller_number || row.do_not_contact || row.non_interested)
              }
            >
              {v}
            </option>
          ))}
        </select>
      </label>
      {admin && stage !== "pending" ? (
        <label>
          Agent responsable
          <select
            required
            value={owner}
            disabled={busy}
            onChange={(e) => setOwner(e.target.value)}
          >
            <option value="">Choisir un agent</option>
            {queue.agents.map((a) => (
              <option
                value={a.user_id}
                key={a.user_id}
                disabled={a.account_active === false}
              >
                {a.display_name}
                {a.account_active === false ? " — désactivé" : ""}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {stage === "callback" ? (
        <>
          <Field
            label="Date et heure du rappel"
            name="callback_time"
            type="datetime-local"
            required
            value={start}
            onChange={(e) => setStart(e.target.value)}
            disabled={busy}
          />
          <Timezone value={zone} onChange={setZone} disabled={busy} />
          {choices.length > 1 ? (
            <label>
              Décalage UTC
              <select
                required
                value={offset}
                onChange={(e) => setOffset(e.target.value)}
              >
                <option value="">Choisir le décalage</option>
                {choices.map((c) => (
                  <option key={c.starts_at} value={c.utc_offset_minutes}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {resolved && !resolving && start && !choices.length ? (
            <p role="alert">Cette heure n’existe pas dans ce fuseau.</p>
          ) : null}
          <p className="muted">
            Ce rappel reste manuel et sera réservé à l’agent responsable.
          </p>
        </>
      ) : null}
      <Submit
        busy={busy}
        disabled={
          stage === "callback" &&
          (resolving || offset === "" || !choices.length)
        }
      >
        Enregistrer le suivi
      </Submit>
    </form>
  );
}

function FollowupDetail({
  id,
  queue,
  admin,
  userId,
  onClose,
  onChanged,
}: {
  id: string;
  queue: Queue;
  admin: boolean;
  userId: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [data, setData] = useState<{
    followup: Followup;
    events: History[];
    has_more: boolean;
  } | null>(null);
  const [calls, setCalls] = useState<Call[]>([]);
  const [moreCalls, setMoreCalls] = useState(false);
  const [error, setError] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const requestId = useRequestId();
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    Promise.all([
      api<NonNullable<typeof data>>(`/inbound/followups/${id}`, {
        signal: controller.signal,
      }),
      api<{ items: Call[]; has_more: boolean }>(
        `/inbound/followups/${id}/calls`,
        { signal: controller.signal },
      ),
    ])
      .then(([d, c]) => {
        setData(d);
        setCalls(c.items);
        setMoreCalls(c.has_more);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      });
    return () => controller.abort();
  }, [id, revision]);
  async function refresh() {
    setRevision((r) => r + 1);
    onChanged();
  }
  async function more(kind: "calls" | "events") {
    if (!data || busy) return;
    setBusy(true);
    setError("");
    try {
      if (kind === "calls") {
        const r = await api<{ items: Call[]; has_more: boolean }>(
          `/inbound/followups/${id}/calls?before=${calls.at(-1)?.id}`,
        );
        setCalls([...calls, ...r.items]);
        setMoreCalls(r.has_more);
      } else {
        const r = await api<NonNullable<typeof data>>(
          `/inbound/followups/${id}?before=${data.events.at(-1)?.id}`,
        );
        setData({
          ...data,
          events: [...data.events, ...r.events],
          has_more: r.has_more,
        });
      }
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function note(event: FormEvent) {
    event.preventDefault();
    if (busy || !content.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api(`/inbound/followups/${id}/notes`, {
        method: "POST",
        body: { id: requestId(content.trim()), content: content.trim() },
      });
      setContent("");
      await refresh();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={data ? contact(data.followup) : "Suivi d’appel entrant"}
      onClose={onClose}
      busy={busy}
    >
      {error ? <Notice error>{error}</Notice> : null}
      <button
        type="button"
        className="button secondary"
        disabled={busy}
        onClick={() => setRevision((r) => r + 1)}
      >
        Actualiser la fiche
      </button>
      {!data ? (
        <p role="status">Chargement du suivi…</p>
      ) : (
        <>
          <dl className="contact-fields">
            <div>
              <dt>Téléphone</dt>
              <dd>{data.followup.caller_number || "Numéro masqué"}</dd>
            </div>
            <div>
              <dt>Responsable</dt>
              <dd>{data.followup.owner_name || "Non attribué"}</dd>
            </div>
            <div>
              <dt>Étape</dt>
              <dd>{stages[data.followup.stage]}</dd>
            </div>
            <div>
              <dt>Appels liés</dt>
              <dd>{data.followup.call_count}</dd>
            </div>
          </dl>
          {data.followup.do_not_contact || data.followup.non_interested ? (
            <Notice>
              Ce contact possède une restriction de contact. La réception de son
              appel ne lève pas cette restriction.
            </Notice>
          ) : null}
          {data.followup.callback_at ? (
            <p>
              Rappel manuel :{" "}
              {when(
                data.followup.callback_at,
                data.followup.callback_timezone || queue.timezone,
              )}
            </p>
          ) : null}
          <FollowupAction
            key={data.followup.version}
            row={data.followup}
            queue={queue}
            admin={admin}
            userId={userId}
            onSaved={refresh}
            onBusy={setBusy}
          />
          <h3>Appels reçus</h3>
          <ol className="inbound-history">
            {calls.map((c) => (
              <li key={c.id}>
                <strong>{outcomes[c.outcome]}</strong>
                <span>{when(c.received_at, queue.timezone)}</span>
                <span>Numéro appelé : {c.called_number}</span>
              </li>
            ))}
          </ol>
          {moreCalls ? (
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => void more("calls")}
            >
              Voir les appels précédents
            </button>
          ) : null}
          <h3>Notes partagées</h3>
          <form onSubmit={note} className="campaign-form">
            <label>
              Ajouter une note
              <textarea
                maxLength={5000}
                required
                value={content}
                onChange={(e) => setContent(e.target.value)}
                disabled={busy}
              />
            </label>
            <Submit busy={busy} disabled={!content.trim()}>
              Enregistrer la note
            </Submit>
          </form>
          <h3>Historique du suivi</h3>
          <ol className="inbound-history">
            {data.events.map((e) => (
              <li key={e.id}>
                <strong>
                  {e.action === "note.added"
                    ? "Note ajoutée"
                    : e.action === "call.received"
                      ? "Appel reçu"
                      : "Suivi modifié"}
                </strong>
                {e.details.content ? (
                  <p>{e.details.content}</p>
                ) : e.details.after ? (
                  <span>
                    {stages[e.details.after.stage]}
                    {e.details.after.callback_at
                      ? ` · ${when(e.details.after.callback_at, e.details.after.timezone || queue.timezone)}`
                      : ""}
                  </span>
                ) : e.details.outcome ? (
                  <span>{outcomes[e.details.outcome]}</span>
                ) : null}
                <span>
                  {e.actor_name || "Réception"} · {date(e.created_at)}
                </span>
              </li>
            ))}
          </ol>
          {data.has_more ? (
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => void more("events")}
            >
              Voir l’historique précédent
            </button>
          ) : null}
        </>
      )}
    </Modal>
  );
}

export function Inbound({ admin, userId }: { admin: boolean; userId: string }) {
  const [queues, setQueues] = useState<Queue[]>([]);
  const [selected, setSelected] = useState("");
  const [board, setBoard] = useState<{
    queue: Queue;
    columns: Column[];
  } | null>(null);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Queue | "new" | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const [moreBusy, setMoreBusy] = useState(false);
  const [view, setView] = useState<"list" | "pipeline">("list");
  const [stageFilter, setStageFilter] = useState<Stage | "all">("all");
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setLoading(true);
    api<{ items: Queue[] }>("/inbound/queues", { signal: controller.signal })
      .then((r) => {
        setQueues(r.items);
        setSelected((old) =>
          r.items.some((q) => q.id === old) ? old : r.items[0]?.id || "",
        );
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    setBoard((current) => (current?.queue.id === selected ? current : null));
    if (!selected) return;
    const controller = new AbortController();
    setError("");
    api<NonNullable<typeof board>>(`/inbound/queues/${selected}/board`, {
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) setBoard(result);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      });
    return () => controller.abort();
  }, [selected, revision]);
  async function more(column: Column) {
    if (moreBusy || !board) return;
    setMoreBusy(true);
    setError("");
    const observed = board;
    try {
      const r = await api<{ items: Followup[]; has_more: boolean }>(
        `/inbound/queues/${selected}/followups?stage=${column.stage}&before=${column.items.at(-1)?.id}`,
      );
      setBoard((current) =>
        current === observed
          ? {
              ...current,
              columns: current.columns.map((c) =>
                c.stage === column.stage
                  ? {
                      ...c,
                      items: [...c.items, ...r.items],
                      has_more: r.has_more,
                    }
                  : c,
              ),
            }
          : current,
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setMoreBusy(false);
    }
  }
  const visibleColumns =
    board?.columns.filter(
      (column) => stageFilter === "all" || column.stage === stageFilter,
    ) || [];
  const total =
    board?.columns.reduce((sum, column) => sum + column.count, 0) || 0;
  const empty = visibleColumns.every((column) => column.items.length === 0);
  const activeAgents =
    board?.queue.agents.filter((agent) => agent.account_active !== false) || [];
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">RÉCEPTION ET SUIVI</span>
          <h1>Appels entrants</h1>
          <p>Vos lignes de réception et les demandes à rappeler.</p>
        </div>
        <div className="audio-actions">
          <button
            type="button"
            className="button secondary"
            onClick={() => setRevision((r) => r + 1)}
          >
            Actualiser
          </button>
          {admin ? (
            <button
              type="button"
              className="button primary"
              onClick={() => setEditing("new")}
            >
              Créer une file
            </button>
          ) : null}
        </div>
      </div>
      {error ? <Notice error>{error}</Notice> : null}
      {loading ? (
        <p role="status">Chargement des files…</p>
      ) : error && !queues.length ? null : !queues.length ? (
        <section className="panel">
          <h2>{admin ? "Organiser la réception" : "Aucune file attribuée"}</h2>
          <p>
            {admin
              ? "Créez une file par numéro et choisissez les agents qui recevront ses appels."
              : "Un administrateur peut vous attribuer une file de réception."}
          </p>
        </section>
      ) : (
        <>
          <label className="inbound-queue-select">
            File de réception
            <select
              value={selected}
              onChange={(e) => {
                setSelected(e.target.value);
                setDetail(null);
                setStageFilter("all");
              }}
            >
              {queues.map((q) => (
                <option key={q.id} value={q.id}>
                  {q.name} · {q.phone}
                  {!q.is_active ? " — archivée" : ""}
                </option>
              ))}
            </select>
          </label>
          {board ? (
            <>
              <section className="panel inbound-summary inbound-line-card">
                <div className="inbound-line-heading">
                  <span className="inbound-line-icon">
                    <Icon name="headset" />
                  </span>
                  <div>
                    <span className="eyebrow">LIGNE DE RÉCEPTION</span>
                    <h2>{board.queue.name}</h2>
                    <p className="inbound-line-phone">{board.queue.phone}</p>
                  </div>
                </div>
                <div className="inbound-line-actions">
                  <span
                    className={`inbound-routing-state ${board.queue.routing_active ? "is-connected" : "is-disconnected"}`}
                  >
                    {!board.queue.is_active
                      ? "File archivée"
                      : board.queue.routing_active
                        ? "Réception active"
                        : "Réception inactive"}
                  </span>
                  {admin ? (
                    <button
                      type="button"
                      className="button secondary"
                      onClick={() => setEditing(board.queue)}
                    >
                      Modifier les réglages
                    </button>
                  ) : null}
                </div>
                <div className="inbound-line-team">
                  <strong>
                    {activeAgents.length} agent
                    {activeAgents.length > 1 ? "s" : ""} attribué
                    {activeAgents.length > 1 ? "s" : ""}
                  </strong>
                  <div className="inbound-team-chips">
                    {activeAgents.map((agent) => (
                      <span key={agent.user_id}>
                        {agent.display_name || "Agent attribué"}
                      </span>
                    ))}
                  </div>
                  {!activeAgents.length ? (
                    <p>
                      Attribuez les agents chargés de cette ligne dans ses
                      réglages.
                    </p>
                  ) : null}
                </div>
                {board.queue.is_active && !board.queue.routing_active ? (
                  <div className="inbound-routing-help" role="status">
                    <strong>
                      Les appels de cette ligne ne sont pas encore acheminés aux
                      agents de l’application.
                    </strong>
                    <p>
                      La file et les agents sont enregistrés. Le raccordement
                      téléphonique reste à effectuer ; les suivis ci-dessous
                      restent consultables.
                    </p>
                  </div>
                ) : null}
              </section>
              <div
                className="inbound-stage-filters"
                aria-label="Filtrer les suivis par statut"
              >
                {board.columns.map((column) => (
                  <button
                    type="button"
                    key={column.stage}
                    className={`inbound-stage-filter stage-${column.stage}`}
                    aria-pressed={stageFilter === column.stage}
                    onClick={() =>
                      setStageFilter((old) =>
                        old === column.stage ? "all" : column.stage,
                      )
                    }
                  >
                    <span>{column.name}</span>
                    <strong>{column.count}</strong>
                  </button>
                ))}
              </div>
              <section
                className="panel inbound-followups"
                aria-label="Suivis des appels entrants"
              >
                <div className="inbound-followups-heading">
                  <div>
                    <h2>Suivis des appels entrants</h2>
                    <p>
                      {total} suivi{total > 1 ? "s" : ""} dans cette file
                    </p>
                  </div>
                  <div
                    className="segmented-control"
                    aria-label="Affichage des suivis"
                  >
                    <button
                      type="button"
                      aria-pressed={view === "list"}
                      onClick={() => setView("list")}
                    >
                      Liste
                    </button>
                    <button
                      type="button"
                      aria-pressed={view === "pipeline"}
                      onClick={() => setView("pipeline")}
                    >
                      Pipeline
                    </button>
                  </div>
                </div>
                {stageFilter !== "all" ? (
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => setStageFilter("all")}
                  >
                    Afficher tous les statuts
                  </button>
                ) : null}
                {empty && view === "list" ? (
                  <div className="inbound-empty">
                    <Icon name="headset" />
                    <h3>
                      {total
                        ? "Aucun suivi dans ce statut"
                        : "Aucun appel à suivre"}
                    </h3>
                    <p>
                      {total
                        ? "Choisissez un autre statut pour retrouver les autres suivis."
                        : "Les demandes à traiter, les prises en charge et les rappels apparaissent ici."}
                    </p>
                  </div>
                ) : view === "list" ? (
                  <div
                    className="inbound-list"
                    tabIndex={0}
                    role="region"
                    aria-label="Liste des suivis"
                  >
                    {visibleColumns
                      .filter((column) => column.items.length > 0)
                      .map((column) => (
                        <section
                          key={column.stage}
                          aria-label={column.name}
                          className={`inbound-list-group stage-${column.stage}`}
                        >
                          <h3>
                            <span className="inbound-stage-dot" />
                            {column.name}
                            <span className="inbound-group-count">
                              {column.count}
                            </span>
                          </h3>
                          <ul>
                            {column.items.map((row) => (
                              <li key={row.id}>
                                <button
                                  type="button"
                                  className="inbound-followup-row"
                                  onClick={() => setDetail(row.id)}
                                >
                                  <span
                                    className="inbound-contact-avatar"
                                    aria-hidden="true"
                                  >
                                    {contact(row)
                                      .replace(/[^\p{L}]/gu, "")
                                      .slice(0, 2)
                                      .toLocaleUpperCase("fr") || "AP"}
                                  </span>
                                  <span className="inbound-row-contact">
                                    <strong>
                                      {contact(row) === row.caller_number ||
                                      (!row.caller_number && !row.profile)
                                        ? "Appelant à identifier"
                                        : contact(row)}
                                    </strong>
                                    <span>
                                      {row.caller_number || "Numéro masqué"}
                                    </span>
                                  </span>
                                  <span className="inbound-row-owner">
                                    {row.owner_name || "À attribuer"}
                                    <small>
                                      {row.call_count} appel
                                      {row.call_count > 1 ? "s" : ""}
                                    </small>
                                  </span>
                                  <span className="inbound-row-date">
                                    {row.callback_at
                                      ? when(
                                          row.callback_at,
                                          row.callback_timezone ||
                                            board.queue.timezone,
                                        )
                                      : row.created_at
                                        ? when(
                                            row.created_at,
                                            board.queue.timezone,
                                          )
                                        : "Ouvrir la fiche"}
                                    <span aria-hidden="true"> →</span>
                                  </span>
                                </button>
                              </li>
                            ))}
                          </ul>
                          {column.has_more ? (
                            <button
                              type="button"
                              className="button secondary"
                              disabled={moreBusy}
                              onClick={() => void more(column)}
                            >
                              Voir plus de suivis — {column.name}
                            </button>
                          ) : null}
                        </section>
                      ))}
                  </div>
                ) : (
                  <div className="pipeline-board inbound-board">
                    {visibleColumns.map((column) => (
                      <section
                        className={`pipeline-column stage-${column.stage}`}
                        key={column.stage}
                        aria-label={column.name}
                      >
                        <header>
                          <h2>{column.name}</h2>
                          <span>{column.count}</span>
                        </header>
                        <div className="pipeline-cards">
                          {column.items.map((row) => (
                            <button
                              type="button"
                              className="pipeline-card"
                              key={row.id}
                              onClick={() => setDetail(row.id)}
                            >
                              <strong>{contact(row)}</strong>
                              <span>
                                {row.caller_number || "Numéro masqué"}
                              </span>
                              <span>
                                {row.owner_name || "Non attribué"} ·{" "}
                                {row.call_count} appel(s)
                              </span>
                              {row.callback_at ? (
                                <span>
                                  Rappel :{" "}
                                  {when(
                                    row.callback_at,
                                    row.callback_timezone ||
                                      board.queue.timezone,
                                  )}
                                </span>
                              ) : null}
                            </button>
                          ))}
                          {!column.items.length ? (
                            <p className="muted">Aucun suivi.</p>
                          ) : null}
                          {column.has_more ? (
                            <button
                              type="button"
                              className="button secondary"
                              disabled={moreBusy}
                              onClick={() => void more(column)}
                            >
                              Voir plus de suivis
                            </button>
                          ) : null}
                        </div>
                      </section>
                    ))}
                  </div>
                )}
              </section>
            </>
          ) : error ? null : (
            <p role="status">Chargement du pipeline…</p>
          )}
        </>
      )}
      {editing ? (
        <QueueForm
          key={editing === "new" ? "new" : editing.id}
          row={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={(id) => {
            setEditing(null);
            setSelected(id);
            setRevision((r) => r + 1);
          }}
        />
      ) : null}
      {detail && board ? (
        <FollowupDetail
          id={detail}
          queue={board.queue}
          admin={admin}
          userId={userId}
          onClose={() => setDetail(null)}
          onChanged={() => setRevision((r) => r + 1)}
        />
      ) : null}
    </>
  );
}
