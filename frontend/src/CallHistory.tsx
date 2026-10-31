import { useCallback, useEffect, useRef, useState } from "react";
import { api, date, message } from "./api";
import { Notice } from "./ui";

type Recording = {
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

function RecordingPlayer({ recording }: { recording: Recording }) {
  const [error, setError] = useState(false);
  const player = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    const audio = player.current;
    return () => {
      audio?.pause();
      audio?.removeAttribute("src");
      audio?.load();
    };
  }, [recording.playback_path]);
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

export function CallHistory() {
  const [calls, setCalls] = useState<Call[]>([]);
  const [cursor, setCursor] = useState<Cursor | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const busyRef = useRef(false);

  const load = useCallback(async (next: Cursor | null = null) => {
    if (next && busyRef.current) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const current = ++sequence.current;
    busyRef.current = true;
    setBusy(true);
    setError("");
    const query = next
      ? "?" +
        new URLSearchParams({
          before_id: next.id,
          before_created_at: next.created_at,
        })
      : "";
    try {
      const result = await api<Result>("/telephony/calls" + query, {
        signal: controller.signal,
      });
      if (controller.signal.aborted || current !== sequence.current) return;
      setCalls((old) =>
        next
          ? [
              ...old,
              ...result.items.filter(
                (item) => !old.some((call) => call.id === item.id),
              ),
            ]
          : result.items,
      );
      setCursor(result.next_cursor);
    } catch (failure) {
      if (!controller.signal.aborted && current === sequence.current)
        setError(message(failure));
    } finally {
      if (!controller.signal.aborted && current === sequence.current) {
        setBusy(false);
        busyRef.current = false;
      }
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      request.current?.abort();
      sequence.current += 1;
    };
  }, [load]);

  return (
    <section
      className="panel audio-panel call-history"
      aria-labelledby="call-history-heading"
    >
      <div className="panel-toolbar">
        <h2 id="call-history-heading">Historique des appels</h2>
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={() => void load()}
        >
          Actualiser les appels
        </button>
      </div>
      {error ? <Notice error>{error}</Notice> : null}
      {busy && calls.length === 0 ? (
        <p role="status">Chargement des appels…</p>
      ) : null}
      {!busy && !error && calls.length === 0 ? (
        <p>Les appels et leurs enregistrements apparaîtront ici.</p>
      ) : null}
      <div className="call-history-list">
        {calls.map((call) => (
          <article key={call.id} className="call-history-item">
            <h3>{call.destination}</h3>
            <p>
              {date(call.created_at)} · {call.actor_name}
            </p>
            <p>
              {(call.outcome ? outcomes[call.outcome] : states[call.state]) ||
                "État en cours de mise à jour"}
            </p>
            {call.recordings.map((recording) => (
              <RecordingPlayer key={recording.sid} recording={recording} />
            ))}
          </article>
        ))}
      </div>
      {cursor ? (
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={() => void load(cursor)}
        >
          Charger les appels précédents
        </button>
      ) : null}
    </section>
  );
}
