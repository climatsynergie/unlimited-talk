import { useEffect, useRef, useState } from "react";
import { api, message } from "./api";
import { Notice } from "./ui";

type Agent = {
  id: string;
  display_name: string;
  email: string;
  is_active: boolean;
  assigned: boolean;
};
type Change = {
  user_id: string;
  expected_assigned: boolean;
  is_active: boolean;
};

export function CampaignTeam({
  campaignId,
  active,
  onChanged,
  onBusyChange,
}: {
  campaignId: string;
  active: boolean;
  onChanged: () => void;
  onBusyChange: (busy: boolean) => void;
}) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [assigned, setAssigned] = useState(0);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [changes, setChanges] = useState<Record<string, Change>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const requestId = useRef(crypto.randomUUID());
  const lifetime = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (search.trim() === q) return;
    const timer = setTimeout(() => {
      setQ(search.trim());
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [search, q]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ offset: String(offset), q });
    if (filter !== "all")
      params.set("assigned", filter === "assigned" ? "true" : "false");
    if (filter === "available") params.set("active_only", "true");
    api<{
      items: Agent[];
      has_more: boolean;
      total?: number;
      assigned_count?: number;
    }>(`/campaigns/${campaignId}/agents?${params}`, {
      signal: controller.signal,
    })
      .then((r) => {
        if (controller.signal.aborted) return;
        setAgents(r.items);
        setMore(r.has_more);
        setTotal(r.total ?? r.items.length);
        setAssigned(
          r.assigned_count ?? r.items.filter((a) => a.assigned).length,
        );
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [campaignId, offset, q, filter, revision]);
  function select(selected: Agent[], enabled: boolean) {
    const next = { ...changes };
    let limited = false;
    for (const agent of selected) {
      if (enabled && !agent.is_active) continue;
      const expected = next[agent.id]?.expected_assigned ?? agent.assigned;
      if (expected === enabled) delete next[agent.id];
      else if (!(agent.id in next) && Object.keys(next).length >= 100)
        limited = true;
      else
        next[agent.id] = {
          user_id: agent.id,
          expected_assigned: expected,
          is_active: enabled,
        };
    }
    setChanges(next);
    if (limited)
      setError(
        "Enregistrez ces 100 modifications avant de sélectionner d’autres agents.",
      );
    requestId.current = crypto.randomUUID();
    setNotice("");
  }
  async function save() {
    const signal = lifetime.current?.signal;
    if (busy || !signal || !Object.keys(changes).length) return;
    setBusy(true);
    onBusyChange(true);
    setError("");
    setNotice("");
    try {
      const r = await api<{ assigned_count: number }>(
        `/campaigns/${campaignId}/agents`,
        {
          method: "PUT",
          signal,
          body: {
            request_id: requestId.current,
            changes: Object.values(changes),
          },
        },
      );
      if (signal.aborted) return;
      setChanges({});
      setOffset(0);
      setAssigned(r.assigned_count);
      setRevision((n) => n + 1);
      requestId.current = crypto.randomUUID();
      setNotice("L’équipe de la campagne a été enregistrée.");
      onChanged();
    } catch (e) {
      if (!signal.aborted) setError(message(e));
    } finally {
      if (!signal.aborted) {
        setBusy(false);
        onBusyChange(false);
      }
    }
  }
  const pending = Object.keys(changes).length;
  return (
    <section className="campaign-team" aria-labelledby="campaign-team-title">
      <div className="team-summary">
        <div>
          <span className="eyebrow">ÉQUIPE DE LA CAMPAGNE</span>
          <h3 id="campaign-team-title">Agents attribués</h3>
          <p>
            Choisissez les agents qui peuvent travailler dans cette campagne.
          </p>
        </div>
        <span className="team-count">
          {assigned} attribué{assigned !== 1 ? "s" : ""}
        </span>
      </div>
      {error ? (
        <Notice error>
          {error}{" "}
          <button
            type="button"
            className="text-button"
            disabled={busy}
            onClick={() => {
              setChanges({});
              requestId.current = crypto.randomUUID();
              setRevision((n) => n + 1);
            }}
          >
            Recharger l’équipe
          </button>
        </Notice>
      ) : null}
      {notice ? <Notice>{notice}</Notice> : null}
      {!active ? (
        <Notice>
          La campagne est archivée. Réactivez-la pour modifier son équipe.
        </Notice>
      ) : null}
      <label className="team-search">
        Rechercher un agent
        <input
          type="search"
          placeholder="Nom ou courriel…"
          value={search}
          disabled={busy}
          maxLength={120}
          onChange={(e) => setSearch(e.target.value)}
        />
      </label>
      <div className="team-filter-row">
        <div className="segmented-control" aria-label="Filtrer les agents">
          {[
            ["all", "Tous"],
            ["assigned", "Attribués"],
            ["available", "Disponibles"],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              disabled={busy}
              onClick={() => {
                setFilter(value);
                setOffset(0);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          className="text-button"
          type="button"
          disabled={busy || loading || !active || !agents.length}
          onClick={() => select(agents, true)}
        >
          Sélectionner la page
        </button>
      </div>
      <div className="team-agent-grid" aria-busy={loading}>
        {agents.map((agent) => {
          const selected = changes[agent.id]?.is_active ?? agent.assigned;
          return (
            <label
              className={`team-agent ${selected ? "is-selected" : ""}`}
              key={agent.id}
            >
              <input
                type="checkbox"
                checked={selected}
                disabled={
                  busy || loading || !active || (!agent.is_active && !selected)
                }
                onChange={(e) => select([agent], e.target.checked)}
              />
              <span className="team-agent-avatar" aria-hidden="true">
                {agent.display_name
                  .split(/\s+/)
                  .map((s) => s[0])
                  .slice(0, 2)
                  .join("")
                  .toUpperCase()}
              </span>
              <span className="team-agent-info">
                <strong>{agent.display_name}</strong>
                <small>{agent.email}</small>
                <span
                  className={`team-agent-state ${agent.is_active ? "" : "inactive"}`}
                >
                  {!agent.is_active
                    ? "Compte désactivé"
                    : selected
                      ? "Attribué à la campagne"
                      : "Disponible"}
                </span>
              </span>
            </label>
          );
        })}
        {!agents.length && !loading ? (
          <p className="team-empty">
            {q || filter !== "all"
              ? "Aucun agent ne correspond à cette recherche."
              : "Aucun compte agent disponible."}
          </p>
        ) : null}
      </div>
      {loading ? <p role="status">Chargement des agents…</p> : null}
      {offset > 0 || more ? (
        <div className="team-pagination">
          <small>
            {offset + 1}–{offset + agents.length} sur {total} agents
          </small>
          <div className="actions">
            <button
              type="button"
              className="button secondary"
              disabled={busy || loading || !offset}
              onClick={() => setOffset((n) => Math.max(0, n - 50))}
            >
              Agents précédents
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={busy || loading || !more}
              onClick={() => setOffset((n) => n + 50)}
            >
              Agents suivants
            </button>
          </div>
        </div>
      ) : null}
      <div className="team-savebar">
        <span role="status">
          {pending
            ? `${pending} modification${pending > 1 ? "s" : ""} en attente`
            : "L’équipe est à jour"}
        </span>
        <div className="actions">
          {pending ? (
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => {
                setChanges({});
                requestId.current = crypto.randomUUID();
              }}
            >
              Annuler les changements
            </button>
          ) : null}
          <button
            type="button"
            className="button"
            disabled={busy || loading || !active || !pending}
            onClick={() => void save()}
          >
            {busy ? "Enregistrement…" : "Enregistrer l’équipe"}
          </button>
        </div>
      </div>
    </section>
  );
}
