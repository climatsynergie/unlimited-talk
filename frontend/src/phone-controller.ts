// A browser media event never proves that the provider has released a call.
// Only the server's durable state permits another explicit attempt.
export type Intent = {
  id: string;
  state: string;
  outcome: string | null;
  owned_session?: boolean;
  destination?: string;
  campaign_id?: string | null;
  contact_id?: string | null;
  callback_id?: string | null;
  caller_number?: string | null;
  automatic?: boolean;
};
export type Session = {
  enabled: boolean;
  destination: string | null;
  max_duration_seconds: number;
  active: Intent | null;
};
export type MediaError = { code?: number };
export type MediaCall = {
  on: (event: string, listener: (error?: MediaError) => void) => void;
  disconnect: () => void;
};
export type MediaDevice = {
  connect: (id: string, input: string) => Promise<MediaCall>;
  destroy: () => void;
  onError: (listener: (error?: MediaError, call?: MediaCall) => void) => void;
};

// SDK 2.18.5 reports some carrier hangups as call errors (also on Device with
// an associated Call). Reconcile these with the server rather than pausing the
// queue. Auth, microphone, signalling and media failures still require a pause.
function requiresDialerPause(error?: MediaError) {
  const code = error?.code;
  return (
    code !== undefined &&
    ((code >= 20100 && code < 20200) ||
      (code >= 31100 && code < 31300) ||
      (code >= 53000 && code < 53500) ||
      code === 31001 ||
      code === 31009 ||
      code === 31401 ||
      code === 31402)
  );
}
export type Transport = {
  voicemail?: (id: string, signal: AbortSignal) => Promise<unknown>;
  session: (signal: AbortSignal) => Promise<Session>;
  reserve: (
    id: string,
    signal: AbortSignal,
    destination: string,
    campaignId?: string,
  ) => Promise<{ intent: Intent; token: string }>;
  cancel: (id: string, signal: AbortSignal) => Promise<Intent>;
  history: (id: string, signal: AbortSignal) => Promise<{ intent: Intent }>;
};
export type Dialer = {
  mode: "running" | "paused" | "stopped" | "booking";
  generation: number;
  campaign_id: string | null;
  browser_id: string | null;
  hold_token?: string | null;
  owned_session?: boolean;
};
export type AutomaticTransport = {
  session: (
    signal: AbortSignal,
  ) => Promise<{ dialer: Dialer; enabled: boolean }>;
  control: (
    body: Record<string, unknown>,
    signal: AbortSignal,
  ) => Promise<{ dialer: Dialer }>;
  heartbeat: (
    body: { browser_id: string; generation: number },
    signal: AbortSignal,
  ) => Promise<{ dialer: Dialer }>;
  next: (
    body: { id: string; browser_id: string; generation: number },
    signal: AbortSignal,
  ) => Promise<{
    intent?: Intent;
    token?: string;
    idle?: string;
    dialer: Dialer;
  }>;
};
export type PhoneState = {
  inboundBusy: boolean;
  voicemailPending: string[];
  voicemailFailures: { id: string; destination: string }[];
  loaded: boolean;
  enabled: boolean;
  destination: string | null;
  dialNumber: string;
  maxDurationSeconds: number;
  inputDevice: string;
  campaignId: string;
  automatic: Dialer | null;
  automaticLoaded: boolean;
  automaticRunning: boolean;
  automaticNextAt: number | null;
  automaticBusy: boolean;
  automaticMessage: string;
  automaticError: string;
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
  lastIntent: Intent | null;
  local: boolean;
  error: string;
  result: string;
};
const terminal = (row: Intent) =>
  ["finished", "cancelled", "expired"].includes(row.state);

export class PhoneController {
  private voicemailRequests = new Map<
    string,
    { id: string; destination: string }
  >();
  private transport: Transport;
  private factory: (token: string) => Promise<MediaDevice>;
  private listeners = new Set<() => void>();
  private device: MediaDevice | null = null;
  private call: MediaCall | null = null;
  private generation = 0;
  private closed = false;
  private refreshing = false;
  private refreshAgain = false;
  private identifier: string | null = null;
  private watchdog: ReturnType<typeof setTimeout> | null = null;
  private pending: number | null = null;
  private requests = new AbortController();
  private mediaAttempted = false;
  private automaticTransport?: AutomaticTransport;
  private browserId = crypto.randomUUID();
  private automaticEpoch = 0;
  private automaticPolling = false;
  private automaticArmed = false;
  private bookingArmed = false;
  state: PhoneState = {
    inboundBusy: false,
    voicemailPending: [],
    voicemailFailures: [],
    loaded: false,
    enabled: false,
    destination: null,
    dialNumber: "",
    maxDurationSeconds: 180,
    inputDevice: "",
    campaignId: "",
    automatic: null,
    automaticLoaded: false,
    automaticRunning: false,
    automaticNextAt: null,
    automaticBusy: false,
    automaticMessage: "",
    automaticError: "",
    phase: "idle",
    intent: null,
    lastIntent: null,
    local: false,
    error: "",
    result: "",
  };

  constructor(
    transport: Transport,
    factory: (token: string) => Promise<MediaDevice>,
    automaticTransport?: AutomaticTransport,
  ) {
    this.transport = transport;
    this.factory = factory;
    this.automaticTransport = automaticTransport;
  }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  snapshot = () => this.state;
  setInboundBusy(value: boolean) {
    if (value === this.state.inboundBusy) return;
    this.update({
      inboundBusy: value,
      ...(!value && this.state.inboundBusy && this.automaticArmed
        ? { automaticNextAt: performance.now() + 10_000 }
        : {}),
    });
  }
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
    const automatic = row.automatic || this.state.intent?.automatic;
    ++this.generation;
    this.identifier = null;
    this.pending = null;
    this.release();
    this.update({
      phase: "idle",
      intent: null,
      lastIntent:
        row.state === "finished"
          ? { ...this.state.intent, ...row }
          : this.state.lastIntent,
      local: false,
      error: "",
      result: row.outcome || row.state,
      automaticNextAt: automatic ? performance.now() + 10_000 : null,
    });
    return true;
  }
  async refresh() {
    if (this.closed) return;
    if (this.refreshing) {
      this.refreshAgain = true;
      return;
    }
    this.refreshing = true;
    const generation = this.generation;
    let observedSession: Session | null = null;
    try {
      const session = await this.transport.session(this.requests.signal);
      if (this.closed || generation !== this.generation) return;
      observedSession = session;
      this.update({
        loaded: true,
        enabled: session.enabled,
        maxDurationSeconds: Math.max(
          60,
          Math.min(1800, session.max_duration_seconds || 180),
        ),
        destination: session.active?.destination ?? this.state.destination,
      });
      if (this.pending !== null && !this.state.intent) return;
      if (this.identifier) {
        const { intent } = await this.transport.history(
          this.identifier,
          this.requests.signal,
        );
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
      if (this.refreshAgain && !this.closed) {
        this.refreshAgain = false;
        void this.refresh();
      }
    }
  }
  setDialNumber(value: string) {
    if (this.closed || this.state.phase !== "idle") return;
    this.update({ dialNumber: value.slice(0, 40), error: "" });
  }
  setInputDevice(value: string) {
    if (this.closed || this.state.phase !== "idle") return;
    this.update({ inputDevice: value });
  }
  setCampaignId(value: string) {
    if (this.closed || this.state.phase !== "idle" || this.automaticArmed)
      return;
    this.update({ campaignId: value });
  }
  private applyAutomatic(row: Dialer) {
    if (row.mode !== "running" || row.browser_id !== this.browserId)
      this.automaticArmed = false;
    this.update({
      automatic: row,
      automaticLoaded: true,
      automaticRunning: this.automaticArmed && row.mode === "running",
      automaticNextAt:
        row.browser_id === this.browserId &&
        (row.mode === "running" || row.mode === "booking")
          ? this.state.automaticNextAt
          : null,
    });
  }
  async refreshAutomatic() {
    if (!this.automaticTransport || this.closed) return;
    const epoch = this.automaticEpoch;
    try {
      const result = await this.automaticTransport.session(
        this.requests.signal,
      );
      if (this.closed || epoch !== this.automaticEpoch) return;
      this.applyAutomatic(result.dialer);
    } catch {
      if (!this.closed && epoch === this.automaticEpoch)
        this.update({
          automaticLoaded: true,
          automaticError:
            "Le composeur ne peut pas être vérifié. Actualisez avant de le démarrer.",
        });
    }
  }
  async startAutomatic(campaignId: string) {
    if (
      !this.automaticTransport ||
      this.closed ||
      !this.state.enabled ||
      !this.state.loaded ||
      this.state.automaticBusy ||
      !campaignId
    )
      return;
    const epoch = ++this.automaticEpoch;
    this.automaticFailures = 0;
    this.update({ automaticBusy: true, automaticError: "" });
    try {
      const result = await this.automaticTransport.control(
        {
          action: "start",
          browser_id: this.browserId,
          campaign_id: campaignId,
        },
        this.requests.signal,
      );
      if (this.closed || epoch !== this.automaticEpoch) return;
      this.automaticArmed = true;
      this.applyAutomatic(result.dialer);
      this.update({
        campaignId,
        automaticNextAt: null,
        automaticMessage: "Recherche du prochain contact ou rappel dû…",
      });
    } catch (error) {
      if (!this.closed && epoch === this.automaticEpoch)
        this.update({
          automaticError:
            error instanceof Error
              ? error.message
              : "Le composeur n’a pas démarré.",
        });
    } finally {
      if (!this.closed && epoch === this.automaticEpoch)
        this.update({ automaticBusy: false });
    }
  }
  async pauseAutomatic(stop = false) {
    this.automaticArmed = false;
    const epoch = ++this.automaticEpoch;
    this.update({
      automaticRunning: false,
      automaticBusy: true,
      automaticNextAt: null,
      automaticMessage: stop
        ? "Enchaînement arrêté."
        : "Enchaînement en pause.",
    });
    const row = this.state.automatic;
    try {
      if (
        this.automaticTransport &&
        row?.generation &&
        row.browser_id === this.browserId
      ) {
        const result = await this.automaticTransport.control(
          {
            action: stop ? "stop" : "pause",
            browser_id: this.browserId,
            generation: row.generation,
          },
          this.requests.signal,
        );
        if (!this.closed && epoch === this.automaticEpoch)
          this.applyAutomatic(result.dialer);
      }
    } catch {
      if (!this.closed && epoch === this.automaticEpoch)
        this.update({
          automaticError:
            "L’enchaînement est suspendu sur cet appareil. La confirmation serveur reste à vérifier.",
        });
    } finally {
      if (!this.closed && epoch === this.automaticEpoch)
        this.update({ automaticBusy: false });
    }
  }
  async beginBooking(campaignId: string): Promise<string | null> {
    if (!this.automaticTransport || this.closed) return null;
    this.bookingArmed = this.automaticArmed;
    this.automaticArmed = false;
    this.update({ automaticRunning: false });
    const epoch = ++this.automaticEpoch;
    const current = await this.automaticTransport.session(this.requests.signal);
    if (this.closed || epoch !== this.automaticEpoch)
      throw new Error("La session du composeur a changé.");
    const hold = crypto.randomUUID();
    const result = await this.automaticTransport.control(
      {
        action: "hold",
        browser_id: this.browserId,
        campaign_id: campaignId,
        generation: current.dialer.generation || undefined,
        hold_token: hold,
      },
      this.requests.signal,
    );
    if (this.closed || epoch !== this.automaticEpoch)
      throw new Error("La saisie du rendez-vous doit être vérifiée.");
    this.applyAutomatic(result.dialer);
    return hold;
  }
  async endBooking(token: string | null) {
    const row = this.state.automatic;
    if (
      !this.automaticTransport ||
      !token ||
      !row ||
      row.hold_token !== token ||
      this.closed
    )
      return;
    const epoch = ++this.automaticEpoch;
    try {
      const result = await this.automaticTransport.control(
        {
          action: "release",
          browser_id: this.browserId,
          generation: row.generation,
          hold_token: token,
        },
        this.requests.signal,
      );
      if (this.closed || epoch !== this.automaticEpoch) return;
      this.automaticArmed = this.bookingArmed;
      this.bookingArmed = false;
      this.applyAutomatic(result.dialer);
    } catch {
      if (!this.closed && epoch === this.automaticEpoch)
        this.update({
          automaticError:
            "Le composeur reste en pause. Vérifiez puis reprenez explicitement.",
        });
    }
  }
  private automaticFailures = 0;
  async automaticTick() {
    const row = this.state.automatic;
    if (
      !this.automaticTransport ||
      this.closed ||
      (!this.automaticArmed &&
        !(row?.mode === "booking" && row.browser_id === this.browserId)) ||
      this.automaticPolling ||
      this.state.automaticBusy ||
      !row
    )
      return;
    this.automaticPolling = true;
    const epoch = this.automaticEpoch;
    try {
      const result = await this.automaticTransport.heartbeat(
        { browser_id: this.browserId, generation: row.generation },
        this.requests.signal,
      );
      if (this.closed || epoch !== this.automaticEpoch) return;
      this.automaticFailures = 0;
      this.update({ automaticError: "" });
      this.applyAutomatic(result.dialer);
      if (
        this.automaticArmed &&
        this.state.phase === "idle" &&
        !this.state.inboundBusy
      )
        await this.start(undefined, "", this.state.campaignId, true);
    } catch (error) {
      if (!this.closed && epoch === this.automaticEpoch) {
        const status =
          error && typeof error === "object" && "status" in error
            ? error.status
            : null;
        const revoked = status === 401 || status === 403 || status === 409;
        if (!revoked && ++this.automaticFailures < 3) {
          this.update({
            automaticError:
              "Connexion instable. Nouvelle vérification automatique avant le prochain appel…",
          });
          return;
        }
        this.automaticArmed = false;
        this.bookingArmed = false;
        this.update({
          automaticRunning: false,
          automaticNextAt: null,
          automaticError: revoked
            ? "La session du composeur a changé. Vérifiez son état avant de reprendre."
            : "Composeur suspendu après plusieurs échecs de connexion. Vérifiez l’appel avant de reprendre.",
        });
      }
    } finally {
      this.automaticPolling = false;
    }
  }
  async start(
    input = this.state.inputDevice,
    number = this.state.dialNumber,
    campaignId = "",
    automatic = false,
  ) {
    if (
      this.closed ||
      !this.state.loaded ||
      !this.state.enabled ||
      this.state.phase !== "idle" ||
      this.state.inboundBusy ||
      this.pending ||
      (!automatic && this.automaticArmed) ||
      (automatic &&
        (!this.automaticArmed ||
          (this.state.automaticNextAt !== null &&
            performance.now() < this.state.automaticNextAt)))
    )
      return;
    // Strip only presentation characters. Extensions, letters and control
    // characters must never be interpreted as a different phone number.
    const destination = number.replace(/[ ().-]/g, "");
    if (
      !automatic &&
      (destination.trim() !== destination ||
        !/^\+[1-9][0-9]{8,14}$/.test(destination))
    ) {
      this.update({
        error:
          "Saisissez un numéro avec son indicatif international, par exemple +15145550123.",
      });
      return;
    }
    const generation = ++this.generation;
    const automaticEpoch = this.automaticEpoch;
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
      destination,
      automaticNextAt: null,
    });
    let attemptedConnect = false;
    let reservationAccepted = false;
    try {
      const reserved =
        automatic && this.automaticTransport && this.state.automatic
          ? await this.automaticTransport.next(
              {
                id,
                browser_id: this.browserId,
                generation: this.state.automatic.generation,
              },
              this.requests.signal,
            )
          : await this.transport.reserve(
              id,
              this.requests.signal,
              destination,
              campaignId || undefined,
            );
      if (this.closed || generation !== this.generation) return;
      if (
        !("intent" in reserved) ||
        !reserved.intent ||
        !("token" in reserved) ||
        !reserved.token
      ) {
        this.identifier = null;
        this.pending = null;
        const reasons: Record<string, string> = {
          empty:
            "Aucun contact disponible. Les rappels dus restent prioritaires.",
          policy:
            "Les horaires, numéros ou délais de rappel ne permettent aucun appel pour le moment.",
          claimed: "Les contacts disponibles sont déjà pris en charge.",
          settling: "Enregistrement du résultat de l’appel…",
          active_call: "Un appel reste à vérifier avant de continuer.",
          inbound_call:
            "Un appel entrant est en cours. L’enchaînement reprendra après sa fin.",
          presence_expired:
            "Session du composeur expirée. Reprenez explicitement.",
        };
        if ("dialer" in reserved && automaticEpoch === this.automaticEpoch)
          this.applyAutomatic(reserved.dialer);
        this.release();
        this.update({
          phase: "idle",
          local: false,
          intent: null,
          automaticMessage:
            "idle" in reserved
              ? reasons[reserved.idle || ""] || "Composeur en attente."
              : "Composeur en attente.",
        });
        return;
      }
      reservationAccepted = true;
      if (
        automatic &&
        (!this.automaticArmed || automaticEpoch !== this.automaticEpoch)
      ) {
        this.update({
          intent: { ...reserved.intent, owned_session: true },
          phase: "checking",
          local: false,
        });
        const cancelled = await this.transport.cancel(id, this.requests.signal);
        this.settle(cancelled);
        return;
      }
      if (automatic && "dialer" in reserved)
        this.applyAutomatic(reserved.dialer);
      this.update({ intent: { ...reserved.intent, owned_session: true } });
      if (automatic) this.update({ automaticMessage: "" });
      this.update({ destination: reserved.intent.destination || destination });
      const device = await this.factory(reserved.token);
      // The token stays only in this stack and the SDK, never in React/storage.
      if (this.closed || generation !== this.generation) {
        device.destroy();
        return;
      }
      this.device = device;
      const mediaLifecycle = this.requests;
      let failurePaused = false;
      const mediaError = (
        error: MediaError | undefined,
        callScoped: boolean,
      ) => {
        if (this.closed || this.requests !== mediaLifecycle) return;
        const current = generation === this.generation;
        // The SDK can emit disconnect before its fatal media error. Accept
        // that error only while this same intent is still being reconciled;
        // an old device must never pause a later call.
        if (!current && this.identifier !== id) return;
        if (automatic && (!callScoped || requiresDialerPause(error))) {
          // A late fatal error cannot replace a newer stop or drop a booking
          // hold. Disarm its eventual release without changing the hold.
          this.bookingArmed = false;
          if (this.automaticArmed && !failurePaused) {
            failurePaused = true;
            void this.pauseAutomatic();
          }
        }
        if (current) this.interrupted();
      };
      device.onError((error, call) => {
        mediaError(error, Boolean(call));
      });
      if (this.closed || generation !== this.generation) {
        device.destroy();
        return;
      }
      if (
        automatic &&
        (!this.automaticArmed || automaticEpoch !== this.automaticEpoch)
      ) {
        device.destroy();
        this.settle(await this.transport.cancel(id, this.requests.signal));
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
        call.on(event, (error) => {
          if (event === "error") {
            mediaError(error, true);
            return;
          }
          if (generation === this.generation) {
            this.interrupted();
          }
        });
      // Include up to 60 s ringing and 30 s signalling teardown. The provider
      // still enforces the exact conversation limit after the customer answers.
      if (this.watchdog !== null) clearTimeout(this.watchdog);
      this.watchdog = setTimeout(
        () => this.hangup(),
        (this.state.maxDurationSeconds + 90) * 1000,
      );
    } catch (error) {
      if (this.closed || generation !== this.generation) return;
      if (automatic) void this.pauseAutomatic();
      ++this.generation;
      this.release();
      if (
        !reservationAccepted &&
        error instanceof Error &&
        "status" in error &&
        typeof error.status === "number" &&
        error.status >= 400 &&
        error.status < 500
      ) {
        // A rejected reservation created no call to cancel. Show its actual
        // explanation, then recover any existing call reported by the server.
        this.identifier = null;
        this.pending = null;
        this.update({
          phase: "idle",
          intent: null,
          local: false,
          error: error.message,
        });
        await this.refresh();
        return;
      }
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
          const row = await this.transport.cancel(id, this.requests.signal);
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
  async voicemail() {
    const row = this.state.intent;
    if (!row || !this.state.local || !this.transport.voicemail || this.closed)
      return;
    const saving = this.saveVoicemail({
      id: row.id,
      destination: row.destination || this.state.destination || "",
    });
    this.hangup();
    await saving;
  }
  async retryVoicemail(id: string) {
    const entry = this.state.voicemailFailures.find((row) => row.id === id);
    if (entry) await this.saveVoicemail(entry);
  }
  private async saveVoicemail(entry: { id: string; destination: string }) {
    if (
      !this.transport.voicemail ||
      this.closed ||
      this.voicemailRequests.has(entry.id)
    )
      return;
    const lifecycle = this.requests;
    const current = () =>
      !this.closed && !lifecycle.signal.aborted && lifecycle === this.requests;
    this.voicemailRequests.set(entry.id, entry);
    this.update({ voicemailPending: [...this.voicemailRequests.keys()] });
    try {
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          await this.transport.voicemail(entry.id, lifecycle.signal);
          if (current())
            this.update({
              voicemailFailures: this.state.voicemailFailures.filter(
                (row) => row.id !== entry.id,
              ),
            });
          return;
        } catch {
          if (!current()) return;
          if (attempt < 2)
            await new Promise((resolve) => setTimeout(resolve, 500));
        }
      }
      if (current()) {
        this.update({
          voicemailFailures: [
            ...this.state.voicemailFailures.filter(
              (row) => row.id !== entry.id,
            ),
            entry,
          ],
        });
        if (this.state.automaticRunning) await this.pauseAutomatic();
      }
    } finally {
      if (current()) {
        this.voicemailRequests.delete(entry.id);
        this.update({ voicemailPending: [...this.voicemailRequests.keys()] });
      }
    }
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
        .cancel(id, this.requests.signal)
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
      const cancelled = await this.transport.cancel(
        row.id,
        this.requests.signal,
      );
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
    this.state = {
      ...this.state,
      voicemailPending: [],
      voicemailFailures: [
        ...new Map([
          ...this.state.voicemailFailures.map((row) => [row.id, row] as const),
          ...this.voicemailRequests.entries(),
        ]).values(),
      ],
    };
    this.voicemailRequests.clear();
    this.automaticArmed = false;
    ++this.automaticEpoch;
    this.closed = true;
    this.requests.abort();
    ++this.generation;
    this.release();
  }
  activate() {
    if (!this.closed) return;
    this.closed = false;
    this.requests = new AbortController();
    this.refreshing = false;
    this.refreshAgain = false;
    this.pending = null;
    this.automaticArmed = false;
    this.update({
      local: false,
      inboundBusy: false,
      automaticRunning: false,
      automaticBusy: false,
      automaticNextAt: null,
      phase: this.identifier ? "checking" : "idle",
    });
  }
}
