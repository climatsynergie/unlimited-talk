import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, date, message } from "./api";
import { Modal, Notice, Submit } from "./ui";

type Status = "booked" | "completed" | "cancelled" | "no_show";
type Appointment = {
  id: string;
  campaign_id: string;
  contact_id: string;
  created_by: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  notes: string;
  status: Status;
  version: number;
  phone: string;
  profile: Record<string, string>;
  campaign_name: string;
  creator_name: string;
};
type Event = {
  id: string;
  action: string;
  actor_name: string;
  created_at: string;
  details: { before?: Partial<Appointment>; after?: Partial<Appointment> };
};
type Detail = {
  appointment: Appointment;
  can_edit: boolean;
  events: Event[];
  has_more: boolean;
};
type Choice = { starts_at: string; utc_offset_minutes: number; label: string };
export type BookingContact = {
  campaign_id: string;
  contact_id: string;
  membership_version: number;
  timezone: string;
};
const statuses: Record<Status, string> = {
  booked: "RDV booké",
  completed: "Terminé",
  cancelled: "Annulé",
  no_show: "Absent",
};
const zones = [
  "America/Toronto",
  "America/Vancouver",
  "America/Edmonton",
  "America/Winnipeg",
  "America/Halifax",
  "America/St_Johns",
  "America/Regina",
  "America/Moncton",
  "America/Blanc-Sablon",
  "America/Whitehorse",
  "UTC",
];
function day(value: string, zone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(value));
  const part = (kind: string) => parts.find((p) => p.type === kind)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}
function local(value: string, zone: string) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));
  return `${day(value, zone)}T${parts.find((p) => p.type === "hour")?.value}:${parts.find((p) => p.type === "minute")?.value}`;
}
function shift(value: string, days: number) {
  const d = new Date(value + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
function when(value: string, zone: string) {
  const instant = new Date(value);
  const text = new Intl.DateTimeFormat("fr-CA", {
    timeZone: zone,
    dateStyle: "medium",
    timeStyle: "short",
  }).format(instant);
  const offset = new Intl.DateTimeFormat("fr-CA", {
    timeZone: zone,
    timeZoneName: "longOffset",
  })
    .formatToParts(instant)
    .find((p) => p.type === "timeZoneName")?.value;
  return `${text} (${offset})`;
}

function Timezone({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (s: string) => void;
  disabled?: boolean;
}) {
  return (
    <label>
      Fuseau horaire
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        {Array.from(new Set([...zones, value])).map((z) => (
          <option key={z} value={z}>
            {z}
          </option>
        ))}
      </select>
    </label>
  );
}

export function AppointmentForm({
  contact,
  appointment,
  onSaved,
  onCancel,
}: {
  contact?: BookingContact;
  appointment?: Appointment;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [zone, setZone] = useState(
    appointment?.timezone || contact?.timezone || "America/Toronto",
  );
  const [start, setStart] = useState(
    appointment ? local(appointment.starts_at, appointment.timezone) : "",
  );
  const [duration, setDuration] = useState(
    appointment
      ? (Date.parse(appointment.ends_at) - Date.parse(appointment.starts_at)) /
          60000
      : 30,
  );
  const [notes, setNotes] = useState(appointment?.notes || "");
  const [status, setStatus] = useState<Status>(appointment?.status || "booked");
  const [choices, setChoices] = useState<Choice[]>([]);
  const [offset, setOffset] = useState("");
  const [resolving, setResolving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(crypto.randomUUID());
  const originalOffset = appointment
    ? (Date.parse(local(appointment.starts_at, appointment.timezone) + "Z") -
        Date.parse(appointment.starts_at)) /
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
      `/calendar/resolve?${new URLSearchParams({ local_start: start, timezone: zone })}`,
      { signal: controller.signal },
    )
      .then((r) => {
        setChoices(r.options);
        if (r.options.length === 1)
          setOffset(String(r.options[0].utc_offset_minutes));
        else if (
          appointment &&
          start === local(appointment.starts_at, appointment.timezone) &&
          zone === appointment.timezone
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
  }, [start, zone, appointment, originalOffset]);
  async function save(e: FormEvent) {
    e.preventDefault();
    if (resolving || !choices.length || offset === "") return;
    setBusy(true);
    setError("");
    try {
      const schedule = {
        local_start: start,
        timezone: zone,
        utc_offset_minutes: Number(offset),
        duration_minutes: duration,
        notes,
      };
      await api(appointment ? `/calendar/${appointment.id}` : "/calendar", {
        method: appointment ? "PATCH" : "POST",
        body: appointment
          ? { ...schedule, status, version: appointment.version }
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
          Date et heure du rendez-vous
          <input
            type="datetime-local"
            required
            min="2000-01-01T00:00"
            max="2100-12-31T23:59"
            value={start}
            onChange={(e) => {
              setStart(e.target.value);
              requestId.current = crypto.randomUUID();
            }}
          />
        </label>
        <Timezone
          value={zone}
          onChange={(v) => {
            setZone(v);
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
          Durée en minutes
          <input
            type="number"
            min="5"
            max="1440"
            required
            value={duration}
            onChange={(e) => {
              setDuration(Number(e.target.value));
              requestId.current = crypto.randomUUID();
            }}
          />
        </label>
        <label>
          Notes du rendez-vous
          <textarea
            maxLength={5000}
            value={notes}
            onChange={(e) => {
              setNotes(e.target.value);
              requestId.current = crypto.randomUUID();
            }}
          />
        </label>
        {appointment ? (
          <label>
            Statut
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
        ) : null}
      </fieldset>
      <div className="actions">
        <Submit
          busy={busy}
          disabled={resolving || !choices.length || offset === ""}
        >
          {appointment
            ? "Enregistrer les modifications"
            : "Confirmer le rendez-vous"}
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

function AppointmentDetail({
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
    api<Detail>(`/calendar/${id}`, { signal: controller.signal })
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
        `/calendar/${id}?before=${data.events.at(-1)?.id}`,
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
  const a = data?.appointment;
  return (
    <Modal
      title="Rendez-vous — Unlimited Talks"
      onClose={onClose}
      busy={editing || busy}
    >
      {error ? <Notice error>{error}</Notice> : null}
      {!a ? (
        <p role="status">Chargement du rendez-vous…</p>
      ) : (
        <>
          <dl className="contact-profile">
            <div>
              <dt>Contact</dt>
              <dd>
                {a.profile.display_name ||
                  [a.profile.first_name, a.profile.last_name]
                    .filter(Boolean)
                    .join(" ") ||
                  a.phone}
              </dd>
            </div>
            <div>
              <dt>Téléphone</dt>
              <dd>{a.phone}</dd>
            </div>
            {Object.entries(a.profile)
              .filter(
                ([k]) =>
                  !["display_name", "first_name", "last_name"].includes(k),
              )
              .map(([k, v]) => (
                <div key={k}>
                  <dt>
                    {{
                      email: "Courriel",
                      address: "Adresse",
                      city: "Ville",
                      province: "Province",
                      postal_code: "Code postal",
                    }[k] || k}
                  </dt>
                  <dd>{v}</dd>
                </div>
              ))}
            <div>
              <dt>Campagne d’origine</dt>
              <dd>{a.campaign_name}</dd>
            </div>
            <div>
              <dt>Créé par</dt>
              <dd>{a.creator_name}</dd>
            </div>
            <div>
              <dt>Date et heure</dt>
              <dd>
                {when(a.starts_at, a.timezone)} · {a.timezone}
              </dd>
            </div>
            <div>
              <dt>Durée</dt>
              <dd>
                {(Date.parse(a.ends_at) - Date.parse(a.starts_at)) / 60000}{" "}
                minutes
              </dd>
            </div>
            <div>
              <dt>Statut</dt>
              <dd>{statuses[a.status]}</dd>
            </div>
            <div>
              <dt>Notes</dt>
              <dd className="appointment-notes">{a.notes || "Aucune note."}</dd>
            </div>
          </dl>
          {editing ? (
            <AppointmentForm
              appointment={a}
              onCancel={() => setEditing(false)}
              onSaved={() => {
                setEditing(false);
                setData(null);
                setRevision((n) => n + 1);
                onChanged();
              }}
            />
          ) : data?.can_edit ? (
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setEditing(true)}
            >
              Modifier ou annuler le rendez-vous
            </button>
          ) : null}
          <h3>Historique du rendez-vous</h3>
          <ul className="contact-notes">
            {data?.events.map((e) => (
              <li key={e.id}>
                <strong>
                  {e.action === "appointment.created"
                    ? "Rendez-vous créé"
                    : "Rendez-vous modifié"}
                </strong>
                <small>
                  {e.actor_name} · {date(e.created_at)}
                </small>
                {e.details.before ? (
                  <p>
                    Avant :{" "}
                    {when(
                      e.details.before.starts_at!,
                      e.details.before.timezone!,
                    )}{" "}
                    · {e.details.before.timezone} ·{" "}
                    {statuses[e.details.before.status!]} ·{" "}
                    {(Date.parse(e.details.before.ends_at!) -
                      Date.parse(e.details.before.starts_at!)) /
                      60000}{" "}
                    min
                    {e.details.before.notes
                      ? `\nNotes : ${e.details.before.notes}`
                      : ""}
                  </p>
                ) : null}
                {e.details.after ? (
                  <p>
                    {e.details.before ? "Après" : "Prévu"} :{" "}
                    {when(
                      e.details.after.starts_at!,
                      e.details.after.timezone!,
                    )}{" "}
                    · {e.details.after.timezone} ·{" "}
                    {statuses[e.details.after.status!]} ·{" "}
                    {(Date.parse(e.details.after.ends_at!) -
                      Date.parse(e.details.after.starts_at!)) /
                      60000}{" "}
                    min
                    {e.details.after.notes
                      ? `\nNotes : ${e.details.after.notes}`
                      : ""}
                  </p>
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

export function Calendar({ userId }: { userId: string }) {
  const [start, setStart] = useState(() => {
    const today = day(new Date().toISOString(), "America/Toronto");
    return shift(
      today,
      -((new Date(today + "T12:00:00Z").getUTCDay() + 6) % 7),
    );
  });
  const [zone, setZone] = useState("America/Toronto");
  const [mine, setMine] = useState(false);
  const [status, setStatus] = useState("upcoming");
  const [view, setView] = useState("agenda");
  const [items, setItems] = useState<Appointment[]>([]);
  const [more, setMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    async function load() {
      const dates = await Promise.all(
        [start, shift(start, 7)].map((d) =>
          api<{ options: Choice[] }>(
            `/calendar/resolve?${new URLSearchParams({ local_start: d + "T00:00", timezone: zone })}`,
            { signal: controller.signal },
          ),
        ),
      );
      if (dates.some((d) => !d.options.length))
        throw new Error(
          "Le début de cette période n’existe pas dans ce fuseau. Choisissez un autre fuseau.",
        );
      const params = new URLSearchParams({
        start: dates[0].options[0].starts_at,
        end: dates[1].options[0].starts_at,
        offset: String(offset),
      });
      if (mine) params.set("creator", userId);
      if (status === "upcoming") params.set("exclude_cancelled", "true");
      if (status !== "upcoming" && status !== "all")
        params.set("status", status);
      const r = await api<{ items: Appointment[]; has_more: boolean }>(
        `/calendar?${params}`,
        { signal: controller.signal },
      );
      setItems(r.items);
      setMore(r.has_more);
    }
    load()
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [start, zone, mine, status, offset, revision, userId]);
  const visible = items.filter(
    (a) => status !== "upcoming" || a.status !== "cancelled",
  );
  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>Calendrier</h1>
          <p>Unlimited Talks — rendez-vous partagés de l’équipe.</p>
        </div>
      </div>
      <div className="calendar-controls">
        <label>
          Semaine à partir du
          <input
            type="date"
            required
            value={start}
            min="2000-01-01"
            max="2100-12-24"
            onChange={(e) => {
              if (e.target.value) {
                setStart(e.target.value);
                setOffset(0);
              }
            }}
          />
        </label>
        <Timezone
          value={zone}
          onChange={(v) => {
            setZone(v);
            setOffset(0);
          }}
        />
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
            <option value="mine">Mes rendez-vous</option>
          </select>
        </label>
        <label>
          Statut
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="upcoming">Tous sauf annulés</option>
            <option value="all">Tous les statuts</option>
            {Object.entries(statuses).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          Affichage
          <select value={view} onChange={(e) => setView(e.target.value)}>
            <option value="agenda">Agenda</option>
            <option value="week">Semaine</option>
          </select>
        </label>
      </div>
      <div className="actions">
        <button
          className="button secondary"
          onClick={() => {
            setStart(shift(start, -7));
            setOffset(0);
          }}
        >
          Semaine précédente
        </button>
        <button
          className="button secondary"
          onClick={() => {
            setStart(shift(start, 7));
            setOffset(0);
          }}
        >
          Semaine suivante
        </button>
        <button
          className="button secondary"
          onClick={() => setRevision((n) => n + 1)}
        >
          Actualiser
        </button>
      </div>
      <p>
        Pour prendre rendez-vous, ouvrez un contact dans sa campagne et
        choisissez « Prendre rendez-vous ».
      </p>
      {error ? <Notice error>{error}</Notice> : null}
      {loading ? (
        <p role="status">Chargement des rendez-vous…</p>
      ) : error ? null : (
        <>
          <div
            className={view === "week" ? "calendar-week" : "calendar-agenda"}
          >
            {Array.from({ length: 7 }, (_, i) => shift(start, i)).map((d) => (
              <section key={d} className="calendar-day">
                <h2>
                  {new Intl.DateTimeFormat("fr-CA", {
                    dateStyle: "full",
                    timeZone: "UTC",
                  }).format(new Date(d + "T12:00:00Z"))}
                </h2>
                {visible
                  .filter(
                    (a) =>
                      day(a.starts_at, zone) === d ||
                      (day(a.starts_at, zone) < d && day(a.ends_at, zone) >= d),
                  )
                  .map((a) => (
                    <button
                      className={`appointment-card status-${a.status}`}
                      key={a.id}
                      onClick={() => setSelected(a.id)}
                    >
                      <strong>
                        {when(a.starts_at, zone)} —{" "}
                        {new Intl.DateTimeFormat("fr-CA", {
                          timeZone: zone,
                          timeStyle: "short",
                        }).format(new Date(a.ends_at))}
                      </strong>
                      <span>
                        {a.profile.display_name ||
                          [a.profile.first_name, a.profile.last_name]
                            .filter(Boolean)
                            .join(" ") ||
                          a.phone}
                      </span>
                      <span>
                        {a.campaign_name} · {a.creator_name}
                      </span>
                      <small>{statuses[a.status]}</small>
                    </button>
                  ))}
                {!visible.some(
                  (a) =>
                    day(a.starts_at, zone) === d ||
                    (day(a.starts_at, zone) < d && day(a.ends_at, zone) >= d),
                ) ? (
                  <p className="subtle">Aucun rendez-vous.</p>
                ) : null}
              </section>
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
              disabled={!more || loading}
              onClick={() => setOffset((n) => n + 100)}
            >
              Résultats suivants
            </button>
          </div>
          {more ? (
            <p>D’autres rendez-vous sont disponibles sur la page suivante.</p>
          ) : null}
        </>
      )}
      {selected ? (
        <AppointmentDetail
          id={selected}
          onClose={() => setSelected(null)}
          onChanged={() => setRevision((n) => n + 1)}
        />
      ) : null}
    </section>
  );
}
