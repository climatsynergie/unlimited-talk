import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, date, message } from "./api";
import { Notice, Submit, Field, Modal } from "./ui";

type Contact = {
  id: string;
  phone: string;
  profile: Record<string, string>;
  do_not_contact: boolean;
  non_interested: boolean;
};
type Job = {
  id: string;
  filename: string;
  status: string;
  headers: string[];
  mapping: Record<string, string>;
  summary: Record<string, number>;
  total: number;
  processed: number;
  created: number;
  enriched: number;
  unchanged: number;
  invalid: number;
  created_at: string;
};
type Row = {
  row_number: number;
  profile: Record<string, string>;
  error: string | null;
  warnings: string[];
  duplicate_in_file: boolean;
  outcome: string | null;
};
const labels: Record<string, string> = {
  phone: "Téléphone",
  first_name: "Prénom",
  last_name: "Nom",
  display_name: "Nom complet",
  email: "Courriel",
  address: "Adresse",
  city: "Ville",
  province: "Province",
  postal_code: "Code postal",
};
const statuses: Record<string, string> = {
  upload: "Fichier attendu",
  mapping: "Colonnes à associer",
  preview: "Aperçu à confirmer",
  queued: "En attente",
  running: "En cours",
  completed: "Terminé",
  discarded: "Annulé",
};

export function Contacts() {
  const [items, setItems] = useState<Contact[]>([]);
  const [historyContact, setHistoryContact] = useState<Contact | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    setError("");
    api<{ items: Contact[]; has_more: boolean }>(
      `/contacts?search=${encodeURIComponent(search)}&offset=${offset}`,
      { signal: abort.signal },
    )
      .then((r) => {
        setItems(r.items);
        setMore(r.has_more);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [search, offset]);
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Contacts</h1>
          <p>Votre répertoire partagé et les coordonnées importées.</p>
        </div>
      </div>
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          setSearch(query);
        }}
      >
        <label>
          Rechercher un contact
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            maxLength={100}
          />
        </label>
        <button className="button primary">Rechercher</button>
      </form>
      {error ? <Notice error>{error}</Notice> : null}
      {loading ? (
        <p role="status">Chargement des contacts…</p>
      ) : (
        <section className="panel table-wrap">
          <table>
            <thead>
              <tr>
                <th>Nom</th>
                <th>Téléphone</th>
                <th>Courriel</th>
                <th>Ville</th>
                <th>Statut</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td>
                    {c.profile.display_name ||
                      [c.profile.first_name, c.profile.last_name]
                        .filter(Boolean)
                        .join(" ") ||
                      "Sans nom"}
                    <button
                      className="text-button"
                      onClick={() => setHistoryContact(c)}
                      aria-label={`Historique de ${c.phone}`}
                    >
                      Historique
                    </button>
                  </td>
                  <td>{c.phone}</td>
                  <td>{c.profile.email || "—"}</td>
                  <td>{c.profile.city || "—"}</td>
                  <td>
                    {c.do_not_contact
                      ? "Ne pas contacter"
                      : c.non_interested
                        ? "Non intéressé"
                        : "Contact"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.length === 0 ? (
            <p>Aucun contact trouvé. Ajoutez un fichier depuis Imports CSV.</p>
          ) : null}
        </section>
      )}
      {historyContact ? (
        <ContactHistory
          contact={historyContact}
          onClose={() => setHistoryContact(null)}
        />
      ) : null}
      <div className="actions">
        <button
          className="button secondary"
          disabled={!offset || loading}
          onClick={() => setOffset((n) => Math.max(0, n - 50))}
        >
          Précédent
        </button>
        <button
          className="button secondary"
          disabled={!more || loading}
          onClick={() => setOffset((n) => n + 50)}
        >
          Suivant
        </button>
      </div>
    </>
  );
}

export function Imports() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [rows, setRows] = useState<Row[]>([]);
  const [after, setAfter] = useState(0);
  const [moreRows, setMoreRows] = useState(false);
  const [issues, setIssues] = useState(false);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const [list, current] = await Promise.all([
          api<{ items: Job[]; has_more: boolean }>(
            `/imports?offset=${offset}`,
            { signal: abort.signal },
          ),
          selected
            ? api<Job>(`/imports/${selected}`, { signal: abort.signal })
            : Promise.resolve(null),
        ]);
        setJobs(list.items);
        setMore(list.has_more);
        setJob(current);
        setError("");
        if (current && ["queued", "running"].includes(current.status))
          timer = setTimeout(refresh, 3000);
      } catch (e) {
        if (!abort.signal.aborted) setError(message(e));
      } finally {
        if (!abort.signal.aborted) setLoading(false);
      }
    }
    setLoading(true);
    void refresh();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, [selected, revision, offset]);
  useEffect(() => {
    if (job && ["mapping", "preview"].includes(job.status))
      setMapping(job.mapping);
  }, [job?.id, job?.status]);
  useEffect(() => {
    if (!job || ["upload", "mapping"].includes(job.status)) {
      setRows([]);
      return;
    }
    const abort = new AbortController();
    api<{ items: Row[]; has_more: boolean }>(
      `/imports/${job.id}/rows?after=${after}&issues=${issues}`,
      { signal: abort.signal },
    )
      .then((r) => {
        setRows(r.items);
        setMoreRows(r.has_more);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(message(e));
      });
    return () => abort.abort();
  }, [job?.id, job?.status, after, issues, revision]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const file = data.get("file");
    if (!(file instanceof File) || !file.size) {
      setError("Choisissez un fichier CSV.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError("Le fichier dépasse la limite de 10 Mio.");
      return;
    }
    setBusy(true);
    setError("");
    const identifier = crypto.randomUUID();
    try {
      await api<Job>("/imports", {
        method: "POST",
        body: {
          id: identifier,
          filename: file.name,
          encoding: data.get("encoding"),
          delimiter: data.get("delimiter") || null,
        },
      });
      const result = await api<Job>(`/imports/${identifier}/source`, {
        method: "PUT",
        raw: file,
      });
      setSelected(result.id);
      setJob(result);
      setMapping(result.mapping);
      setAfter(0);
      setRevision((n) => n + 1);
      form.reset();
    } catch (e) {
      setError(message(e));
      setRevision((n) => n + 1);
    } finally {
      setBusy(false);
    }
  }
  async function act(action: "preview" | "confirm") {
    if (!job || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Job>(`/imports/${job.id}/${action}`, {
        method: "POST",
        body: action === "preview" ? { mapping } : {},
      });
      setJob(result);
      setAfter(0);
      setRevision((n) => n + 1);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Imports CSV</h1>
          <p>
            Déposez un fichier, vérifiez les colonnes et confirmez l’import.
          </p>
        </div>
      </div>
      {error ? <Notice error>{error}</Notice> : null}
      <section className="panel import-panel">
        <h2>Ajouter un fichier</h2>
        <p>
          10 Mio maximum · 100 000 lignes · Téléphone obligatoire. Les cellules
          vides ne suppriment aucune coordonnée existante.
        </p>
        <form className="form-grid" onSubmit={create}>
          <Field
            label="Fichier CSV"
            type="file"
            name="file"
            accept=".csv,text/csv"
            required
            disabled={busy}
          />
          <label>
            Encodage
            <select name="encoding" disabled={busy}>
              <option value="utf-8-sig">UTF-8</option>
              <option value="cp1252">Windows-1252</option>
            </select>
          </label>
          <label>
            Séparateur
            <select name="delimiter" disabled={busy}>
              <option value="">Détection automatique</option>
              <option value=",">Virgule</option>
              <option value=";">Point-virgule</option>
              <option value={"\t"}>Tabulation</option>
            </select>
          </label>
          <Submit busy={busy}>Déposer le fichier</Submit>
        </form>
      </section>
      <section className="panel import-panel">
        <h2>Historique des imports</h2>
        {loading && !jobs.length ? <p role="status">Chargement…</p> : null}
        {jobs.length === 0 && !loading ? (
          <p>Aucun import pour le moment.</p>
        ) : null}
        <ul className="import-list">
          {jobs.map((j) => (
            <li key={j.id}>
              <button
                disabled={busy}
                className="text-button"
                aria-pressed={selected === j.id}
                onClick={() => {
                  setSelected(j.id);
                  setAfter(0);
                  setIssues(false);
                }}
              >
                {j.filename}
              </button>
              <span>
                {statuses[j.status]} · {date(j.created_at)}
              </span>
            </li>
          ))}
        </ul>
        <div className="actions">
          <button
            className="button secondary"
            disabled={!offset || busy}
            onClick={() => setOffset((n) => Math.max(0, n - 20))}
          >
            Précédent
          </button>
          <button
            className="button secondary"
            disabled={!more || busy}
            onClick={() => setOffset((n) => n + 20)}
          >
            Suivant
          </button>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => setRevision((n) => n + 1)}
          >
            Actualiser
          </button>
        </div>
      </section>
      {job ? (
        <section className="panel import-panel">
          <h2>{job.filename}</h2>
          <p role="status">{statuses[job.status]}</p>
          {job.status === "upload" ? (
            <p>
              Le dépôt n’a pas abouti. Ajoutez à nouveau le fichier depuis le
              formulaire ci-dessus.
            </p>
          ) : null}
          {["mapping", "preview"].includes(job.status) ? (
            <>
              <fieldset disabled={busy}>
                <legend>Associer les colonnes</legend>
                <div className="mapping-grid">
                  {Object.entries(labels).map(([key, label]) => (
                    <label key={key}>
                      {label}
                      {key === "phone" ? " (obligatoire)" : ""}
                      <select
                        value={mapping[key] || ""}
                        onChange={(e) => {
                          const next = { ...mapping };
                          if (e.target.value) next[key] = e.target.value;
                          else delete next[key];
                          setMapping(next);
                        }}
                      >
                        <option value="">Ignorer</option>
                        {job.headers.map((h) => (
                          <option key={h} value={h}>
                            {h}
                          </option>
                        ))}
                      </select>
                    </label>
                  ))}
                </div>
              </fieldset>
              <button
                className="button secondary"
                disabled={busy || !mapping.phone}
                onClick={() => act("preview")}
              >
                {busy ? "Validation…" : "Valider et afficher l’aperçu"}
              </button>
            </>
          ) : null}
          {job.status === "preview" ? (
            <>
              <p>
                {job.summary.valid_count} lignes valides ·{" "}
                {job.summary.invalid_count} invalides ·{" "}
                {job.summary.distinct_count} téléphones distincts ·{" "}
                {job.summary.duplicate_count} doublons dans le fichier.
              </p>
              <Notice>
                Aucun contact n’a encore été modifié. Les lignes invalides
                seront ignorées. Les doublons enrichiront le même contact sans
                modifier ses restrictions d’appel.
              </Notice>
              <button
                className="button primary"
                disabled={
                  busy ||
                  !job.summary.valid_count ||
                  Object.keys({ ...mapping, ...job.mapping }).some(
                    (key) => mapping[key] !== job.mapping[key],
                  )
                }
                onClick={() => act("confirm")}
              >
                Confirmer l’import de ces lignes
              </button>
            </>
          ) : null}
          {["queued", "running", "completed"].includes(job.status) ? (
            <>
              <progress
                max={job.total || 1}
                value={job.processed}
                aria-label="Progression de l’import"
              />
              <p>
                {job.processed} / {job.total} lignes traitées
              </p>
              <p>
                {job.created} contacts créés · {job.enriched} enrichis ·{" "}
                {job.unchanged} inchangés · {job.invalid} lignes invalides
              </p>
              <p>
                Vous pouvez quitter cette page : le traitement continue sur le
                serveur.
              </p>
            </>
          ) : null}
          {!["upload", "mapping"].includes(job.status) ? (
            <>
              <label>
                <input
                  type="checkbox"
                  checked={issues}
                  onChange={(e) => {
                    setIssues(e.target.checked);
                    setAfter(0);
                  }}
                />{" "}
                Afficher uniquement les erreurs et avertissements
              </label>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Ligne</th>
                      <th>Téléphone</th>
                      <th>Nom</th>
                      <th>Résultat</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.row_number}>
                        <td>{r.row_number}</td>
                        <td>{r.profile.phone || "—"}</td>
                        <td>{r.profile.display_name || "—"}</td>
                        <td>
                          {r.error ||
                            r.warnings.join(" ") ||
                            (r.duplicate_in_file
                              ? "Doublon dans le fichier"
                              : "Valide")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="actions">
                <button
                  className="button secondary"
                  disabled={!after}
                  onClick={() => setAfter(0)}
                >
                  Premières lignes
                </button>
                <button
                  className="button secondary"
                  disabled={!moreRows}
                  onClick={() => setAfter(rows.at(-1)?.row_number || 0)}
                >
                  Lignes suivantes
                </button>
              </div>
            </>
          ) : null}
        </section>
      ) : null}
    </>
  );
}

type HistoryEvent = {
  id: number;
  action: string;
  actor_name: string;
  created_at: string;
  previous_profile: Record<string, string>;
  incoming_profile: Record<string, string>;
};
function ContactHistory({
  contact,
  onClose,
}: {
  contact: Contact;
  onClose: () => void;
}) {
  const [items, setItems] = useState<HistoryEvent[]>([]);
  const [before, setBefore] = useState<string>("9223372036854775807");
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    api<{ items: HistoryEvent[]; has_more: boolean }>(
      `/contacts/${contact.id}/history?before=${before}`,
      { signal: abort.signal },
    )
      .then((r) => {
        setItems(r.items);
        setMore(r.has_more);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [contact.id, before]);
  return (
    <Modal title={`Historique — ${contact.phone}`} onClose={onClose}>
      {error ? <Notice error>{error}</Notice> : null}
      {loading ? (
        <p role="status">Chargement…</p>
      ) : (
        <ul className="import-list">
          {items.map((item) => (
            <li key={item.id}>
              <div>
                <strong>
                  {{
                    created: "Contact créé",
                    enriched: "Coordonnées enrichies",
                    unchanged: "Contact inchangé",
                  }[item.action] || "Import CSV"}
                </strong>
                <p>
                  {date(item.created_at)} · {item.actor_name}
                </p>
                {Object.entries(item.incoming_profile).map(([key, value]) => (
                  <p key={key}>
                    {labels[key] || key} : {value}
                    {item.previous_profile[key] &&
                    item.previous_profile[key] !== value
                      ? ` (avant : ${item.previous_profile[key]})`
                      : ""}
                  </p>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
      <button
        className="button secondary"
        disabled={loading || !more}
        onClick={() => setBefore(String(items.at(-1)?.id))}
      >
        Événements précédents
      </button>
    </Modal>
  );
}
