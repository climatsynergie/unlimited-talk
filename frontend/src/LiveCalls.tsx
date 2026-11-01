import { useEffect, useState } from "react";
import { api } from "./api";
import { Notice } from "./ui";

type Snapshot = {
  active_count: number;
  answered_count: number;
  items: {
    id: string;
    destination: string;
    actor_name: string;
    state: string;
  }[];
};
const labels: Record<string, string> = {
  reserved: "Préparation",
  authorized: "Connexion",
  ringing: "Sonnerie",
  answered: "En conversation",
};

export function LiveCalls() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    async function load() {
      if (pending || document.visibilityState === "hidden") return;
      pending = true;
      try {
        const result = await api<Snapshot>("/telephony/active-calls", {
          signal: AbortSignal.any([
            controller.signal,
            AbortSignal.timeout(10000),
          ]),
        });
        if (!controller.signal.aborted) {
          setSnapshot(result);
          setError(false);
        }
      } catch {
        if (!controller.signal.aborted) setError(true);
      } finally {
        pending = false;
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    document.addEventListener("visibilitychange", load);
    return () => {
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", load);
    };
  }, []);
  return (
    <section className="panel audio-panel" aria-labelledby="live-calls-heading">
      <h2 id="live-calls-heading">Appels en cours</h2>
      {error ? (
        <Notice error>
          La supervision ne peut pas être actualisée. Dernier état conservé.
        </Notice>
      ) : null}
      {!snapshot ? (
        <p>Chargement de la supervision…</p>
      ) : (
        <>
          <p>
            {snapshot.active_count} appel(s) actif(s) ·{" "}
            {snapshot.answered_count} en conversation
          </p>
          {snapshot.items.length ? (
            <ul className="call-history-list">
              {snapshot.items.map((call) => (
                <li key={call.id} className="call-history-item">
                  <strong>{call.actor_name}</strong>
                  <p>
                    {call.destination} · {labels[call.state] || call.state}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p>Aucun appel en cours.</p>
          )}
        </>
      )}
    </section>
  );
}
