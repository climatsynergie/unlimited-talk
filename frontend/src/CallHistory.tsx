import { useCallback, useEffect, useRef, useState } from "react";
import { api, date, message } from "./api";
import { Notice, Field, Icon } from "./ui";
import { CallContactDialog } from "./Campaigns";

export type Recording = {
  sid: string;
  state: string;
  duration: number;
  playback_path: string | null;
  archive_status?: string;
};
type Call = {
  id: string;
  created_at: string;
  destination: string;
  state: string;
  outcome: string | null;
  actor_name: string;
  actor_id?: string;
  contact_name?: string | null;
  campaign_name?: string | null;
  campaign_id?: string | null;
  contact_id?: string | null;
  caller_number?: string;
  finished_at?: string | null;
  recordings: Recording[];
};
type Cursor = { id: string; created_at: string };
type Result = { items: Call[]; next_cursor: Cursor | null };
const states: Record<string, string> = {
  reserved: "Préparé",
  authorized: "Connexion en cours",
  ringing: "Sonnerie",
  answered: "En conversation",
  finished: "Terminé",
  cancelled: "Annulé",
  expired: "Expiré",
};
const outcomes: Record<string, string> = {
  completed: "Terminé",
  busy: "Occupé",
  "no-answer": "Pas de réponse",
  failed: "Échec",
  canceled: "Annulé",
};

export function RecordingPlayer({
  recording,
  disabled,
}: {
  recording: Recording;
  disabled: boolean;
}) {
  const [error, setError] = useState(false);
  const player = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    const audio = player.current;
    return () => {
      audio?.pause();
      audio?.removeAttribute("src");
      audio?.load();
    };
  }, [recording.playback_path, disabled]);
  if (disabled) return <p>Lecture suspendue pendant l’appel.</p>;
  if (!recording.playback_path)
    return (
      <p className="audio-result">
        {recording.archive_status === "retrying"
          ? "Enregistrement : sauvegarde différée, une nouvelle tentative est prévue."
          : "Enregistrement : sauvegarde privée en cours."}
      </p>
    );
  return (
    <div className="recording-player">
      <p>Enregistrement · {recording.duration} s</p>
      <audio
        ref={player}
        controls
        preload="none"
        src={recording.playback_path}
        aria-label="Lire l’enregistrement de cet appel"
        onError={() => setError(true)}
      />
      {error ? (
        <>
          <Notice error>La lecture est temporairement indisponible.</Notice>
          <button
            type="button"
            className="button secondary"
            onClick={() => {
              setError(false);
              player.current?.load();
              void player.current?.play().catch(() => setError(true));
            }}
          >
            Réessayer la lecture
          </button>
        </>
      ) : null}
    </div>
  );
}

type Filters = {
  q: string;
  outcome: string;
  day: string;
  actor: string;
  recordings: boolean;
  destination: string;
};
const emptyFilters: Filters = {
  q: "",
  outcome: "",
  day: "",
  actor: "",
  recordings: false,
  destination: "",
};

export function CallHistory({
  disabled = false,
  admin = false,
}: {
  disabled?: boolean;
  admin?: boolean;
}) {
  const [calls, setCalls] = useState<Call[]>([]);
  const [cursor, setCursor] = useState<Cursor | null>(null);
  const [pages, setPages] = useState<(Cursor | null)[]>([null]);
  const [selected, setSelected] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [draft, setDraft] = useState<Filters>(emptyFilters);
  const [agents, setAgents] = useState<{ id: string; display_name: string }[]>(
    [],
  );
  const [contactOpen, setContactOpen] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const sequence = useRef(0);

  useEffect(() => {
    if (!admin) return;
    const controller = new AbortController();
    api<{ items: { id: string; display_name: string }[] }>(
      "/telephony/call-agents",
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted) setAgents(result.items);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [admin]);

  const load = useCallback(
    async (nextPages: (Cursor | null)[] = [null]) => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      const current = ++sequence.current;
      setBusy(true);
      setError("");
      const query = new URLSearchParams();
      const next = nextPages[nextPages.length - 1];
      if (next) {
        query.set("before_id", next.id);
        query.set("before_created_at", next.created_at);
      }
      if (filters.q.trim()) query.set("q", filters.q.trim());
      if (filters.outcome) query.set("outcome", filters.outcome);
      if (filters.actor) query.set("actor_id", filters.actor);
      if (filters.recordings) query.set("recordings_only", "true");
      if (filters.destination) query.set("destination", filters.destination);
      if (filters.day) {
        const from = new Date(filters.day + "T00:00:00");
        const until = new Date(from);
        until.setDate(until.getDate() + 1);
        query.set("from_at", from.toISOString());
        query.set("until_at", until.toISOString());
      }
      try {
        const result = await api<Result>(
          "/telephony/calls" + (query.size ? "?" + query : ""),
          { signal: controller.signal },
        );
        if (controller.signal.aborted || current !== sequence.current) return;
        setCalls(result.items);
        setCursor(result.next_cursor);
        setPages(nextPages);
        setSelected((old) =>
          result.items.some((call) => call.id === old)
            ? old
            : result.items[0]?.id || null,
        );
      } catch (failure) {
        if (!controller.signal.aborted && current === sequence.current)
          setError(message(failure));
      } finally {
        if (!controller.signal.aborted && current === sequence.current)
          setBusy(false);
      }
    },
    [filters],
  );
  useEffect(() => {
    void load();
    return () => {
      request.current?.abort();
      sequence.current += 1;
    };
  }, [load, disabled]);
  const call = calls.find((item) => item.id === selected);
  function applyFilters(next: Filters) {
    setCalls([]);
    setCursor(null);
    setPages([null]);
    setSelected(null);
    setFilters(next);
  }
  return (
    <section
      className="panel call-inbox"
      aria-labelledby="call-history-heading"
    >
      <div className="panel-toolbar">
        <div>
          <span className="eyebrow">VOS CONVERSATIONS</span>
          <h2 id="call-history-heading">Historique des appels</h2>
        </div>
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={() => void load(pages)}
        >
          Actualiser les appels
        </button>
      </div>
      <form
        className="call-history-filters"
        onSubmit={(event) => {
          event.preventDefault();
          applyFilters({ ...draft });
        }}
      >
        <Field
          label="Rechercher dans les appels"
          type="search"
          placeholder="Nom, numéro, campagne ou agent"
          maxLength={120}
          value={draft.q}
          onChange={(event) => setDraft({ ...draft, q: event.target.value })}
        />
        <label>
          Résultat
          <select
            value={draft.outcome}
            onChange={(event) =>
              setDraft({ ...draft, outcome: event.target.value })
            }
          >
            <option value="">Tous les résultats</option>
            <option value="completed">Terminés</option>
            <option value="no-answer">Pas de réponse</option>
            <option value="busy">Occupés</option>
            <option value="failed">Échecs</option>
            <option value="canceled">Annulés</option>
          </select>
        </label>
        <Field
          label="Jour de l’appel"
          type="date"
          value={draft.day}
          onChange={(event) => setDraft({ ...draft, day: event.target.value })}
        />
        {admin ? (
          <label>
            Agent
            <select
              value={draft.actor}
              onChange={(event) =>
                setDraft({ ...draft, actor: event.target.value })
              }
            >
              <option value="">Tous les agents</option>
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.display_name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="call-recording-filter">
          <input
            type="checkbox"
            checked={draft.recordings}
            onChange={(event) =>
              setDraft({ ...draft, recordings: event.target.checked })
            }
          />
          Avec enregistrement
        </label>
        <div className="call-history-filter-actions">
          <button
            type="submit"
            className="button primary small"
            aria-label="Rechercher les appels"
            disabled={busy}
          >
            Rechercher
          </button>
          <button
            type="button"
            className="text-button"
            disabled={busy}
            onClick={() => {
              setDraft(emptyFilters);
              applyFilters({ ...emptyFilters });
            }}
          >
            Réinitialiser
          </button>
        </div>
      </form>
      {filters.destination ? (
        <p className="call-filter-summary">
          Appels du numéro {filters.destination}
        </p>
      ) : null}
      {error ? <Notice error>{error}</Notice> : null}
      {busy ? (
        <p role="status" className="call-filter-summary">
          Chargement des appels…
        </p>
      ) : null}
      {!busy && !error && !calls.length ? (
        <div className="call-inbox-empty">
          <Icon name="headset" />
          <h3>Aucun appel à afficher</h3>
          <p>Les appels et leurs enregistrements apparaîtront ici.</p>
        </div>
      ) : null}
      {calls.length ? (
        <div className="call-inbox-layout">
          <div
            className="call-inbox-list"
            aria-label="Liste des appels"
            aria-busy={busy}
          >
            {calls.map((item) => (
              <button
                type="button"
                key={item.id}
                className={
                  item.id === selected
                    ? "call-inbox-row selected"
                    : "call-inbox-row"
                }
                aria-pressed={item.id === selected}
                disabled={busy}
                onClick={() => setSelected(item.id)}
              >
                <span className="call-row-avatar">
                  <Icon name="headset" />
                </span>
                <span className="call-row-copy">
                  <strong>{item.contact_name || item.destination}</strong>
                  <span>
                    {item.contact_name ? item.destination + " · " : ""}
                    {item.actor_name}
                  </span>
                  <small>{date(item.created_at)}</small>
                  <span className="call-row-outcome">
                    {(item.outcome
                      ? outcomes[item.outcome]
                      : states[item.state]) || "Mise à jour en cours"}
                    {item.recordings.length ? " · Enregistrement" : ""}
                  </span>
                </span>
              </button>
            ))}
          </div>
          <div className="call-conversation" aria-live="polite">
            {call ? (
              <>
                <header className="call-conversation-header">
                  <span className="avatar avatar-purple">
                    <Icon name="users" />
                  </span>
                  <div>
                    <h3>{call.contact_name || call.destination}</h3>
                    <p>{call.destination}</p>
                  </div>
                  <span className="badge badge-purple">
                    {(call.outcome
                      ? outcomes[call.outcome]
                      : states[call.state]) || "Appel"}
                  </span>
                </header>
                <dl className="call-details">
                  <div>
                    <dt>Agent</dt>
                    <dd>{call.actor_name}</dd>
                  </div>
                  <div>
                    <dt>Campagne</dt>
                    <dd>{call.campaign_name || "Appel manuel"}</dd>
                  </div>
                  <div>
                    <dt>Numéro émetteur</dt>
                    <dd>{call.caller_number || "—"}</dd>
                  </div>
                  <div>
                    <dt>Date de l’appel</dt>
                    <dd>{date(call.created_at)}</dd>
                  </div>
                </dl>
                <div className="audio-actions">
                  <button
                    type="button"
                    className="text-button"
                    disabled={busy}
                    onClick={() => {
                      const next = {
                        ...emptyFilters,
                        destination: call.destination,
                      };
                      setDraft(next);
                      applyFilters(next);
                    }}
                  >
                    Historique de ce numéro
                  </button>
                  {call.campaign_id && call.contact_id ? (
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => setContactOpen(true)}
                    >
                      Ouvrir la fiche du contact
                    </button>
                  ) : null}
                </div>
                <article className="call-timeline-entry">
                  <div className="call-timeline-icon">
                    <Icon name="headset" />
                  </div>
                  <div>
                    <h4>Appel sortant</h4>
                    <p>
                      {date(call.created_at)} · {call.actor_name}
                    </p>
                    <p>
                      {call.outcome
                        ? outcomes[call.outcome]
                        : states[call.state]}
                    </p>
                    {call.recordings.length ? (
                      call.recordings.map((recording) => (
                        <RecordingPlayer
                          key={call.id + recording.sid}
                          recording={recording}
                          disabled={disabled}
                        />
                      ))
                    ) : (
                      <p className="call-recording-empty">
                        Aucun enregistrement disponible pour cet appel.
                      </p>
                    )}
                  </div>
                </article>
              </>
            ) : null}
          </div>
        </div>
      ) : null}
      <nav
        className="call-history-pagination"
        aria-label="Pages de l’historique"
      >
        <button
          type="button"
          className="button secondary"
          disabled={busy || pages.length <= 1}
          onClick={() => void load(pages.slice(0, -1))}
        >
          Appels plus récents
        </button>
        <span>
          Page {pages.length} · {calls.length} appel
          {calls.length > 1 ? "s" : ""}
        </span>
        <button
          type="button"
          className="button secondary"
          disabled={busy || !cursor}
          onClick={() => cursor && void load([...pages, cursor])}
        >
          Charger les appels précédents
        </button>
      </nav>
      {contactOpen && call?.campaign_id && call.contact_id ? (
        <CallContactDialog
          campaignId={call.campaign_id}
          contactId={call.contact_id}
          admin={admin}
          onClose={() => setContactOpen(false)}
        />
      ) : null}
    </section>
  );
}
