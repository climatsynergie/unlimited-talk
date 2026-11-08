import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { api, message } from "./api";
import { Notice } from "./ui";

type Metrics = {
  calls: number;
  answered: number;
  incoming_calls?: number;
  incoming_answered?: number;
  incoming_talk_seconds?: number;
  voicemail?: number;
  no_answer: number;
  busy: number;
  failed: number;
  cancelled: number;
  in_progress: number;
  manual: number;
  automatic: number;
  contacts: number;
  bookings: number;
  cancelled_bookings: number;
  pauses: number;
  stops: number;
  starts: number;
  automatic_pauses: number;
  talk_seconds: number;
  duration_known: number;
  duration_missing: number;
  answer_rate: number | null;
  bookings_per_100_calls: number | null;
  average_talk_seconds: number | null;
  first_call_at: string | null;
  last_call_at: string | null;
};
type Agent = {
  id: string;
  display_name: string;
  email: string;
  role: string;
  is_active: boolean;
  metrics: Metrics;
};
type Daily = Metrics & { agent_id: string; date: string };
type Hour = Metrics & {
  starts_at: string;
  date: string;
  label: string;
  utc_offset: string;
};
type Filters = { start: string; end: string; timezone: string };
type Report = {
  period: Filters;
  generated_at: string;
  agents: Agent[];
  daily: Daily[];
  hourly: Hour[];
  totals: Metrics;
  definitions: Record<string, string>;
};
type LiveAgent = {
  id: string;
  display_name: string;
  email: string;
  status: string;
  online: boolean;
  last_seen_at: string | null;
  campaign_name: string | null;
  call_id: string | null;
  destination: string | null;
  consumed_at: string | null;
};
type Live = {
  directory_warning?: { severity: string; message: string } | null;
  generated_at: string;
  items: LiveAgent[];
  online: number;
  in_calls: number;
  connected: number;
  paused: number;
};
const STATUSES: Record<string, string> = {
  connected: "En conversation",
  calling: "Appel en cours",
  dialing: "Composeur actif",
  paused: "En pause",
  booking: "Saisie du RDV",
  available: "En ligne",
  offline: "Hors ligne",
};
const number = (value: number) => new Intl.NumberFormat("fr-CA").format(value);
function duration(value: number | null) {
  if (value === null) return "—";
  const total = Math.round(value);
  return `${Math.floor(total / 3600)} h ${String(Math.floor(total / 60) % 60).padStart(2, "0")} min ${String(total % 60).padStart(2, "0")} s`;
}
function today(zone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  return ["year", "month", "day"]
    .map((type) => parts.find((p) => p.type === type)?.value)
    .join("-");
}
function dayBefore(day: string, days: number) {
  const result = new Date(`${day}T12:00:00Z`);
  result.setUTCDate(result.getUTCDate() - days);
  return result.toISOString().slice(0, 10);
}
const shortDay = (day: string) =>
  new Intl.DateTimeFormat("fr-CA", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(`${day}T12:00:00Z`));
function query(filters: Filters, agent = "") {
  return new URLSearchParams({
    ...filters,
    ...(agent ? { agent_id: agent } : {}),
  }).toString();
}
function Rate({ value }: { value: number | null }) {
  return <>{value === null ? "—" : `${value.toLocaleString("fr-CA")} %`}</>;
}
function Measures({ metrics }: { metrics: Metrics }) {
  return (
    <div className="report-kpis">
      {[
        {
          title: "Appels lancés",
          value: number(metrics.calls),
          hint: `${number(metrics.contacts)} contacts distincts`,
          tone: "blue",
        },
        {
          title: "Décrochés clients",
          value: number(metrics.answered),
          hint:
            metrics.answer_rate === null
              ? "Aucun appel lancé"
              : `${metrics.answer_rate.toLocaleString("fr-CA")} % des appels`,
          tone: "green",
        },
        {
          title: "Boîtes vocales",
          value: number(metrics.voicemail ?? 0),
          hint: "Signalées par les agents · hors conversations",
          tone: "blue",
        },
        {
          title: "Appels entrants proposés",
          value: number(metrics.incoming_calls ?? 0),
          hint: "Présentés aux agents · séparés des appels sortants",
          tone: "blue",
        },
        {
          title: "Entrants décrochés",
          value: number(metrics.incoming_answered ?? 0),
          hint: "Appels entrants pris en charge par les agents",
          tone: "green",
        },
        {
          title: "Conversation entrante connue",
          value: duration(metrics.incoming_talk_seconds ?? 0),
          hint: "Durées confirmées des appels entrants décrochés",
          tone: "green",
        },
        {
          title: "RDV créés",
          value: number(metrics.bookings),
          hint: `${number(metrics.cancelled_bookings)} annulés (statut actuel)`,
          tone: "blue",
        },
        {
          title: "Conversation connue",
          value: metrics.duration_known ? duration(metrics.talk_seconds) : "—",
          hint: `${number(metrics.duration_known)} appels avec durée · ${number(metrics.duration_missing)} sans durée`,
          tone: "green",
        },
      ].map((card) => (
        <div className={`report-kpi tone-${card.tone}`} key={card.title}>
          <span>{card.title}</span>
          <strong>{card.value}</strong>
          <small>{card.hint}</small>
        </div>
      ))}
    </div>
  );
}
function Bars({
  rows,
  label,
}: {
  rows: { label: string; tooltip?: string; calls: number; answered: number }[];
  label: string;
}) {
  const max = Math.max(1, ...rows.map((row) => row.calls));
  const width = Math.max(600, rows.length * 18);
  const step = width / Math.max(1, rows.length);
  return (
    <div className="report-chart-scroll">
      <svg
        role="img"
        aria-label={label}
        viewBox={`0 0 ${width} 185`}
        className="report-chart"
      >
        <title>{label}</title>
        <line x1="0" y1="150" x2={width} y2="150" stroke="#dce5ef" />
        {rows.map((row, index) => (
          <g key={`${index}-${row.label}`}>
            <title>
              {row.tooltip || row.label} : {row.calls} appels, {row.answered}{" "}
              décrochés
            </title>
            <rect
              x={index * step + 3}
              y={150 - (row.calls / max) * 132}
              width={Math.max(2, step * 0.42)}
              height={(row.calls / max) * 132}
              fill="#2563eb"
              rx="3"
            />
            <rect
              x={index * step + step * 0.5}
              y={150 - (row.answered / max) * 132}
              width={Math.max(2, step * 0.42)}
              height={(row.answered / max) * 132}
              fill="#15803d"
              rx="3"
            />
            {index % Math.ceil(rows.length / 8) === 0 ? (
              <text x={index * step + 3} y="174" fill="#53667d" fontSize="11">
                {row.label}
              </text>
            ) : null}
          </g>
        ))}
      </svg>
    </div>
  );
}
export function Dashboard() {
  const [draft, setDraft] = useState<Filters>(() => {
    const end = today("America/Toronto");
    return { start: dayBefore(end, 6), end, timezone: "America/Toronto" };
  });
  const [filters, setFilters] = useState(draft);
  const [selected, setSelected] = useState("");
  const [search, setSearch] = useState("");
  const [overview, setOverview] = useState<Report | null>(null);
  const [detail, setDetail] = useState<Report | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [liveError, setLiveError] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [showOffline, setShowOffline] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const [dailyPage, setDailyPage] = useState(0);
  const [agentPage, setAgentPage] = useState(0);
  const [agentSort, setAgentSort] = useState("name");
  const [hourDay, setHourDay] = useState(filters.end);
  const download = useRef<AbortController | null>(null);
  const tabs = useRef<HTMLDivElement>(null);
  useEffect(() => () => download.current?.abort(), []);
  useEffect(() => {
    const abort = new AbortController();
    let busy = false;
    async function load() {
      if (busy || document.visibilityState === "hidden") return;
      busy = true;
      try {
        const value = await api<Live>("/reporting/live", {
          signal: AbortSignal.any([abort.signal, AbortSignal.timeout(10000)]),
        });
        if (!abort.signal.aborted) {
          setLive(value);
          setLiveError("");
        }
      } catch (e) {
        if (!abort.signal.aborted) setLiveError(message(e));
      } finally {
        busy = false;
      }
    }
    void load();
    const timer = setInterval(() => void load(), 10000);
    document.addEventListener("visibilitychange", load);
    return () => {
      abort.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", load);
    };
  }, [refresh]);
  useEffect(() => {
    const abort = new AbortController();
    let busy = false;
    async function load() {
      if (busy) return;
      busy = true;
      try {
        const value = await api<Report>(`/reporting/report?${query(filters)}`, {
          signal: AbortSignal.any([abort.signal, AbortSignal.timeout(40000)]),
        });
        if (!abort.signal.aborted) {
          setOverview(value);
          setError("");
        }
      } catch (e) {
        if (!abort.signal.aborted) setError(message(e));
      } finally {
        busy = false;
        if (!abort.signal.aborted) setLoading(false);
      }
    }
    setLoading(true);
    setOverview(null);
    void load();
    const timer = setInterval(() => {
      if (document.visibilityState !== "hidden") void load();
    }, 60000);
    return () => {
      abort.abort();
      clearInterval(timer);
    };
  }, [filters, refresh]);
  useEffect(() => {
    if (!selected) {
      setDetail(null);
      setDetailLoading(false);
      return;
    }
    const abort = new AbortController();
    let busy = false;
    async function load() {
      if (busy) return;
      busy = true;
      try {
        const value = await api<Report>(
          `/reporting/report?${query(filters, selected)}`,
          {
            signal: AbortSignal.any([abort.signal, AbortSignal.timeout(40000)]),
          },
        );
        if (!abort.signal.aborted) {
          setDetail(value);
          setError("");
        }
      } catch (e) {
        if (!abort.signal.aborted) setError(message(e));
      } finally {
        busy = false;
        if (!abort.signal.aborted) setDetailLoading(false);
      }
    }
    setDetail(null);
    setDetailLoading(true);
    void load();
    const timer = setInterval(() => {
      if (document.visibilityState !== "hidden") void load();
    }, 60000);
    return () => {
      abort.abort();
      clearInterval(timer);
    };
  }, [selected, filters, refresh]);
  useEffect(() => {
    setDailyPage(0);
    setHourDay(filters.end);
  }, [selected, filters]);
  useEffect(() => setAgentPage(0), [search, agentSort, filters]);
  function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setFilters({ ...draft });
  }
  async function excel(agent = selected) {
    if (exporting) return;
    setExporting(true);
    setExportError("");
    const controller = new AbortController();
    download.current = controller;
    try {
      const response = await fetch(
        `/api/reporting/export.xlsx?${query(filters, agent)}`,
        {
          credentials: "same-origin",
          cache: "no-store",
          signal: controller.signal,
        },
      );
      if (!response.ok) {
        if (response.status === 401)
          window.dispatchEvent(new Event("ut-session-expired"));
        const body = await response.json().catch(() => null);
        throw new Error(
          typeof body?.detail === "string"
            ? body.detail
            : "L’export n’a pas pu être créé. Réessayez.",
        );
      }
      if (
        !response.headers
          .get("Content-Type")
          ?.startsWith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          )
      )
        throw new Error("Le fichier Excel reçu est invalide.");
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download =
        response.headers
          .get("Content-Disposition")
          ?.match(/filename="([a-zA-Z0-9._-]+)"/)?.[1] ||
        `unlimited-talk-${agent || "equipe"}-${filters.start}-${filters.end}.xlsx`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      if (!controller.signal.aborted) setExportError(message(e));
    } finally {
      if (!controller.signal.aborted) setExporting(false);
    }
  }
  function keydown(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const buttons = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
    );
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? buttons.length - 1
          : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) %
            buttons.length;
    buttons[next]?.click();
    buttons[next]?.focus();
  }
  const current = selected ? detail : overview;
  const selectedAgent = detail?.agents[0];
  const visibleAgents = (overview?.agents || []).filter((agent) =>
    `${agent.display_name} ${agent.email}`
      .toLocaleLowerCase("fr")
      .includes(search.toLocaleLowerCase("fr")),
  );
  const sortedAgents = [...visibleAgents].sort((a, b) =>
    agentSort === "name"
      ? a.display_name.localeCompare(b.display_name, "fr")
      : b.metrics[agentSort as "calls" | "answered" | "bookings"] -
          a.metrics[agentSort as "calls" | "answered" | "bookings"] ||
        a.display_name.localeCompare(b.display_name, "fr"),
  );
  const agentRows = sortedAgents.slice(agentPage * 10, agentPage * 10 + 10);
  const liveMap = new Map(live?.items.map((agent) => [agent.id, agent]));
  const tabAgents: Pick<Agent, "id" | "display_name" | "email">[] = [
    ...(overview?.agents || []),
  ];
  const fallback = liveMap.get(selected) || detail?.agents[0];
  if (selected && fallback && !tabAgents.some((agent) => agent.id === selected))
    tabAgents.push({
      id: fallback.id,
      display_name: fallback.display_name,
      email: fallback.email,
    });
  const visibleTabs = tabAgents.filter(
    (agent) =>
      agent.id === selected ||
      `${agent.display_name} ${agent.email}`
        .toLocaleLowerCase("fr")
        .includes(search.toLocaleLowerCase("fr")),
  );
  const pendingFilters =
    draft.start !== filters.start ||
    draft.end !== filters.end ||
    draft.timezone !== filters.timezone;
  const daily = current?.daily || [];
  const perDay = new Map<string, { calls: number; answered: number }>();
  for (const row of daily) {
    const value = perDay.get(row.date) || { calls: 0, answered: 0 };
    value.calls += row.calls;
    value.answered += row.answered;
    perDay.set(row.date, value);
  }
  const hours = (detail?.hourly || []).filter((hour) => hour.date === hourDay);
  const dailyRows = selected
    ? daily.slice(dailyPage * 14, dailyPage * 14 + 14)
    : [];
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">PILOTAGE DE L’ÉQUIPE</span>
          <h1>Tableau de bord.</h1>
          <p>
            L’activité en direct et les résultats de chaque agent, au même
            endroit.
          </p>
        </div>
        <button
          className="button secondary"
          onClick={() => setRefresh((value) => value + 1)}
        >
          Actualiser
        </button>
      </div>
      <section className="report-live panel" aria-labelledby="live-heading">
        {live?.directory_warning ? (
          <Notice error={live.directory_warning.severity === "critical"}>
            {live.directory_warning.message}
          </Notice>
        ) : null}
        <div className="report-section-heading">
          <div>
            <span className="report-live-dot" aria-hidden="true" />
            <h2 id="live-heading">L’équipe en direct</h2>
          </div>
          <span className="report-timestamp">
            Actualisation toutes les 10 secondes
          </span>
        </div>
        {liveError ? (
          <Notice error>Le direct ne s’actualise plus : {liveError}</Notice>
        ) : null}
        <div className="report-live-counts">
          <span>
            <strong>{live?.online ?? "—"}</strong> en ligne
          </span>
          <span>
            <strong>{live?.in_calls ?? "—"}</strong> en appel
          </span>
          <span>
            <strong>{live?.connected ?? "—"}</strong> en conversation
          </span>
          <span>
            <strong>{live?.paused ?? "—"}</strong> en pause
          </span>
        </div>
        <label className="report-offline-toggle">
          <input
            type="checkbox"
            checked={showOffline}
            onChange={(event) => setShowOffline(event.target.checked)}
          />{" "}
          Afficher aussi les agents hors ligne
        </label>
        <div className="report-agent-grid">
          {live?.items
            .filter((agent) => showOffline || agent.online || agent.call_id)
            .map((agent) => (
              <article
                className={`report-agent status-${agent.status}`}
                key={agent.id}
              >
                <div className="report-agent-heading">
                  <span className="avatar avatar-small">
                    {agent.display_name.slice(0, 2).toUpperCase()}
                  </span>
                  <div>
                    <strong>{agent.display_name}</strong>
                    <span className={`report-status status-${agent.status}`}>
                      {STATUSES[agent.status] || agent.status}
                    </span>
                  </div>
                </div>
                <p>
                  {agent.call_id
                    ? agent.destination
                    : agent.campaign_name || "Aucune campagne en cours"}
                </p>
                {agent.call_id && !agent.online ? (
                  <small>Connexion du navigateur à vérifier</small>
                ) : null}
                <button
                  className="text-button"
                  onClick={() => {
                    setSelected(agent.id);
                    tabs.current?.scrollIntoView({ block: "nearest" });
                  }}
                >
                  Voir son activité
                </button>
              </article>
            ))}
        </div>
        {live?.items.length === 0 ? (
          <p className="subtle">Aucun compte agent pour le moment.</p>
        ) : null}
        <p className="report-footnote">
          En ligne = une session authentifiée a répondu dans les 90 dernières
          secondes. Une présence récente n’est pas un décompte du temps
          travaillé.
        </p>
      </section>
      <section className="report-history" aria-labelledby="history-heading">
        <div className="report-section-heading">
          <div>
            <h2 id="history-heading">Activité et résultats</h2>
            <p>
              Choisissez jusqu’à trois mois. Tous les horaires suivent le fuseau
              sélectionné.
            </p>
          </div>
          <button
            className="button success"
            disabled={
              exporting ||
              loading ||
              detailLoading ||
              !current ||
              pendingFilters
            }
            onClick={() => void excel()}
          >
            {exporting
              ? "Préparation de l’export…"
              : selected
                ? "Exporter cet agent · Excel"
                : "Exporter l’équipe · Excel"}
          </button>
        </div>
        <form className="report-filters" onSubmit={submit}>
          <label>
            Du
            <input
              type="date"
              value={draft.start}
              max={draft.end}
              required
              onChange={(e) => setDraft({ ...draft, start: e.target.value })}
            />
          </label>
          <label>
            Au
            <input
              type="date"
              value={draft.end}
              min={draft.start}
              max={today(draft.timezone)}
              required
              onChange={(e) => setDraft({ ...draft, end: e.target.value })}
            />
          </label>
          <label>
            Fuseau horaire
            <select
              value={draft.timezone}
              onChange={(e) => setDraft({ ...draft, timezone: e.target.value })}
            >
              <option value="America/Toronto">Québec / Toronto</option>
              <option value="Africa/Casablanca">Maroc</option>
              <option value="UTC">UTC</option>
            </select>
          </label>
          <button className="button info" type="submit">
            Appliquer
          </button>
          <button
            className="text-button"
            type="button"
            onClick={() => {
              const end = today(draft.timezone);
              const value = {
                start: dayBefore(end, 89),
                end,
                timezone: draft.timezone,
              };
              setDraft(value);
              setFilters(value);
            }}
          >
            90 derniers jours
          </button>
        </form>
        <p className="report-footnote">
          Période affichée : {shortDay(filters.start)} au{" "}
          {shortDay(filters.end)} · {filters.timezone}
          {pendingFilters
            ? " · Appliquez les dates pour actualiser le rapport et l’export."
            : ""}
        </p>
        {error ? <Notice error>{error}</Notice> : null}
        {exportError ? <Notice error>{exportError}</Notice> : null}
        <div className="report-agent-search">
          <label>
            Rechercher un agent
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Nom ou courriel"
            />
          </label>
          <span>
            {overview?.generated_at
              ? `Rapport actualisé à ${new Intl.DateTimeFormat("fr-CA", { timeZone: filters.timezone, timeStyle: "short" }).format(new Date(overview.generated_at))}`
              : ""}
          </span>
        </div>
        <div
          className="report-tabs"
          role="tablist"
          aria-label="Rapports des agents"
          ref={tabs}
          onKeyDown={keydown}
        >
          <button
            role="tab"
            id="report-tab-all"
            aria-controls="report-panel"
            aria-selected={!selected}
            tabIndex={selected ? -1 : 0}
            onClick={() => setSelected("")}
          >
            Vue d’ensemble
          </button>
          {visibleTabs.map((agent) => (
            <button
              role="tab"
              id={`report-tab-${agent.id}`}
              aria-controls="report-panel"
              aria-selected={selected === agent.id}
              tabIndex={selected === agent.id ? 0 : -1}
              key={agent.id}
              onClick={() => setSelected(agent.id)}
            >
              {agent.display_name}
            </button>
          ))}
        </div>
        <div
          role="tabpanel"
          id="report-panel"
          aria-labelledby={
            selected ? `report-tab-${selected}` : "report-tab-all"
          }
          aria-busy={loading || detailLoading}
        >
          {loading || detailLoading ? (
            <p className="report-loading" role="status">
              Chargement de l’activité…
            </p>
          ) : current ? (
            <>
              {selectedAgent ? (
                <div className="report-selected-agent">
                  <span className="avatar avatar-purple">
                    {selectedAgent.display_name.slice(0, 2).toUpperCase()}
                  </span>
                  <div>
                    <h3>{selectedAgent.display_name}</h3>
                    <p>
                      {selectedAgent.email}
                      {!selectedAgent.is_active ? " · Compte désactivé" : ""}
                    </p>
                  </div>
                </div>
              ) : null}
              <Measures metrics={current.totals} />
              <p className="report-footnote">
                Appels lancés, décrochés clients et graphiques : appels
                sortants. Les appels entrants sont comptés séparément. Un même
                appel présenté à plusieurs agents compte une proposition par
                agent.
              </p>
              {selected ? (
                <p className="report-footnote">
                  Durée moyenne connue :{" "}
                  {duration(current.totals.average_talk_seconds)} · RDV pour 100
                  appels :{" "}
                  {current.totals.bookings_per_100_calls === null
                    ? "—"
                    : current.totals.bookings_per_100_calls.toLocaleString(
                        "fr-CA",
                      )}
                </p>
              ) : null}
              <section className="panel report-chart-panel">
                <div className="report-section-heading">
                  <h3>
                    {selected
                      ? "Ses résultats par jour"
                      : "Évolution de l’équipe par jour"}
                  </h3>
                  <div className="report-chart-key">
                    <span>Appels</span>
                    <span>Décrochés</span>
                  </div>
                </div>
                <Bars
                  rows={Array.from(perDay, ([day, value]) => ({
                    label: shortDay(day),
                    ...value,
                  }))}
                  label="Appels lancés et décrochés par jour"
                />
              </section>
              {selected ? (
                <>
                  <section className="panel report-hourly">
                    <div className="report-section-heading">
                      <div>
                        <h3>Appels heure par heure</h3>
                        <p>
                          Les changements d’heure sont conservés avec leur
                          décalage UTC.
                        </p>
                      </div>
                      <label>
                        Journée
                        <input
                          type="date"
                          min={filters.start}
                          max={filters.end}
                          value={hourDay}
                          onChange={(e) => setHourDay(e.target.value)}
                        />
                      </label>
                    </div>
                    <Bars
                      rows={hours.map((hour) => ({
                        ...hour,
                        label: hour.label,
                        tooltip: `${hour.label} UTC${hour.utc_offset}`,
                      }))}
                      label={`Appels par heure du ${hourDay}`}
                    />
                    <div className="report-hour-cells">
                      {hours.map((hour) => (
                        <div key={hour.starts_at}>
                          <span>
                            {hour.label}
                            <small>UTC{hour.utc_offset}</small>
                          </span>
                          <strong>{number(hour.calls)}</strong>
                          <small>
                            {number(hour.answered)} décrochés sortants
                          </small>
                          <small>
                            {number(hour.incoming_calls ?? 0)} entrants proposés
                            · {number(hour.incoming_answered ?? 0)} décrochés
                          </small>
                          <small>
                            {duration(hour.incoming_talk_seconds ?? 0)} de
                            conversation entrante
                          </small>
                        </div>
                      ))}
                    </div>
                  </section>
                  <div className="report-extra-metrics">
                    {[
                      ["Pauses enregistrées", current.totals.pauses],
                      ["Arrêts enregistrés", current.totals.stops],
                      ["Démarrages / reprises", current.totals.starts],
                      ["Appels manuels", current.totals.manual],
                      ["Appels automatiques", current.totals.automatic],
                      ["Sans réponse", current.totals.no_answer],
                      ["Occupés", current.totals.busy],
                      ["Échecs", current.totals.failed],
                    ].map(([label, value]) => (
                      <div key={label}>
                        <span>{label}</span>
                        <strong>{number(Number(value))}</strong>
                      </div>
                    ))}
                  </div>
                  <div className="panel report-table-panel">
                    <h3>Journal quotidien</h3>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            {[
                              "Date",
                              "Appels",
                              "Décrochés clients",
                              "Boîtes vocales",
                              "Entrants proposés",
                              "Entrants décrochés",
                              "Conversation entrante connue",
                              "Taux",
                              "RDV",
                              "Pauses",
                              "Arrêts",
                              "Conversation connue",
                            ].map((label) => (
                              <th key={label}>{label}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {dailyRows.map((day) => (
                            <tr key={day.date}>
                              <th scope="row">{shortDay(day.date)}</th>
                              <td>{number(day.calls)}</td>
                              <td>{number(day.answered)}</td>
                              <td>{number(day.voicemail ?? 0)}</td>
                              <td>{number(day.incoming_calls ?? 0)}</td>
                              <td>{number(day.incoming_answered ?? 0)}</td>
                              <td>
                                {duration(day.incoming_talk_seconds ?? 0)}
                              </td>
                              <td>
                                <Rate value={day.answer_rate} />
                              </td>
                              <td>{number(day.bookings)}</td>
                              <td>{number(day.pauses)}</td>
                              <td>{number(day.stops)}</td>
                              <td>
                                {day.duration_known
                                  ? duration(day.talk_seconds)
                                  : "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="report-pagination">
                      <button
                        className="button secondary"
                        disabled={dailyPage === 0}
                        onClick={() => setDailyPage((value) => value - 1)}
                      >
                        Jours précédents
                      </button>
                      <span>
                        {dailyPage * 14 + 1}–
                        {Math.min(dailyPage * 14 + 14, daily.length)} sur{" "}
                        {daily.length} jours
                      </span>
                      <button
                        className="button secondary"
                        disabled={(dailyPage + 1) * 14 >= daily.length}
                        onClick={() => setDailyPage((value) => value + 1)}
                      >
                        Jours suivants
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <div className="panel report-table-panel">
                  <div className="report-section-heading">
                    <h3>Comparaison des agents</h3>
                    <label className="report-sort">
                      Trier les agents
                      <select
                        value={agentSort}
                        onChange={(event) => setAgentSort(event.target.value)}
                      >
                        <option value="name">Nom</option>
                        <option value="calls">Appels lancés</option>
                        <option value="answered">Décrochés</option>
                        <option value="bookings">RDV créés</option>
                      </select>
                    </label>
                  </div>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          {[
                            "Agent",
                            "État actuel",
                            "Appels",
                            "Décrochés clients",
                            "Boîtes vocales",
                            "Entrants proposés",
                            "Entrants décrochés",
                            "Conversation entrante connue",
                            "RDV",
                            "Pauses",
                            "Arrêts",
                            "Export",
                          ].map((label) => (
                            <th key={label}>{label}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {agentRows.map((agent) => (
                          <tr key={agent.id}>
                            <th scope="row">
                              <button
                                className="text-button"
                                onClick={() => setSelected(agent.id)}
                              >
                                {agent.display_name}
                              </button>
                              <small>{agent.email}</small>
                            </th>
                            <td>
                              <span
                                className={`report-status status-${liveMap.get(agent.id)?.status || "offline"}`}
                              >
                                {
                                  STATUSES[
                                    liveMap.get(agent.id)?.status || "offline"
                                  ]
                                }
                              </span>
                            </td>
                            <td>{number(agent.metrics.calls)}</td>
                            <td>{number(agent.metrics.answered)}</td>
                            <td>{number(agent.metrics.voicemail ?? 0)}</td>
                            <td>{number(agent.metrics.incoming_calls ?? 0)}</td>
                            <td>
                              {number(agent.metrics.incoming_answered ?? 0)}
                            </td>
                            <td>
                              {duration(
                                agent.metrics.incoming_talk_seconds ?? 0,
                              )}
                            </td>
                            <td>{number(agent.metrics.bookings)}</td>
                            <td>{number(agent.metrics.pauses)}</td>
                            <td>{number(agent.metrics.stops)}</td>
                            <td>
                              <button
                                className="text-button"
                                disabled={exporting}
                                aria-label={`Exporter Excel pour ${agent.display_name}`}
                                onClick={() => void excel(agent.id)}
                              >
                                Excel
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {!visibleAgents.length ? (
                    <p className="subtle">Aucun agent correspondant.</p>
                  ) : null}
                  {visibleAgents.length > 10 ? (
                    <div className="report-pagination">
                      <button
                        className="button secondary"
                        disabled={agentPage === 0}
                        onClick={() => setAgentPage((value) => value - 1)}
                      >
                        Agents précédents
                      </button>
                      <span>
                        {agentPage * 10 + 1}–
                        {Math.min(agentPage * 10 + 10, visibleAgents.length)}{" "}
                        sur {visibleAgents.length} agents
                      </span>
                      <button
                        className="button secondary"
                        disabled={(agentPage + 1) * 10 >= visibleAgents.length}
                        onClick={() => setAgentPage((value) => value + 1)}
                      >
                        Agents suivants
                      </button>
                    </div>
                  ) : null}
                </div>
              )}
              <details className="report-definitions">
                <summary>Comment lire les indicateurs</summary>
                <dl>
                  {Object.entries(current.definitions).map(([key, value]) => (
                    <div key={key}>
                      <dt>
                        {{
                          calls: "Appels lancés",
                          answered: "Décrochés clients",
                          voicemail: "Boîtes vocales",
                          incoming: "Appels entrants",
                          incoming_calls: "Entrants proposés",
                          incoming_answered: "Entrants décrochés",
                          incoming_talk_seconds: "Conversation entrante connue",
                          talk: "Durées",
                          bookings: "Rendez-vous",
                          pauses: "Pauses et arrêts",
                          time: "Temps et fuseaux",
                        }[key] || key}
                      </dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            </>
          ) : null}
        </div>
      </section>
    </>
  );
}
