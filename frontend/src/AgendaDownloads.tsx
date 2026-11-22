import { useEffect, useRef, useState } from "react";
import { ApiError, message } from "./api";

export function useAgendaDownload({
  zone,
  creator,
  status,
  period,
  disabled,
}: {
  zone: string;
  creator: string;
  status: string;
  period: string;
  disabled: boolean;
}) {
  const [exporting, setExporting] = useState<string | null>(null);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    setExporting(null);
    setError("");
    return () => request.current?.abort();
  }, [zone, creator, status, period]);

  async function download(day: string) {
    if (exporting || disabled) return;
    const abort = new AbortController();
    request.current = abort;
    setExporting(day);
    setError("");
    const query = new URLSearchParams({ day, timezone: zone });
    if (creator) query.set("creator", creator);
    if (status === "upcoming") query.set("exclude_cancelled", "true");
    else if (status !== "all") query.set("phase", status);
    try {
      const response = await fetch(`/api/calendar/export.txt?${query}`, {
        credentials: "same-origin",
        cache: "no-store",
        signal: abort.signal,
      });
      if (!response.ok) {
        if (response.status === 401)
          window.dispatchEvent(new Event("ut-session-expired"));
        const body = await response.json().catch(() => null);
        throw new ApiError(
          response.status,
          typeof body?.detail === "string"
            ? body.detail
            : "Le fichier n’a pas pu être créé. Réessayez.",
        );
      }
      if (!response.headers.get("Content-Type")?.startsWith("text/plain"))
        throw new Error("Le fichier TXT reçu est invalide.");
      const blob = await response.blob();
      if (abort.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `unlimited-talk-rendez-vous-${day}.txt`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) {
      if (!abort.signal.aborted)
        setError(
          failure instanceof TypeError
            ? "Connexion interrompue. Réessayez le téléchargement."
            : message(failure),
        );
    } finally {
      if (!abort.signal.aborted && request.current === abort)
        setExporting(null);
    }
  }
  return { download, exporting, error };
}

export function AgendaDownloadButton({
  day,
  exporting,
  disabled,
  onDownload,
}: {
  day: string;
  exporting: string | null;
  disabled: boolean;
  onDownload: (day: string) => Promise<void>;
}) {
  const label = new Intl.DateTimeFormat("fr-CA", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  }).format(new Date(day + "T12:00:00Z"));
  return (
    <button
      type="button"
      className="button secondary small agenda-day-download"
      disabled={disabled || !!exporting}
      onClick={(event) => {
        event.stopPropagation();
        void onDownload(day);
      }}
      aria-label={`Télécharger les rendez-vous du ${label} en TXT`}
    >
      {exporting === day ? "Préparation…" : "Télécharger TXT"}
    </button>
  );
}
