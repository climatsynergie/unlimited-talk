import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError, date, message } from "./api";
import { CallbackForm } from "./Callbacks";
import { AppointmentForm } from "./Calendar";
import { Field, Modal, Notice, Submit } from "./ui";

type Campaign = {
  id: string;
  name: string;
  description: string;
  timezone: string;
  is_active: boolean;
  version: number;
  contact_count?: number;
};
type Card = {
  contact_id: string;
  stage_id: string;
  phone: string;
  profile: Record<string, string>;
  version: number;
  queue_position: string;
  do_not_contact: boolean;
  non_interested: boolean;
  contact_updated_at: string;
};
type Stage = {
  id: string;
  name: string;
  kind: string;
  color: string;
  position: number;
  total: number;
  items: Card[];
};
type Board = { campaign: Campaign; stages: Stage[] };
type Agent = {
  id: string;
  display_name: string;
  email: string;
  is_active: boolean;
  assigned: boolean;
};
type Note = {
  id: string;
  content: string;
  created_at: string;
  actor_name: string;
};
type Event = {
  id: string;
  action: string;
  details: Record<string, unknown>;
  created_at: string;
  actor_name: string;
};
type Detail = {
  contact: Card;
  notes: Note[];
  events: Event[];
  notes_has_more: boolean;
  events_has_more: boolean;
};
const zones = [
  ["America/Toronto", "Toronto / Montréal"],
  ["America/Vancouver", "Vancouver"],
  ["America/Edmonton", "Edmonton"],
  ["America/Winnipeg", "Winnipeg"],
  ["America/Halifax", "Halifax"],
  ["America/St_Johns", "Terre-Neuve"],
  ["America/Regina", "Regina"],
  ["America/Whitehorse", "Whitehorse"],
];
const colors: Record<string, string> = {
  violet: "Violet",
  blue: "Bleu",
  amber: "Ambre",
  green: "Vert",
  rose: "Rose",
  slate: "Gris",
};
const actions: Record<string, string> = {
  "contact.enrolled": "Ajout à la campagne",
  "card.moved": "Changement d’étape",
  "contact.restricted": "Restriction globale appliquée",
  "contact.restored": "Restrictions révisées",
  "note.added": "Note ajoutée",
  "contact.removed": "Retrait de la campagne",
};
function name(card: Card) {
  return (
    card.profile.display_name ||
    [card.profile.first_name, card.profile.last_name]
      .filter(Boolean)
      .join(" ") ||
    "Sans nom"
  );
}

export function Campaigns({ admin }: { admin: boolean }) {
  const [list, setList] = useState<Campaign[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [archived, setArchived] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [create, setCreate] = useState(false);
  const [settings, setSettings] = useState(false);
  const [enroll, setEnroll] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{
    card: Card;
    stage: Stage;
    request: string;
  } | null>(null);
  const drag = useRef<Card | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    if (!selected) setBoard(null);
    drag.current = null;
    const task = selected
      ? api<Board>(`/campaigns/${selected}/board`, {
          signal: abort.signal,
        }).then(setBoard)
      : api<{ items: Campaign[]; has_more: boolean }>(
          `/campaigns?offset=${offset}&archived=${archived}`,
          { signal: abort.signal },
        ).then((r) => {
          setList(r.items);
          setMore(r.has_more);
        });
    task
      .catch((e) => {
        if (!abort.signal.aborted) {
          setError(message(e));
          if (e instanceof ApiError && [403, 404].includes(e.status))
            setBoard(null);
        }
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [selected, offset, archived, revision]);
  async function applyMove(value: {
    card: Card;
    stage: Stage;
    request: string;
  }) {
    if (!selected || busy) return;
    setBusy(true);
    setError("");
    try {
      await api(
        `/campaigns/${selected}/contacts/${value.card.contact_id}/move`,
        {
          method: "POST",
          body: {
            request_id: value.request,
            stage_id: value.stage.id,
            version: value.card.version,
          },
        },
      );
      setPending(null);
      setDetail(null);
      setRevision((n) => n + 1);
    } catch (e) {
      setError(message(e));
      if (e instanceof ApiError && e.status === 409) {
        setPending(null);
        setDetail(null);
        setRevision((n) => n + 1);
      }
    } finally {
      setBusy(false);
    }
  }
  function move(card: Card, stage: Stage) {
    if (card.stage_id === stage.id || busy) return;
    const value = { card, stage, request: crypto.randomUUID() };
    if (["non_interested", "do_not_contact"].includes(stage.kind))
      setPending(value);
    else void applyMove(value);
  }
  async function moreCards(stage: Stage) {
    if (!selected || busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await api<{ items: Card[] }>(
        `/campaigns/${selected}/cards?stage_id=${stage.id}&after=${stage.items.at(-1)?.queue_position || "0"}`,
      );
      setBoard((old) =>
        old
          ? {
              ...old,
              stages: old.stages.map((s) =>
                s.id === stage.id
                  ? {
                      ...s,
                      items: [
                        ...s.items,
                        ...response.items.filter(
                          (c) =>
                            !s.items.some((p) => p.contact_id === c.contact_id),
                        ),
                      ],
                    }
                  : s,
              ),
            }
          : old,
      );
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
          <h1>
            {board
              ? board.campaign.name
              : admin
                ? "Campagnes"
                : "Mes campagnes"}
          </h1>
          <p>
            {board
              ? board.campaign.description ||
                "Organisez les contacts et suivez leur progression."
              : "Retrouvez les campagnes et leurs pipelines."}
          </p>
        </div>
        <div className="actions">
          {selected ? (
            <button
              className="button secondary"
              onClick={() => {
                setSelected(null);
                setDetail(null);
              }}
            >
              Toutes les campagnes
            </button>
          ) : admin ? (
            <button className="button primary" onClick={() => setCreate(true)}>
              Créer une campagne
            </button>
          ) : null}
          {board && admin && board.campaign.is_active ? (
            <button className="button primary" onClick={() => setEnroll(true)}>
              Ajouter des contacts
            </button>
          ) : null}
          {board && admin ? (
            <button
              className="button secondary"
              onClick={() => setSettings(true)}
            >
              Réglages de la campagne
            </button>
          ) : null}
          <button
            className="button secondary"
            disabled={loading || busy}
            onClick={() => setRevision((n) => n + 1)}
          >
            Actualiser
          </button>
        </div>
      </div>
      {error ? <Notice error>{error}</Notice> : null}
      {!selected && admin ? (
        <label>
          <input
            type="checkbox"
            checked={archived}
            onChange={(e) => {
              setArchived(e.target.checked);
              setOffset(0);
            }}
          />{" "}
          Inclure les campagnes archivées
        </label>
      ) : null}
      {loading ? (
        <p role="status">Chargement des campagnes…</p>
      ) : !selected ? (
        <>
          <section className="campaign-grid">
            {list.map((c) => (
              <button
                key={c.id}
                className="panel campaign-tile"
                onClick={() => {
                  setError("");
                  setSelected(c.id);
                }}
              >
                <strong>{c.name}</strong>
                <span>
                  {c.contact_count} contacts ·{" "}
                  {c.is_active ? "Active" : "Archivée"}
                </span>
                <span>{c.description || c.timezone}</span>
              </button>
            ))}
          </section>
          {!list.length ? (
            <p>
              {admin
                ? "Créez votre première campagne pour organiser vos contacts."
                : "Aucune campagne ne vous est attribuée."}
            </p>
          ) : null}
          <div className="actions">
            <button
              className="button secondary"
              disabled={!offset}
              onClick={() => setOffset((n) => Math.max(0, n - 50))}
            >
              Précédent
            </button>
            <button
              className="button secondary"
              disabled={!more}
              onClick={() => setOffset((n) => n + 50)}
            >
              Suivant
            </button>
          </div>
        </>
      ) : board ? (
        <>
          {!board.campaign.is_active ? (
            <Notice>
              Cette campagne est archivée. Son historique reste consultable.
            </Notice>
          ) : null}
          <div className="pipeline-board" aria-label="Pipeline de la campagne">
            {board.stages.map((stage) => (
              <section
                key={stage.id}
                className={`pipeline-column stage-${stage.color}`}
                aria-label={`Étape ${stage.name}`}
                onDragOver={(e) => {
                  if (board.campaign.is_active && drag.current)
                    e.preventDefault();
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  if (drag.current && board.campaign.is_active)
                    move(drag.current, stage);
                  drag.current = null;
                }}
              >
                <header>
                  <h2>{stage.name}</h2>
                  <span>{stage.total}</span>
                </header>
                <div className="pipeline-cards">
                  {stage.items.map((card) => (
                    <button
                      key={card.contact_id}
                      className="pipeline-card"
                      disabled={busy}
                      draggable={board.campaign.is_active && !busy}
                      onDragStart={(e) => {
                        drag.current = card;
                        e.dataTransfer.setData("text/plain", card.contact_id);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onDragEnd={() => {
                        drag.current = null;
                      }}
                      onClick={() => setDetail(card.contact_id)}
                    >
                      <strong>{name(card)}</strong>
                      <span>{card.phone}</span>
                      {card.profile.city ? (
                        <span>{card.profile.city}</span>
                      ) : null}
                      {card.do_not_contact || card.non_interested ? (
                        <span className="restriction-label">
                          {card.do_not_contact
                            ? "Ne pas contacter"
                            : "Non intéressé"}
                        </span>
                      ) : null}
                    </button>
                  ))}
                  {!stage.total ? (
                    <p className="subtle">Aucun contact</p>
                  ) : null}
                </div>
                {stage.items.length < stage.total ? (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => moreCards(stage)}
                  >
                    Afficher plus de contacts
                  </button>
                ) : null}
              </section>
            ))}
          </div>
        </>
      ) : null}
      {create ? (
        <CampaignForm
          onClose={() => setCreate(false)}
          onSaved={(c) => {
            setCreate(false);
            setSelected(c.id);
            setRevision((n) => n + 1);
          }}
        />
      ) : null}
      {settings && board ? (
        <Settings
          campaign={board.campaign}
          stages={board.stages}
          onClose={() => setSettings(false)}
          onChanged={() => setRevision((n) => n + 1)}
        />
      ) : null}
      {enroll && selected ? (
        <EnrollContacts
          campaignId={selected}
          onClose={() => setEnroll(false)}
          onSaved={() => setRevision((n) => n + 1)}
        />
      ) : null}
      {detail && selected && board ? (
        <CardDetail
          key={detail}
          campaign={board.campaign}
          identifier={detail}
          stages={board.stages}
          admin={admin}
          onClose={() => setDetail(null)}
          onMove={move}
          onChanged={() => {
            setDetail(null);
            setRevision((n) => n + 1);
          }}
        />
      ) : null}
      {pending ? (
        <Modal
          title={
            pending.stage.kind === "do_not_contact"
              ? "Ne plus contacter ce contact ?"
              : "Classer ce contact non intéressé ?"
          }
          onClose={() => setPending(null)}
          busy={busy}
        >
          <p>
            Cette restriction s’applique à toutes les campagnes auxquelles
            appartient ce contact.
          </p>
          <p>{pending.card.phone}</p>
          <div className="actions">
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setPending(null)}
            >
              Annuler
            </button>
            <button
              className="button danger"
              disabled={busy}
              onClick={() => applyMove(pending)}
            >
              Confirmer pour toutes les campagnes
            </button>
          </div>
        </Modal>
      ) : null}
    </>
  );
}

function CampaignForm({
  campaign,
  onClose,
  onSaved,
}: {
  campaign?: Campaign;
  onClose: () => void;
  onSaved: (campaign: Campaign) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    const data = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      const body = {
        name: data.get("name"),
        description: data.get("description"),
        timezone: data.get("timezone"),
        ...(campaign
          ? {
              version: campaign.version,
              is_active: data.get("active") === "on",
            }
          : {}),
      };
      const result = await api<Campaign>(
        campaign ? `/campaigns/${campaign.id}` : "/campaigns",
        { method: campaign ? "PATCH" : "POST", body },
      );
      onSaved(result);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={campaign ? "Modifier la campagne" : "Créer une campagne"}
      onClose={onClose}
      busy={busy}
    >
      {error ? <Notice error>{error}</Notice> : null}
      <form className="campaign-form" onSubmit={submit}>
        <Field
          label="Nom de la campagne"
          name="name"
          disabled={busy}
          required
          maxLength={120}
          defaultValue={campaign?.name}
        />
        <label>
          Description
          <textarea
            disabled={busy}
            name="description"
            maxLength={2000}
            defaultValue={campaign?.description}
          />
        </label>
        <label>
          Fuseau horaire
          <select
            name="timezone"
            disabled={busy}
            defaultValue={campaign?.timezone || "America/Toronto"}
          >
            {zones.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
            {campaign && !zones.some(([zone]) => zone === campaign.timezone) ? (
              <option value={campaign.timezone}>{campaign.timezone}</option>
            ) : null}
          </select>
        </label>
        {campaign ? (
          <label>
            <input
              type="checkbox"
              name="active"
              disabled={busy}
              defaultChecked={campaign.is_active}
            />{" "}
            Campagne active
          </label>
        ) : null}
        <Submit busy={busy}>
          {campaign ? "Enregistrer les réglages" : "Créer la campagne"}
        </Submit>
      </form>
    </Modal>
  );
}

function Settings({
  campaign,
  stages,
  onClose,
  onChanged,
}: {
  campaign: Campaign;
  stages: Stage[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState(false);
  const [editingStage, setEditingStage] = useState<Stage | null | undefined>(
    undefined,
  );
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    api<{ items: Agent[]; has_more: boolean }>(
      `/campaigns/${campaign.id}/agents?offset=${offset}`,
      { signal: abort.signal },
    )
      .then((r) => {
        setAgents(r.items);
        setMore(r.has_more);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(message(e));
      });
    return () => abort.abort();
  }, [campaign.id, offset, revision]);
  async function mutate(path: string, method: string, body?: unknown) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`/campaigns/${campaign.id}${path}`, { method, body });
      setRevision((n) => n + 1);
      onChanged();
      return true;
    } catch (e) {
      setError(message(e));
      return false;
    } finally {
      setBusy(false);
    }
  }
  function reorder(index: number, direction: number) {
    const ids = stages.map((s) => s.id);
    [ids[index], ids[index + direction]] = [ids[index + direction], ids[index]];
    void mutate("/stage-order", "PUT", { stage_ids: ids });
  }
  return (
    <Modal title="Réglages de la campagne" onClose={onClose} busy={busy}>
      {error ? <Notice error>{error}</Notice> : null}
      <p>
        {campaign.name} · {campaign.timezone}
      </p>
      <button
        className="button secondary"
        onClick={() => setEdit(true)}
        disabled={busy}
      >
        Modifier le nom, le fuseau ou l’état
      </button>
      <h3>Agents attribués</h3>
      <div className="campaign-agent-list">
        {agents.map((agent) => (
          <label key={agent.id}>
            <input
              type="checkbox"
              checked={agent.assigned}
              disabled={
                busy ||
                (!agent.is_active && !agent.assigned) ||
                !campaign.is_active
              }
              onChange={async (e) => {
                const checked = e.target.checked;
                setAgents((list) =>
                  list.map((item) =>
                    item.id === agent.id
                      ? { ...item, assigned: checked }
                      : item,
                  ),
                );
                const saved = await mutate(`/agents/${agent.id}`, "PUT", {
                  is_active: checked,
                });
                if (!saved) {
                  setAgents((list) =>
                    list.map((item) =>
                      item.id === agent.id
                        ? { ...item, assigned: agent.assigned }
                        : item,
                    ),
                  );
                  setRevision((n) => n + 1);
                }
              }}
            />
            <span>
              {agent.display_name}
              <small>
                {agent.email}
                {!agent.is_active ? " · Compte désactivé" : ""}
              </small>
            </span>
          </label>
        ))}
      </div>
      {!agents.length ? <p>Aucun compte agent disponible.</p> : null}
      <div className="actions">
        <button
          className="button secondary"
          disabled={busy || !offset}
          onClick={() => setOffset((n) => Math.max(0, n - 50))}
        >
          Agents précédents
        </button>
        <button
          className="button secondary"
          disabled={busy || !more}
          onClick={() => setOffset((n) => n + 50)}
        >
          Agents suivants
        </button>
      </div>
      <h3>Étapes du pipeline</h3>
      <ol className="stage-settings">
        {stages.map((stage, index) => (
          <li key={stage.id}>
            <span>{stage.name}</span>
            <div>
              <button
                className="text-button"
                disabled={busy || !campaign.is_active}
                onClick={() => setEditingStage(stage)}
              >
                Modifier
              </button>
              <button
                className="text-button"
                aria-label={`Monter ${stage.name}`}
                disabled={busy || index === 0 || !campaign.is_active}
                onClick={() => reorder(index, -1)}
              >
                ↑
              </button>
              <button
                className="text-button"
                aria-label={`Descendre ${stage.name}`}
                disabled={
                  busy || index === stages.length - 1 || !campaign.is_active
                }
                onClick={() => reorder(index, 1)}
              >
                ↓
              </button>
              {stage.kind === "custom" ? (
                <button
                  className="text-button"
                  disabled={busy || stage.total > 0 || !campaign.is_active}
                  onClick={() => mutate(`/stages/${stage.id}`, "DELETE")}
                >
                  Archiver
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
      <button
        className="button secondary"
        disabled={busy || !campaign.is_active}
        onClick={() => setEditingStage(null)}
      >
        Ajouter une étape
      </button>
      {edit ? (
        <CampaignForm
          campaign={campaign}
          onClose={() => setEdit(false)}
          onSaved={() => {
            setEdit(false);
            onChanged();
          }}
        />
      ) : null}
      {editingStage !== undefined ? (
        <StageForm
          campaignId={campaign.id}
          stage={editingStage}
          onClose={() => setEditingStage(undefined)}
          onSaved={() => {
            setEditingStage(undefined);
            onChanged();
          }}
        />
      ) : null}
    </Modal>
  );
}

function StageForm({
  campaignId,
  stage,
  onClose,
  onSaved,
}: {
  campaignId: string;
  stage: Stage | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    const data = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api(
        `/campaigns/${campaignId}/stages${stage ? `/${stage.id}` : ""}`,
        {
          method: stage ? "PATCH" : "POST",
          body: { name: data.get("name"), color: data.get("color") },
        },
      );
      onSaved();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={stage ? "Modifier l’étape" : "Ajouter une étape"}
      onClose={onClose}
      busy={busy}
    >
      {error ? <Notice error>{error}</Notice> : null}
      <form className="campaign-form" onSubmit={submit}>
        <Field
          label="Nom de l’étape"
          name="name"
          disabled={busy}
          required
          maxLength={80}
          defaultValue={stage?.name}
        />
        <label>
          Couleur
          <select
            name="color"
            disabled={busy}
            defaultValue={stage?.color || "violet"}
          >
            {Object.entries(colors).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <Submit busy={busy}>Enregistrer l’étape</Submit>
      </form>
    </Modal>
  );
}

export function EnrollContacts({
  campaignId,
  contactIds,
  importId,
  onClose,
  onSaved,
}: {
  campaignId?: string;
  contactIds?: string[];
  importId?: string;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [imports, setImports] = useState<
    { id: string; filename: string; status: string }[]
  >([]);
  const [selected, setSelected] = useState(campaignId || "");
  const [source, setSource] = useState(importId || "");
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<{
    added: number;
    existing: number;
    total: number;
  } | null>(null);
  const requestId = useRef(crypto.randomUUID());
  useEffect(() => {
    const abort = new AbortController();
    const task = campaignId
      ? api<{
          items: { id: string; filename: string; status: string }[];
          has_more: boolean;
        }>(`/imports?offset=${offset}`, { signal: abort.signal }).then((r) => {
          setImports(r.items.filter((i) => i.status === "completed"));
          setMore(r.has_more);
        })
      : api<{ items: Campaign[]; has_more: boolean }>(
          `/campaigns?offset=${offset}`,
          { signal: abort.signal },
        ).then((r) => {
          setCampaigns(r.items);
          setMore(r.has_more);
        });
    task.catch((e) => {
      if (!abort.signal.aborted) setError(message(e));
    });
    return () => abort.abort();
  }, [campaignId, offset]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const r = await api<{ added: number; existing: number; total: number }>(
        `/campaigns/${selected}/contacts`,
        {
          method: "POST",
          body: {
            request_id: requestId.current,
            ...(contactIds
              ? { contact_ids: contactIds }
              : { import_id: source }),
          },
        },
      );
      setResult(r);
      onSaved?.();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="Ajouter des contacts à une campagne"
      onClose={onClose}
      busy={busy}
    >
      {error ? <Notice error>{error}</Notice> : null}
      {result ? (
        <>
          <Notice>
            {result.added} contacts ajoutés · {result.existing} déjà présents.
          </Notice>
          <button className="button primary" onClick={onClose}>
            Terminer
          </button>
        </>
      ) : (
        <form className="campaign-form" onSubmit={submit}>
          {contactIds ? (
            <p>{contactIds.length} contacts sélectionnés.</p>
          ) : null}
          {!campaignId ? (
            <label>
              Campagne
              <select
                value={selected}
                onChange={(e) => {
                  setSelected(e.target.value);
                  requestId.current = crypto.randomUUID();
                }}
                disabled={busy}
              >
                <option value="">Choisir une campagne</option>
                {campaigns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {campaignId && !importId && !contactIds ? (
            <label>
              Import terminé
              <select
                value={source}
                onChange={(e) => {
                  setSource(e.target.value);
                  requestId.current = crypto.randomUUID();
                }}
                disabled={busy}
              >
                <option value="">Choisir un import</option>
                {imports.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.filename}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <div className="actions">
            <button
              type="button"
              className="button secondary"
              disabled={busy || !offset}
              onClick={() =>
                setOffset((n) => Math.max(0, n - (campaignId ? 20 : 50)))
              }
            >
              Liste précédente
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={busy || !more}
              onClick={() => setOffset((n) => n + (campaignId ? 20 : 50))}
            >
              Liste suivante
            </button>
          </div>
          <p>
            Les contacts déjà présents conservent leur étape et leur historique.
          </p>
          <Submit busy={busy} disabled={!selected || (!contactIds && !source)}>
            Ajouter à la campagne
          </Submit>
        </form>
      )}
    </Modal>
  );
}

function CardDetail({
  campaign,
  identifier,
  stages,
  admin,
  onClose,
  onMove,
  onChanged,
}: {
  campaign: Campaign;
  identifier: string;
  stages: Stage[];
  admin: boolean;
  onClose: () => void;
  onMove: (card: Card, stage: Stage) => void;
  onChanged: () => void;
}) {
  const [data, setData] = useState<Detail | null>(null);
  const [booking, setBooking] = useState(false);
  const [callback, setCallback] = useState(false);
  const [target, setTarget] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [restore, setRestore] = useState(false);
  const [remove, setRemove] = useState(false);
  const noteId = useRef(crypto.randomUUID());
  const actionId = useRef(crypto.randomUUID());
  useEffect(() => {
    const abort = new AbortController();
    api<Detail>(`/campaigns/${campaign.id}/contacts/${identifier}`, {
      signal: abort.signal,
    })
      .then((r) => {
        setData(r);
        setTarget(r.contact.stage_id);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(message(e));
      });
    return () => abort.abort();
  }, [campaign.id, identifier, revision]);
  async function addNote(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    const form = e.currentTarget;
    const body = {
      id: noteId.current,
      content: new FormData(form).get("content"),
    };
    setBusy(true);
    setError("");
    try {
      await api(`/campaigns/${campaign.id}/contacts/${identifier}/notes`, {
        method: "POST",
        body,
      });
      noteId.current = crypto.randomUUID();
      form.reset();
      setRevision((n) => n + 1);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function restriction(action: "restore" | "remove") {
    if (!data || busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`/campaigns/${campaign.id}/contacts/${identifier}/${action}`, {
        method: "POST",
        body:
          action === "remove"
            ? { request_id: actionId.current, version: data.contact.version }
            : {
                request_id: actionId.current,
                do_not_contact: false,
                non_interested: false,
                confirmation: "REACTIVER",
                expected_updated_at: data.contact.contact_updated_at,
              },
      });
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function more(kind: "notes" | "events") {
    if (!data || busy) return;
    setBusy(true);
    try {
      const query =
        kind === "notes"
          ? `offset=${data.notes.length}`
          : `before=${data.events.at(-1)?.id}`;
      const r = await api<{ items: Note[] | Event[]; has_more: boolean }>(
        `/campaigns/${campaign.id}/contacts/${identifier}/${kind}?${query}`,
      );
      setData((old) =>
        old
          ? {
              ...old,
              [kind]: [
                ...old[kind],
                ...r.items.filter((i) => !old[kind].some((p) => p.id === i.id)),
              ],
              [`${kind}_has_more`]: r.has_more,
            }
          : old,
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={data ? name(data.contact) : "Fiche contact"}
      onClose={onClose}
      busy={busy || booking || callback}
    >
      {error ? <Notice error>{error}</Notice> : null}
      <button
        className="button secondary"
        disabled={busy}
        onClick={() => {
          actionId.current = crypto.randomUUID();
          setRestore(false);
          setRemove(false);
          setRevision((n) => n + 1);
        }}
      >
        Actualiser la fiche
      </button>
      {!data ? (
        <p role="status">Chargement du contact…</p>
      ) : (
        <>
          <dl className="contact-profile">
            <div>
              <dt>Téléphone</dt>
              <dd>{data.contact.phone}</dd>
            </div>
            {Object.entries(data.contact.profile).map(([key, value]) => (
              <div key={key}>
                <dt>
                  {{
                    display_name: "Nom complet",
                    first_name: "Prénom",
                    last_name: "Nom",
                    email: "Courriel",
                    address: "Adresse",
                    city: "Ville",
                    province: "Province",
                    postal_code: "Code postal",
                  }[key] || key}
                </dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          {data.contact.do_not_contact || data.contact.non_interested ? (
            <Notice>
              {data.contact.do_not_contact
                ? "Ne pas contacter — toutes les campagnes"
                : "Non intéressé — toutes les campagnes"}
            </Notice>
          ) : null}
          {callback ? (
            <section>
              <h3>Programmer un rappel</h3>
              <CallbackForm
                contact={{
                  campaign_id: campaign.id,
                  contact_id: identifier,
                  membership_version: data.contact.version,
                  timezone: campaign.timezone,
                }}
                onCancel={() => setCallback(false)}
                onSaved={() => {
                  setCallback(false);
                  onChanged();
                }}
              />
            </section>
          ) : !booking &&
            campaign.is_active &&
            !data.contact.do_not_contact &&
            !data.contact.non_interested ? (
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setCallback(true)}
            >
              Programmer un rappel
            </button>
          ) : null}
          {booking ? (
            <section>
              <h3>Prendre rendez-vous — Unlimited Talks</h3>
              <AppointmentForm
                contact={{
                  campaign_id: campaign.id,
                  contact_id: identifier,
                  membership_version: data.contact.version,
                  timezone: campaign.timezone,
                }}
                onCancel={() => setBooking(false)}
                onSaved={() => {
                  setBooking(false);
                  setRevision((n) => n + 1);
                  onChanged();
                }}
              />
            </section>
          ) : !callback &&
            campaign.is_active &&
            !data.contact.do_not_contact &&
            !data.contact.non_interested ? (
            <button
              className="button primary"
              disabled={busy}
              onClick={() => setBooking(true)}
            >
              Prendre rendez-vous
            </button>
          ) : null}
          <label className="campaign-stage-picker">
            Étape du pipeline
            <select
              value={target}
              disabled={busy || booking || callback || !campaign.is_active}
              onChange={(e) => setTarget(e.target.value)}
            >
              {stages.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button secondary"
            disabled={
              busy || target === data.contact.stage_id || !campaign.is_active
            }
            onClick={() => {
              const stage = stages.find((s) => s.id === target);
              if (stage) onMove(data.contact, stage);
            }}
          >
            Déplacer vers cette étape
          </button>
          <h3>Notes partagées</h3>
          {!data.notes.length ? (
            <p>Aucune note pour ce contact.</p>
          ) : (
            <ul className="contact-notes">
              {data.notes.map((n) => (
                <li key={n.id}>
                  <p>{n.content}</p>
                  <small>
                    {n.actor_name} · {date(n.created_at)}
                  </small>
                </li>
              ))}
            </ul>
          )}
          {data.notes_has_more ? (
            <button
              className="text-button"
              disabled={busy}
              onClick={() => more("notes")}
            >
              Notes précédentes
            </button>
          ) : null}
          {campaign.is_active ? (
            <form className="campaign-form" onSubmit={addNote}>
              <label>
                Ajouter une note
                <textarea
                  disabled={busy}
                  name="content"
                  required
                  maxLength={5000}
                  onInvalid={(e) =>
                    e.currentTarget.setCustomValidity(
                      "Veuillez écrire une note.",
                    )
                  }
                  onInput={(e) => e.currentTarget.setCustomValidity("")}
                  onChange={() => {
                    noteId.current = crypto.randomUUID();
                  }}
                />
              </label>
              <Submit busy={busy}>Enregistrer la note</Submit>
            </form>
          ) : null}
          <h3>Historique de la campagne</h3>
          <ul className="contact-notes">
            {data.events.map((e) => (
              <li key={e.id}>
                <strong>
                  {actions[e.action] || "Mise à jour de la campagne"}
                </strong>
                {e.details.stage_name ? (
                  <p>
                    {String(e.details.previous_stage_name)} →{" "}
                    {String(e.details.stage_name)}
                  </p>
                ) : null}
                <small>
                  {e.actor_name} · {date(e.created_at)}
                </small>
              </li>
            ))}
          </ul>
          {data.events_has_more ? (
            <button
              className="text-button"
              disabled={busy}
              onClick={() => more("events")}
            >
              Événements précédents
            </button>
          ) : null}
          {admin && campaign.is_active ? (
            <div className="actions">
              {data.contact.do_not_contact || data.contact.non_interested ? (
                <button
                  className="button secondary"
                  onClick={() => setRestore(true)}
                  disabled={busy}
                >
                  Réactiver le contact
                </button>
              ) : null}
              <button
                className="button danger"
                disabled={busy}
                onClick={() => setRemove(true)}
              >
                Retirer de cette campagne
              </button>
            </div>
          ) : null}
          {restore || remove ? (
            <section className="confirmation-panel">
              <h3>
                {remove
                  ? "Retirer ce contact de la campagne ?"
                  : "Lever les restrictions dans toutes les campagnes ?"}
              </h3>
              <p>
                {remove
                  ? "Le contact et son historique restent conservés."
                  : "Après réactivation, choisissez une nouvelle étape dans les campagnes concernées."}
              </p>
              <div className="actions">
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => {
                    setRestore(false);
                    setRemove(false);
                  }}
                >
                  Annuler
                </button>
                <button
                  className="button danger"
                  disabled={busy}
                  onClick={() => restriction(remove ? "remove" : "restore")}
                >
                  {remove
                    ? "Confirmer le retrait"
                    : "Confirmer la réactivation globale"}
                </button>
              </div>
            </section>
          ) : null}
        </>
      )}
    </Modal>
  );
}
