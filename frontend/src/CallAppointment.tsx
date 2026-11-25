import { useState } from "react";
import { AppointmentDetail } from "./Calendar";
import { when } from "./Scheduling";
import { appointmentPhases, phaseOf } from "./appointment-phases";
import type { Phase, Status } from "./appointment-phases";

export type ClientAppointment = {
  id: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  status: Status;
  phase?: Phase;
  creator_name: string;
  campaign_name: string;
  notes: string;
};

export function CallAppointment({
  appointment,
  onChanged,
}: {
  appointment?: ClientAppointment | null;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  if (!appointment)
    return (
      <p className="call-appointment-empty">
        Aucun rendez-vous enregistré pour ce client.
      </p>
    );
  const phase = appointmentPhases[phaseOf(appointment)];
  const duration = Math.round(
    (Date.parse(appointment.ends_at) - Date.parse(appointment.starts_at)) /
      60000,
  );
  return (
    <aside className="call-appointment" aria-label="Rendez-vous du client">
      <div className="call-appointment-heading">
        <strong>Dernier rendez-vous du client</strong>
        <span
          className="call-appointment-phase"
          style={{ background: phase.color, color: phase.text }}
        >
          {phase.label}
        </span>
      </div>
      <p className="call-appointment-time">
        {when(appointment.starts_at, appointment.timezone)}
        <small className="call-appointment-zone">{appointment.timezone}</small>
      </p>
      <dl>
        <div>
          <dt>Durée</dt>
          <dd>{duration} min</dd>
        </div>
        <div>
          <dt>Booké par</dt>
          <dd>{appointment.creator_name}</dd>
        </div>
        <div>
          <dt>Campagne</dt>
          <dd>{appointment.campaign_name}</dd>
        </div>
      </dl>
      {appointment.notes ? (
        <details>
          <summary>Notes du rendez-vous</summary>
          <p>{appointment.notes}</p>
        </details>
      ) : null}
      <button
        type="button"
        className="button secondary"
        onClick={() => setOpen(true)}
      >
        Voir les informations du RDV
      </button>
      {open ? (
        <AppointmentDetail
          key={appointment.id}
          id={appointment.id}
          onClose={() => setOpen(false)}
          onChanged={onChanged}
        />
      ) : null}
    </aside>
  );
}
