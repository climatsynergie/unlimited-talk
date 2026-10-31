// A browser media event never proves that the provider has released a call.
// Only the server's durable state permits another explicit attempt.
export type Intent = {
  id: string;
  state: string;
  outcome: string | null;
  owned_session?: boolean;
};
export type Session = {
  enabled: boolean;
  destination: string | null;
  max_duration_seconds: number;
  active: Intent | null;
};
export type MediaCall = {
  on: (event: string, listener: () => void) => void;
  disconnect: () => void;
};
export type MediaDevice = {
  connect: (id: string, input: string) => Promise<MediaCall>;
  destroy: () => void;
  onError: (listener: () => void) => void;
};
export type Transport = {
  session: () => Promise<Session>;
  reserve: (id: string) => Promise<{ intent: Intent; token: string }>;
  cancel: (id: string) => Promise<Intent>;
  history: (id: string) => Promise<{ intent: Intent }>;
};
export type PhoneState = {
  loaded: boolean;
  enabled: boolean;
  destination: string | null;
  phase:
    | "idle"
    | "preparing"
    | "connecting"
    | "ringing"
    | "connected"
    | "reconnecting"
    | "ending"
    | "checking";
  intent: Intent | null;
  local: boolean;
  error: string;
  result: string;
};
const terminal = (row: Intent) =>
  ["finished", "cancelled", "expired"].includes(row.state);

export class PhoneController {
  private transport: Transport;
  private factory: (token: string) => Promise<MediaDevice>;
  private listeners = new Set<() => void>();
  private device: MediaDevice | null = null;
  private call: MediaCall | null = null;
  private generation = 0;
  private closed = false;
  private refreshing = false;
  private identifier: string | null = null;
  private watchdog: ReturnType<typeof setTimeout> | null = null;
  private pending: number | null = null;
  private mediaAttempted = false;
  state: PhoneState = {
    loaded: false,
    enabled: false,
    destination: null,
    phase: "idle",
    intent: null,
    local: false,
    error: "",
    result: "",
  };

  constructor(
    transport: Transport,
    factory: (token: string) => Promise<MediaDevice>,
  ) {
    this.transport = transport;
    this.factory = factory;
  }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  snapshot = () => this.state;
  private update(patch: Partial<PhoneState>) {
    if (this.closed) return;
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }
  private release() {
    if (this.watchdog !== null) clearTimeout(this.watchdog);
    this.watchdog = null;
    const call = this.call,
      device = this.device;
    this.call = null;
    this.device = null;
    try {
      call?.disconnect();
    } catch {
      /* Server reconciliation remains authoritative. */
    }
    try {
      device?.destroy();
    } catch {
      /* Do not expose provider exceptions or tokens. */
    }
  }
  private settle(row: Intent) {
    if (!terminal(row)) return false;
    ++this.generation;
    this.identifier = null;
    this.pending = null;
    this.release();
    this.update({
      phase: "idle",
      intent: null,
      local: false,
      error: "",
      result: row.outcome || row.state,
    });
    return true;
  }
  async refresh() {
    if (this.closed || this.refreshing) return;
    this.refreshing = true;
    const generation = this.generation;
    let observedSession: Session | null = null;
    try {
      const session = await this.transport.session();
      if (this.closed || generation !== this.generation) return;
      observedSession = session;
      this.update({
        loaded: true,
        enabled: session.enabled,
        destination: session.destination,
      });
      if (this.pending !== null && !this.state.intent) return;
      if (this.identifier) {
        const { intent } = await this.transport.history(this.identifier);
        if (this.closed || generation !== this.generation) return;
        if (!this.settle(intent)) {
          const owned = this.state.intent?.owned_session;
          this.update({ intent: { ...intent, owned_session: owned } });
          if (
            this.call &&
            this.state.local &&
            !["ending", "checking", "reconnecting"].includes(this.state.phase)
          ) {
            if (intent.state === "answered")
              this.update({ phase: "connected" });
            else if (
              intent.state === "ringing" &&
              this.state.phase !== "connected"
            )
              this.update({ phase: "ringing" });
          }
        }
      } else if (session.active) {
        this.identifier = session.active.id;
        this.update({
          intent: session.active,
          phase: "checking",
          local: false,
        });
      } else if (this.state.phase === "checking") {
        this.update({ phase: "idle", intent: null, error: "" });
      }
    } catch (error) {
      if (
        !this.closed &&
        generation === this.generation &&
        !this.mediaAttempted &&
        typeof error === "object" &&
        error !== null &&
        "status" in error &&
        error.status === 404
      ) {
        const active = observedSession?.active ?? null;
        this.identifier = active?.id ?? null;
        this.update({
          phase: active ? "checking" : "idle",
          intent: active,
          local: false,
        });
      } else if (!this.closed && generation === this.generation)
        this.update({
          loaded: true,
          error:
            "L’état de l’appel ne peut pas être confirmé. Vérifiez votre connexion, puis actualisez.",
        });
    } finally {
      this.refreshing = false;
    }
  }
  async start(input = "") {
    if (
      this.closed ||
      !this.state.loaded ||
      !this.state.enabled ||
      this.state.phase !== "idle" ||
      this.pending
    )
      return;
    const generation = ++this.generation;
    const id = crypto.randomUUID();
    this.identifier = id;
    this.mediaAttempted = false;
    this.pending = generation;
    this.watchdog = setTimeout(() => this.hangup(), 45_000);
    this.update({
      phase: "preparing",
      local: true,
      error: "",
      result: "",
      intent: null,
    });
    let attemptedConnect = false;
    try {
      const reserved = await this.transport.reserve(id);
      if (this.closed || generation !== this.generation) return;
      this.update({ intent: { ...reserved.intent, owned_session: true } });
      const device = await this.factory(reserved.token);
      // The token stays only in this stack and the SDK, never in React/storage.
      if (this.closed || generation !== this.generation) {
        device.destroy();
        return;
      }
      this.device = device;
      device.onError(() => {
        if (generation === this.generation) this.interrupted();
      });
      if (this.closed || generation !== this.generation) {
        device.destroy();
        return;
      }
      this.update({ phase: "connecting" });
      attemptedConnect = true;
      this.mediaAttempted = true;
      const call = await device.connect(id, input);
      if (this.closed || generation !== this.generation) {
        call.disconnect();
        device.destroy();
        return;
      }
      this.call = call;
      const when = (phase: PhoneState["phase"]) => () => {
        if (generation === this.generation && this.state.phase !== "ending")
          this.update({ phase });
      };
      call.on("ringing", when("ringing"));
      call.on("accept", when("connected"));
      call.on("reconnecting", when("reconnecting"));
      call.on("reconnected", when("connected"));
      for (const event of ["disconnect", "cancel", "reject", "error"])
        call.on(event, () => {
          if (generation === this.generation) this.interrupted();
        });
      // A second local ceiling complements the provider's immutable 180s cap.
      if (this.watchdog !== null) clearTimeout(this.watchdog);
      this.watchdog = setTimeout(() => this.hangup(), 210_000);
    } catch (error) {
      if (this.closed || generation !== this.generation) return;
      ++this.generation;
      this.release();
      this.update({
        phase: "checking",
        local: false,
        error:
          typeof error === "object" &&
          error !== null &&
          "status" in error &&
          error.status === 403
            ? "Reconnectez-vous pour confirmer votre identité et vos droits avant d’appeler."
            : "L’appel n’a pas pu démarrer. Vérifiez son état avant de recommencer.",
      });
      // Before connect(), cancellation is safe even if a response was lost.
      // A missing/uncertain reservation stays blocked until an explicit refresh.
      if (!attemptedConnect) {
        try {
          const row = await this.transport.cancel(id);
          if (!this.closed && this.identifier === id) {
            const failure = this.state.error;
            if (this.settle(row)) this.update({ error: failure });
          }
        } catch {
          /* No blind redial or invented terminal state. */
        }
      }
    } finally {
      if (this.pending === generation) this.pending = null;
    }
  }
  private interrupted() {
    if (this.closed) return;
    ++this.generation; // Invalidates late connect promises and media events.
    this.release();
    this.update({ phase: "checking", local: false });
    void this.refresh();
  }
  hangup() {
    if (this.closed || this.state.phase === "idle") return;
    const generation = ++this.generation;
    const id = this.identifier;
    const reserved = this.state.intent?.state === "reserved";
    this.release();
    this.update({ phase: "ending", local: false });
    if (id && reserved) {
      // Race atomically with consume: late permission cannot redeem a cancelled
      // reservation; an already consumed call returns 409 and stays occupied.
      void this.transport
        .cancel(id)
        .then((row) => {
          if (generation === this.generation) this.settle(row);
        })
        .catch(() => {
          if (generation === this.generation) void this.refresh();
        });
    }
    // In-flight reserve/connect code will close any late media handle.
    if (!this.pending) void this.refresh();
  }
  async cancelPreparation() {
    const row = this.state.intent;
    if (
      !row ||
      row.state !== "reserved" ||
      row.owned_session === false ||
      this.pending
    )
      return;
    const generation = ++this.generation;
    this.release();
    this.update({ phase: "ending", error: "" });
    try {
      const cancelled = await this.transport.cancel(row.id);
      if (generation === this.generation) this.settle(cancelled);
    } catch {
      this.update({
        phase: "checking",
        error:
          "La fin de la préparation doit être confirmée. Actualisez son état.",
      });
    }
  }
  dispose() {
    this.closed = true;
    ++this.generation;
    this.release();
  }
  activate() {
    if (!this.closed) return;
    this.closed = false;
    this.refreshing = false;
    this.pending = null;
    this.update({ local: false, phase: this.identifier ? "checking" : "idle" });
  }
}
