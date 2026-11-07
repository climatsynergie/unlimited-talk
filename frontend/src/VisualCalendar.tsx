import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import FullCalendar, { useCalendarController } from "@fullcalendar/react";
import type {
  DatesSetInfo,
  EventDisplayInfo,
  EventInput,
  EventClickInfo,
} from "@fullcalendar/react";
import dayGrid from "@fullcalendar/react/daygrid";
import timeGrid from "@fullcalendar/react/timegrid";
import list from "@fullcalendar/react/list";
import monarch from "@fullcalendar/react/themes/monarch";
import fr from "@fullcalendar/react/locales/fr";
import "@fullcalendar/react/skeleton.css";
import "@fullcalendar/react/themes/monarch/theme.css";
import "@fullcalendar/react/themes/monarch/palettes/purple.css";
import { api, message } from "./api";
import { AppointmentDetail } from "./Calendar";
import type { Appointment, Status } from "./Calendar";
import { day, when, Timezone } from "./Scheduling";
import { Notice } from "./ui";

const plugins = [monarch, dayGrid, timeGrid, list];
const clockFormat = {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
} as const;
const calendarViews = {
  timeGridWeek: {
    titleFormat: { year: "numeric", month: "short", day: "numeric" },
  },
  timeGridDay: {
    titleFormat: {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    },
  },
  listWeek: {
    titleFormat: { year: "numeric", month: "short", day: "numeric" },
  },
} as const;
const viewNames: Record<string, string> = {
  month: "dayGridMonth",
  week: "timeGridWeek",
  day: "timeGridDay",
  agenda: "listWeek",
};
const states: Record<Status, { label: string; color: string; text: string }> = {
  booked: { label: "RDV booké", color: "#ede9fe", text: "#4c1d95" },
  completed: { label: "Terminé", color: "#dcfce7", text: "#14532d" },
  cancelled: { label: "Annulé", color: "#f1f5f9", text: "#475569" },
  no_show: { label: "Absent", color: "#ffe4e6", text: "#9f1239" },
};
function name(a: Appointment) {
  return (
    a.profile.display_name ||
    [a.profile.first_name, a.profile.last_name].filter(Boolean).join(" ") ||
    a.phone
  );
}
function eventClass(info: EventDisplayInfo) {
  return `appointment-card calendar-appointment status-${info.event.extendedProps.status}`;
}
function eventContent(info: EventDisplayInfo) {
  return (
    <div className="calendar-event-content">
      <span className="calendar-event-time">{info.timeText}</span>
      <strong>{info.event.title}</strong>
      <small>{info.event.extendedProps.creator_name}</small>
      <span className="calendar-event-status">
        {states[info.event.extendedProps.status as Status]?.label}
      </span>
    </div>
  );
}

export default function VisualCalendar({ userId }: { userId: string }) {
  const controller = useCalendarController();
  const [view, setView] = useState(() =>
    window.matchMedia("(max-width: 760px)").matches ? "day" : "week",
  );
  const [date, setDate] = useState(() =>
    day(new Date().toISOString(), "America/Toronto"),
  );
  const [zone, setZone] = useState("America/Toronto");
  const [creator, setCreator] = useState("all");
  const [status, setStatus] = useState("upcoming");
  const [range, setRange] = useState<{ start: string; end: string } | null>(
    null,
  );
  const [items, setItems] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [pages, setPages] = useState(10);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [knownAgents, setKnownAgents] = useState<[string, string][]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const firstDate = useRef(date);
  const canvas = useRef<HTMLDivElement>(null);
  const loadedWindow = useRef("");
  useEffect(() => {
    const root = canvas.current;
    if (!root) return;
    // FullCalendar 7.1.3's internalScroller (.fc-ox) can have no focus target
    // in empty/mobile views. Focus an existing cell, preserving the widget's
    // table/row hierarchy across view replacements.
    const accessibleScrollers = () => {
      root.querySelectorAll<HTMLElement>(".fc-ox").forEach((scroller) => {
        const cell =
          scroller.querySelector<HTMLElement>('[role="gridcell"]') ||
          scroller.querySelector<HTMLElement>('[role="cell"]') ||
          scroller.querySelector<HTMLElement>('[role="columnheader"]');
        if (cell) {
          cell.tabIndex = 0;
          cell.dataset.calendarScroll = "";
        }
      });
    };
    accessibleScrollers();
    const observer = new MutationObserver(accessibleScrollers);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);
  const changedDates = useCallback((info: DatesSetInfo) => {
    setDate(day(info.view.currentStart.toISOString(), info.timeZone));
    setRange((previous) =>
      previous?.start === info.startStr && previous.end === info.endStr
        ? previous
        : { start: info.startStr, end: info.endStr },
    );
  }, []);
  useEffect(() => {
    if (!range) return;
    const abort = new AbortController();
    setLoading(true);
    setError("");
    const windowKey = `${range.start}|${range.end}|${creator}|${status}|${pages}`;
    if (loadedWindow.current !== windowKey) {
      setItems([]);
      setMore(false);
    }
    loadedWindow.current = windowKey;
    async function load() {
      const found = new Map<string, Appointment>();
      for (let page = 0; page < pages; page++) {
        const query = new URLSearchParams({
          start: range!.start,
          end: range!.end,
          offset: String(page * 100),
        });
        if (creator === "mine") query.set("creator", userId);
        else if (creator !== "all") query.set("creator", creator);
        if (status === "upcoming") query.set("exclude_cancelled", "true");
        else if (status !== "all") query.set("status", status);
        const result = await api<{ items: Appointment[]; has_more: boolean }>(
          `/calendar?${query}`,
          { signal: abort.signal },
        );
        if (abort.signal.aborted) return;
        result.items.forEach((a) => found.set(a.id, a));
        if (!result.has_more || page === pages - 1) {
          const appointments = [...found.values()];
          setItems(appointments);
          setKnownAgents((previous) => [
            ...new Map([
              ...previous,
              ...appointments.map((a): [string, string] => [
                a.created_by,
                a.creator_name,
              ]),
            ]).entries(),
          ]);
          setMore(result.has_more);
          return;
        }
      }
    }
    load()
      .catch((e) => {
        if (!abort.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [range, creator, status, pages, revision, userId]);
  useEffect(() => {
    function refresh() {
      if (!document.hidden) setRevision((n) => n + 1);
    }
    const timer = window.setInterval(refresh, 30000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);
  const events = useMemo<EventInput[]>(
    () =>
      items
        .filter((a) => status !== "upcoming" || a.status !== "cancelled")
        .map((a) => ({
          id: a.id,
          title: name(a),
          start: a.starts_at,
          end: a.ends_at,
          color: states[a.status].color,
          contrastColor: states[a.status].text,
          extendedProps: {
            status: a.status,
            creator_name: a.creator_name,
            appointment: a,
          },
        })),
    [items, status],
  );
  const agentChoices = useMemo(
    () => [...knownAgents].sort((a, b) => a[1].localeCompare(b[1], "fr")),
    [knownAgents],
  );
  const clickEvent = useCallback(
    (info: EventClickInfo) => setSelected(info.event.id),
    [],
  );
  const describeEvent = useCallback(
    (info: EventDisplayInfo & { el: HTMLElement }) => {
      const appointment = info.event.extendedProps.appointment as Appointment;
      info.el.setAttribute(
        "aria-label",
        `${name(appointment)}, ${when(appointment.starts_at, zone)}, ${appointment.creator_name}, ${states[appointment.status].label}`,
      );
      info.el.setAttribute(
        "title",
        `${name(appointment)} · ${appointment.campaign_name} · ${appointment.creator_name}`,
      );
    },
    [zone],
  );
  function changeView(value: string) {
    setView(value);
    setPages(10);
    controller.changeView(viewNames[value]);
  }
  return (
    <section className="visual-calendar-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">L’AGENDA DE VOTRE ÉQUIPE</span>
          <h1>Calendrier</h1>
          <p>Unlimited Talks · Tous vos rendez-vous, au même endroit.</p>
        </div>
        <button
          className="button secondary"
          onClick={() => setRevision((n) => n + 1)}
        >
          Actualiser
        </button>
      </div>
      <div className="calendar-workspace">
        <aside className="calendar-sidebar" aria-label="Filtres du calendrier">
          <div className="calendar-owner">
            <span aria-hidden="true">UT</span>
            <div>
              <strong>Unlimited Talks</strong>
              <small>Calendrier partagé</small>
            </div>
          </div>
          <label>
            Aller à la date
            <input
              type="date"
              value={date}
              min="2000-01-01"
              max="2100-12-31"
              onChange={(e) => {
                if (e.target.value) {
                  setDate(e.target.value);
                  setPages(10);
                  controller.gotoDate(e.target.value);
                }
              }}
            />
          </label>
          <Timezone
            value={zone}
            onChange={(v) => {
              setZone(v);
              setPages(10);
            }}
          />
          <label>
            Agent
            <select
              value={creator}
              onChange={(e) => {
                setCreator(e.target.value);
                setPages(10);
              }}
            >
              <option value="all">Tous les agents</option>
              <option value="mine">Mes rendez-vous</option>
              {agentChoices
                .filter(([id]) => id !== userId)
                .map(([id, label]) => (
                  <option value={id} key={id}>
                    {label}
                  </option>
                ))}
              {creator !== "all" &&
              creator !== "mine" &&
              !agentChoices.some(([id]) => id === creator) ? (
                <option value={creator}>Agent sélectionné</option>
              ) : null}
            </select>
          </label>
          <label>
            Statut
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPages(10);
              }}
            >
              <option value="upcoming">Tous sauf annulés</option>
              <option value="all">Tous les statuts</option>
              {Object.entries(states).map(([key, value]) => (
                <option key={key} value={key}>
                  {value.label}
                </option>
              ))}
            </select>
          </label>
          <div className="calendar-legend">
            <h2>Repères de couleur</h2>
            {Object.entries(states).map(([key, value]) => (
              <span key={key}>
                <i
                  className={`calendar-dot status-${key}`}
                  aria-hidden="true"
                />
                {value.label}
              </span>
            ))}
          </div>
          <p className="calendar-booking-help">
            Pour créer un rendez-vous, ouvrez la fiche d’un contact dans sa
            campagne.
          </p>
        </aside>
        <div className="calendar-main">
          <div className="calendar-toolbar">
            <div className="calendar-period">
              <div className="calendar-navigation">
                <button
                  type="button"
                  aria-label="Période précédente"
                  onClick={() => {
                    setPages(10);
                    controller.prev();
                  }}
                >
                  ‹
                </button>
                <button
                  type="button"
                  aria-label="Période suivante"
                  onClick={() => {
                    setPages(10);
                    controller.next();
                  }}
                >
                  ›
                </button>
              </div>
              <h2 aria-live="polite">
                {controller.view?.title || "Calendrier de l’équipe"}
              </h2>
            </div>
            <button
              className="button secondary"
              onClick={() => {
                setDate(day(new Date().toISOString(), zone));
                setPages(10);
                controller.today();
              }}
            >
              Aujourd’hui
            </button>
            <div
              className="segmented-control calendar-views"
              aria-label="Affichage du calendrier"
            >
              {[
                ["month", "Mois"],
                ["week", "Semaine"],
                ["day", "Jour"],
                ["agenda", "Agenda"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  aria-pressed={view === value}
                  onClick={() => changeView(value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="calendar-load-status" role="status">
            {loading
              ? "Chargement des rendez-vous…"
              : `${events.length} rendez-vous dans cette période${more ? " · chargement partiel" : ""}`}
          </div>
          {error ? <Notice error>{error}</Notice> : null}
          {more ? (
            <Notice>
              D’autres rendez-vous sont disponibles.{" "}
              <button
                className="text-button"
                disabled={loading}
                onClick={() => setPages((n) => n + 10)}
              >
                Charger les rendez-vous suivants
              </button>
            </Notice>
          ) : null}
          <div
            ref={canvas}
            className={`calendar-canvas view-${view}`}
            aria-label="Grille des rendez-vous"
            aria-busy={loading}
          >
            <FullCalendar
              controller={controller}
              plugins={plugins}
              locale={fr}
              timeZone={zone}
              initialDate={firstDate.current}
              initialView={viewNames[view]}
              firstDay={1}
              headerToolbar={false}
              height={720}
              nowIndicator
              allDaySlot={false}
              slotDuration="00:30:00"
              slotHeaderFormat={clockFormat}
              slotHeaderClass="calendar-slot-label"
              dayHeaderClass="calendar-day-label"
              scrollTime="08:00:00"
              slotMinHeight={28}
              dayMaxEvents={3}
              nextDayThreshold="00:00:00"
              eventMinHeight={38}
              eventMaxStack={3}
              views={calendarViews}
              eventTimeFormat={clockFormat}
              slotEventOverlap={false}
              eventInteractive
              editable={false}
              events={events}
              datesSet={changedDates}
              eventClass={eventClass}
              eventContent={eventContent}
              eventClick={clickEvent}
              eventDidMount={describeEvent}
            />
          </div>
        </div>
      </div>
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
