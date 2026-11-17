export type Status = "booked" | "completed" | "cancelled" | "no_show";
export const appointmentPhases = {
  booked: {
    label: "RDV booké",
    status: "booked",
    color: "#ede9fe",
    text: "#4c1d95",
  },
  confirmed: {
    label: "Confirmé",
    status: "booked",
    color: "#dcfce7",
    text: "#14532d",
  },
  sold: {
    label: "Vendu",
    status: "completed",
    color: "#dbeafe",
    text: "#1e3a8a",
  },
  cancelled: {
    label: "Annulé",
    status: "cancelled",
    color: "#fee2e2",
    text: "#991b1b",
  },
  invalid: {
    label: "Non Valide",
    status: "cancelled",
    color: "#ffe4e6",
    text: "#9f1239",
  },
  non_compliant: {
    label: "Non Conforme",
    status: "cancelled",
    color: "#fecaca",
    text: "#7f1d1d",
  },
  completed: {
    label: "Terminé",
    status: "completed",
    color: "#e2e8f0",
    text: "#334155",
  },
  no_show: {
    label: "Absent",
    status: "no_show",
    color: "#fef3c7",
    text: "#92400e",
  },
} as const;
export type Phase = keyof typeof appointmentPhases;
export function phaseOf(appointment: { status: Status; phase?: Phase }) {
  return appointment.phase && appointment.phase in appointmentPhases
    ? appointment.phase
    : appointment.status;
}
