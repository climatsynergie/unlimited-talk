import { useEffect, useRef, useState } from "react";
import { api, message } from "./api";
import { AppointmentForm } from "./Calendar";
import type { BookingContact } from "./Calendar";
import { usePhone } from "./Phone";
import { QualificationFields, upgradeQualification } from "./Qualification";
import type {
  QualificationSchema,
  QualificationValue,
  SavedQualification,
} from "./Qualification";
import { Notice } from "./ui";

type Campaign = {
  id: string;
  name: string;
  timezone: string;
  already_enrolled: boolean;
};
type Context = BookingContact & {
  source_followup_id?: string;
  source_followup_version?: number;
  qualification_schema: QualificationSchema;
  qualification: SavedQualification | null;
  booker_name: string;
};

export function InboundBooking({
  id,
  source = "followups",
  initiallyOpen = false,
  allowed,
  onBusy,
  onBooked,
}: {
  id: string;
  source?: "followups" | "calls";
  initiallyOpen?: boolean;
  allowed: boolean;
  onBusy: (value: boolean) => void;
  onBooked: () => void;
}) {
  const { controller: phone } = usePhone();
  const [expanded, setExpanded] = useState(false);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [campaign, setCampaign] = useState("");
  const [more, setMore] = useState(false);
  const [context, setContext] = useState<Context | null>(null);
  const [value, setValue] = useState<QualificationValue | null>(null);
  const [dirty, setDirty] = useState(false);
  const [booking, setBooking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const lifecycle = useRef(new AbortController());
  const hold = useRef<string | null>(null);
  const preparation = useRef(new Map<string, string>());
  const saveId = useRef(crypto.randomUUID());
  useEffect(() => {
    onBusy(allowed && (busy || dirty || booking));
  }, [allowed, busy, dirty, booking, onBusy]);
  useEffect(() => {
    const controller = new AbortController();
    lifecycle.current = controller;
    return () => {
      controller.abort();
      void phone.endBooking(hold.current);
    };
  }, [phone]);
  useEffect(() => {
    if (initiallyOpen && allowed) void load();
  }, [initiallyOpen, allowed, id, source]);
  async function prepare(campaignId: string) {
    setBusy(true);
    setError("");
    let requestId = preparation.current.get(campaignId);
    if (!requestId) {
      requestId = crypto.randomUUID();
      preparation.current.set(campaignId, requestId);
    }
    try {
      const result = await api<Context>(
        `/inbound/${source}/${id}/booking-context`,
        {
          method: "POST",
          body: { campaign_id: campaignId, request_id: requestId },
          signal: lifecycle.current.signal,
        },
      );
      setContext(result);
      setValue(
        upgradeQualification(
          result.qualification_schema,
          result.qualification?.qualification || {
            schema_version: result.qualification_schema.schema_version,
            answers: {},
          },
        ),
      );
      setDirty(false);
    } catch (e) {
      if (!lifecycle.current.signal.aborted) setError(message(e));
    } finally {
      if (!lifecycle.current.signal.aborted) setBusy(false);
    }
  }
  async function load(offset = 0) {
    setExpanded(true);
    setBusy(true);
    setError("");
    try {
      const result = await api<{ items: Campaign[]; has_more: boolean }>(
        `/inbound/${source}/${id}/booking-options?offset=${offset}`,
        { signal: lifecycle.current.signal },
      );
      setCampaigns((old) =>
        offset ? [...old, ...result.items] : result.items,
      );
      setMore(result.has_more);
      if (offset === 0 && result.items.length === 1 && !result.has_more) {
        setCampaign(result.items[0].id);
        await prepare(result.items[0].id);
      }
    } catch (e) {
      if (!lifecycle.current.signal.aborted) setError(message(e));
    } finally {
      if (!lifecycle.current.signal.aborted) setBusy(false);
    }
  }
  async function save() {
    if (!context || !value || busy) return;
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const result = await api<SavedQualification>(
        `/campaigns/${context.campaign_id}/contacts/${context.contact_id}/qualification`,
        {
          method: "PUT",
          body: {
            request_id: saveId.current,
            expected_revision: context.qualification?.revision || null,
            qualification: value,
          },
          signal: lifecycle.current.signal,
        },
      );
      setContext({ ...context, qualification: result });
      setValue(result.qualification);
      setDirty(false);
      setSaved("Qualification enregistrée.");
    } catch (e) {
      if (!lifecycle.current.signal.aborted) setError(message(e));
    } finally {
      if (!lifecycle.current.signal.aborted) setBusy(false);
    }
  }
  async function begin() {
    if (!context || busy) return;
    setBusy(true);
    setError("");
    try {
      hold.current = await phone.beginBooking(context.campaign_id);
      setBooking(true);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  function end() {
    void phone.endBooking(hold.current);
    hold.current = null;
    setBooking(false);
  }
  if (!allowed) return null;
  return (
    <section
      className="inbound-booking"
      aria-label="Qualification et rendez-vous"
    >
      <h3>Qualification et rendez-vous</h3>
      {!expanded ? (
        <button
          className="button success"
          type="button"
          onClick={() => void load()}
        >
          Qualifier / Prendre rendez-vous
        </button>
      ) : (
        <>
          {error ? <Notice error>{error}</Notice> : null}
          {saved ? <p role="status">{saved}</p> : null}
          {busy ? (
            <p role="status">Chargement ou enregistrement de la fiche…</p>
          ) : null}
          {!context ? (
            <>
              {!busy && !campaigns.length ? (
                <p>
                  Un administrateur doit vous attribuer une campagne active pour
                  enregistrer ce rendez-vous.
                </p>
              ) : null}
              {campaigns.length ? (
                <>
                  <label>
                    Campagne d’origine
                    <select
                      value={campaign}
                      disabled={busy}
                      onChange={(e) => setCampaign(e.target.value)}
                    >
                      <option value="">Choisir une campagne</option>
                      {campaigns.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                          {c.already_enrolled ? " · client déjà présent" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="actions">
                    <button
                      className="button info"
                      type="button"
                      disabled={busy || !campaign}
                      onClick={() => void prepare(campaign)}
                    >
                      Ouvrir la qualification
                    </button>
                    {more ? (
                      <button
                        type="button"
                        className="button secondary"
                        disabled={busy}
                        onClick={() => void load(campaigns.length)}
                      >
                        Voir d’autres campagnes
                      </button>
                    ) : null}
                  </div>
                </>
              ) : null}
            </>
          ) : value ? (
            booking ? (
              <AppointmentForm
                contact={{
                  campaign_id: context.campaign_id,
                  contact_id: context.contact_id,
                  membership_version: context.membership_version,
                  timezone: context.timezone,
                  source_followup_id: context.source_followup_id,
                  source_followup_version: context.source_followup_version,
                }}
                qualificationSchema={context.qualification_schema}
                qualification={value}
                qualificationRevision={context.qualification?.revision || null}
                bookerName={context.booker_name}
                onQualificationChange={(v) => {
                  setValue(v);
                  setDirty(true);
                  saveId.current = crypto.randomUUID();
                }}
                onCancel={end}
                onSaved={() => {
                  end();
                  setDirty(false);
                  setSaved(
                    source === "followups"
                      ? "Rendez-vous enregistré. Le suivi est traité."
                      : "Rendez-vous enregistré.",
                  );
                  onBooked();
                }}
              />
            ) : (
              <>
                <p className="muted">
                  Préparez la fiche pendant l’appel. Les réponses sont
                  facultatives.
                </p>
                <QualificationFields
                  schema={context.qualification_schema}
                  value={value}
                  disabled={busy}
                  onChange={(v) => {
                    setValue(v);
                    setDirty(true);
                    setSaved("");
                    saveId.current = crypto.randomUUID();
                  }}
                />
                <div className="actions">
                  <button
                    type="button"
                    className="button info"
                    disabled={busy || !dirty}
                    onClick={() => void save()}
                  >
                    Enregistrer la qualification
                  </button>
                  <button
                    type="button"
                    className="button success"
                    disabled={busy}
                    onClick={() => void begin()}
                  >
                    Prendre rendez-vous
                  </button>
                  {dirty ? (
                    <button
                      type="button"
                      className="button secondary"
                      disabled={busy}
                      onClick={() => {
                        setValue(
                          context.qualification?.qualification || {
                            schema_version:
                              context.qualification_schema.schema_version,
                            answers: {},
                          },
                        );
                        setDirty(false);
                      }}
                    >
                      Abandonner les modifications
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="button secondary"
                      disabled={busy}
                      onClick={() => void prepare(context.campaign_id)}
                    >
                      Actualiser la qualification
                    </button>
                  )}
                </div>
              </>
            )
          ) : null}
        </>
      )}
    </section>
  );
}
