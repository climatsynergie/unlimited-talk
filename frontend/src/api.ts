export type Role = "admin" | "agent";
export type User = {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  is_active: boolean;
};
export type Identity = {
  user: User;
  mfa_enrollment_required: boolean;
  recovery_codes?: string[];
};
export type Invitation = {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  created_at: string;
  expires_at: string;
  used_at: string | null;
  revoked_at: string | null;
};
export type AuditEvent = {
  id: string;
  actor_id: string | null;
  action: string;
  subject_id: string | null;
  actor_email: string | null;
  subject_label: string | null;
  created_at: string;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
    authenticated?: boolean;
  } = {},
): Promise<T> {
  const csrf = document.cookie
    .split("; ")
    .find((value) => value.startsWith("__Host-ut_csrf="))
    ?.split("=")[1];
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (csrf && options.method && options.method !== "GET")
    headers["X-CSRF-Token"] = csrf;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: options.method ?? "GET",
      headers,
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      0,
      "Connexion interrompue. Vérifiez votre réseau, puis réessayez.",
    );
  }
  const payload = await response.json().catch(() => null);
  if (options.signal?.aborted) throw new DOMException("Aborted", "AbortError");
  if (!response.ok) {
    if (response.status === 401 && options.authenticated !== false)
      window.dispatchEvent(new Event("ut-session-expired"));
    const message =
      typeof payload?.detail === "string"
        ? payload.detail
        : response.status === 422
          ? "Vérifiez les champs du formulaire."
          : "Le service est indisponible. Réessayez dans un instant.";
    throw new ApiError(response.status, message);
  }
  if (payload === null)
    throw new ApiError(
      503,
      "Le service ne répond pas correctement. Réessayez dans un instant.",
    );
  return payload as T;
}

export function message(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Une erreur est survenue. Réessayez.";
}
export function date(value: string): string {
  return new Intl.DateTimeFormat("fr-CA", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value.replace(" ", "T")));
}
export function privateLink(
  kind: "invitation" | "reinitialisation",
  token: string,
): string {
  return `${window.location.origin}/${kind}#token=${encodeURIComponent(token)}`;
}
