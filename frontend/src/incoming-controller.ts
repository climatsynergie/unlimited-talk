// Provider terminal state, never a browser event or presence timeout, frees calls.
export type IncomingOffer = {
  id: string;
  call_id: string;
  registration_id: string;
  caller_number: string | null;
  called_number: string;
  queue_name: string;
  state: string;
  call_state: string;
  owned_session?: boolean;
};
export type IncomingSession = {
  enabled: boolean;
  queues: { id: string; name: string; phone: string }[];
  registration: {
    id: string;
    browser_id: string;
    available: boolean;
    media_ready: boolean;
    alive: boolean;
    owned_session: boolean;
  } | null;
  active: (Omit<IncomingOffer, "id"> & { offer_id: string }) | null;
};
export type IncomingMediaCall = {
  offerId: string;
  on: (event: string, listener: () => void) => void;
  accept: (input: string) => Promise<void>;
  reject: () => void;
  disconnect: () => void;
};
export type IncomingMediaDevice = {
  register: () => Promise<void>;
  updateToken: (token: string) => void;
  releaseInput: () => void;
  destroy: () => void;
};
export type IncomingCallbacks = {
  incoming: (call: IncomingMediaCall) => void;
  registered: () => void;
  unregistered: () => void;
  tokenWillExpire: () => void;
  error: () => void;
};
export type IncomingTransport = {
  session: (signal: AbortSignal) => Promise<IncomingSession>;
  register: (
    browser: string,
    signal: AbortSignal,
  ) => Promise<{ id: string; token: string }>;
  heartbeat: (
    id: string,
    available: boolean,
    ready: boolean,
    signal: AbortSignal,
  ) => Promise<{
    available: boolean;
    media_ready: boolean;
    active: IncomingSession["active"];
  }>;
  token: (id: string, signal: AbortSignal) => Promise<{ token: string }>;
  offer: (id: string, signal: AbortSignal) => Promise<IncomingOffer>;
  choose: (
    id: string,
    registration: string,
    accept: boolean,
    signal: AbortSignal,
  ) => Promise<IncomingOffer>;
  leave: (id: string) => Promise<unknown>;
};
export type IncomingState = {
  loaded: boolean;
  enabled: boolean;
  wanted: boolean;
  registered: boolean;
  phase:
    | "idle"
    | "registering"
    | "ringing"
    | "connecting"
    | "connected"
    | "reconnecting"
    | "checking";
  queues: IncomingSession["queues"];
  registrationId: string | null;
  offer: IncomingOffer | null;
  local: boolean;
  error: string;
};
export class IncomingController {
  state: IncomingState = {
    loaded: false,
    enabled: false,
    wanted: false,
    registered: false,
    phase: "idle",
    queues: [],
    registrationId: null,
    offer: null,
    local: false,
    error: "",
  };
  private listeners = new Set<() => void>();
  private requests = new AbortController();
  private closed = false;
  private generation = 0;
  private contextRevision = 0;
  private device: IncomingMediaDevice | null = null;
  private call: IncomingMediaCall | null = null;
  private polling = false;
  private renewing = false;
  private starting = false;
  private renewDue = false;
  private lastHeartbeat = 0;
  private failures = 0;
  readonly browserId: string;
  private transport: IncomingTransport;
  private factory: (
    token: string,
    handlers: IncomingCallbacks,
  ) => Promise<IncomingMediaDevice>;
  private options: {
    onBusy: (value: boolean) => void;
    input: () => string;
    probe: () => Promise<void>;
    outgoingMedia: () => boolean;
    browserId?: string;
  };
  constructor(
    transport: IncomingTransport,
    factory: IncomingController["factory"],
    options: IncomingController["options"],
  ) {
    this.transport = transport;
    this.factory = factory;
    this.options = options;
    this.browserId = options.browserId || crypto.randomUUID();
  }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  snapshot = () => this.state;
  private update(patch: Partial<IncomingState>) {
    if (this.closed) return;
    if ("offer" in patch || "registrationId" in patch || "local" in patch)
      ++this.contextRevision;
    this.state = { ...this.state, ...patch };
    this.options.onBusy(!!this.state.offer || !!this.call);
    for (const listener of this.listeners) listener();
  }
  async prepare() {
    const lifecycle = this.requests;
    const generation = this.generation;
    const context = this.contextRevision;
    const current = () =>
      !this.closed &&
      lifecycle === this.requests &&
      generation === this.generation &&
      context === this.contextRevision;
    try {
      const data = await this.transport.session(lifecycle.signal);
      // An older session snapshot cannot settle an offer or registration that
      // appeared while its request was in flight.
      if (!current()) return;
      this.update({ loaded: true, enabled: data.enabled, queues: data.queues });
      if (
        data.registration?.owned_session &&
        data.registration.browser_id === this.browserId
      )
        this.update({ registrationId: data.registration.id });
      if (data.active && !this.state.offer && !this.call) {
        const { offer_id, ...rest } = data.active;
        this.update({
          offer: { ...rest, id: offer_id },
          phase: "checking",
          local: false,
        });
      } else if (!data.active && this.state.offer && !this.call)
        this.clearOffer();
    } catch {
      if (current())
        this.update({
          loaded: true,
          error: "La réception n’a pas pu être vérifiée. Réessayez.",
        });
    }
  }
  async start() {
    if (this.closed || this.starting) return;
    this.update({ wanted: true, error: "" });
    if (this.device) {
      try {
        if (!this.call) await this.options.probe();
        if (!this.call && (!this.state.registered || this.renewDue))
          await this.renew();
        await this.beat();
      } catch {
        if (!this.closed)
          this.update({
            wanted: false,
            error:
              "Vérifiez le microphone et la connexion, puis reprenez la réception.",
          });
      }
      return;
    }
    this.starting = true;
    const generation = ++this.generation;
    this.update({ phase: this.state.offer ? "checking" : "registering" });
    try {
      await this.options.probe();
      if (this.closed || generation !== this.generation) return;
      const registration = await this.transport.register(
        this.browserId,
        this.requests.signal,
      );
      if (this.closed || generation !== this.generation) return;
      this.update({ registrationId: registration.id });
      const device = await this.factory(registration.token, {
        incoming: (call) => {
          if (this.closed || generation !== this.generation) {
            call.reject();
            return;
          }
          void this.received(call, generation);
        },
        registered: () => {
          if (!this.closed && generation === this.generation) {
            this.update({ registered: true });
            this.lastHeartbeat = 0;
            void this.beat().catch(() => {});
          }
        },
        unregistered: () => {
          if (!this.closed && generation === this.generation) {
            this.update({ registered: false });
            this.renewDue = true;
            this.lastHeartbeat = 0;
          }
        },
        tokenWillExpire: () => {
          if (!this.closed && generation === this.generation)
            this.renewDue = true;
        },
        error: () => {
          if (!this.closed && generation === this.generation)
            this.update({
              wanted: false,
              error:
                "La réception est en pause après une erreur du téléphone. Vérifiez le casque puis reprenez-la.",
            });
        },
      });
      if (this.closed || generation !== this.generation) {
        device.destroy();
        return;
      }
      this.device = device;
      await device.register();
      if (this.closed || generation !== this.generation) return;
      this.failures = 0;
      this.update({
        phase: this.state.offer ? "checking" : "idle",
        registered: true,
      });
      await this.beat();
    } catch (error) {
      if (!this.closed && generation === this.generation) {
        if (this.call && this.state.offer) {
          // Registration can already have admitted an incoming call before
          // the final setup heartbeat returns. Keep its media on control-plane
          // failure, just as later heartbeat failures preserve ongoing calls.
          this.update({
            wanted: false,
            error:
              "La réception est en pause. L’appel actuel est conservé pendant la vérification du réseau.",
          });
          this.lastHeartbeat = 0;
          return;
        }
        ++this.generation;
        try {
          this.call?.reject();
        } catch {
          /* No media may survive failed setup. */
        }
        this.call = null;
        this.update({
          wanted: false,
          registered: false,
          local: false,
          phase: this.state.offer ? "checking" : "idle",
          error:
            error instanceof Error
              ? error.message
              : "Autorisez le microphone et reprenez la réception.",
        });
        this.device?.destroy();
        this.device = null;
        if (this.state.registrationId)
          void this.transport.leave(this.state.registrationId).catch(() => {});
      }
    } finally {
      if (generation === this.generation || generation + 1 === this.generation)
        this.starting = false;
    }
  }
  async pause() {
    this.update({ wanted: false, error: "" });
    await this.beat()
      .then(() => {
        if (!this.state.offer && !this.call) this.closeIdleReceiver();
      })
      .catch(() => {
        if (!this.closed)
          this.update({
            error: "La pause sera confirmée dès le retour du réseau.",
          });
      });
  }
  private async beat() {
    const id = this.state.registrationId;
    if (!id || this.closed) return;
    const lifecycle = this.requests;
    const expectedOffer = this.state.offer?.id;
    const result = await this.transport.heartbeat(
      id,
      this.state.wanted,
      this.state.registered && !(this.state.phase === "checking" && !this.call),
      lifecycle.signal,
    );
    if (this.closed || lifecycle !== this.requests) return;
    this.lastHeartbeat = performance.now();
    if (id !== this.state.registrationId) return;
    if (!result.available && this.state.wanted)
      this.update({
        wanted: false,
        error:
          "La réception est en pause. Vérifiez votre attribution puis reprenez-la.",
      });
    if (result.active && !this.state.offer && !this.call) {
      const { offer_id, ...rest } = result.active;
      this.update({ offer: { ...rest, id: offer_id }, phase: "checking" });
    }
    if (
      !result.active &&
      expectedOffer &&
      this.state.offer?.id === expectedOffer
    )
      this.clearOffer();
  }
  private async renew() {
    if (
      this.closed ||
      this.call ||
      this.renewing ||
      !this.device ||
      !this.state.registrationId
    )
      return;
    this.renewing = true;
    const generation = this.generation;
    try {
      const refreshed = await this.transport.token(
        this.state.registrationId,
        this.requests.signal,
      );
      if (this.closed || generation !== this.generation || this.call) return;
      this.device.updateToken(refreshed.token);
      if (!this.state.registered) await this.device.register();
      if (!this.closed && generation === this.generation) {
        this.renewDue = false;
        this.failures = 0;
      }
    } finally {
      if (generation === this.generation) this.renewing = false;
    }
  }
  async tick() {
    if (
      this.closed ||
      this.polling ||
      (!this.state.registrationId && !this.state.offer)
    )
      return;
    this.polling = true;
    const lifecycle = this.requests;
    try {
      if (performance.now() - this.lastHeartbeat >= 10000) await this.beat();
      if (this.closed || lifecycle !== this.requests) return;
      const offer = this.state.offer;
      if (offer) {
        if (offer.owned_session === false) await this.prepare();
        else {
          const fresh = await this.transport.offer(offer.id, lifecycle.signal);
          if (
            !this.closed &&
            lifecycle === this.requests &&
            this.state.offer?.id === offer.id
          ) {
            if (fresh.state === "finished") this.clearOffer();
            else this.update({ offer: fresh });
          }
        }
      }
      if (
        this.state.wanted &&
        !this.call &&
        (this.renewDue || !this.state.registered)
      )
        await this.renew();
      this.failures = 0;
    } catch (error) {
      if (this.closed || lifecycle !== this.requests) return;
      this.failures++;
      const status =
        error && typeof error === "object" && "status" in error
          ? error.status
          : null;
      if (this.failures >= 3 || [401, 403, 404, 409].includes(Number(status))) {
        if ([401, 403].includes(Number(status)) && this.call) this.hangup();
        if (Number(status) === 404 && !this.call && !this.state.offer) {
          this.device?.destroy();
          this.device = null;
          this.update({ registrationId: null, registered: false });
        }
        this.update({
          wanted: false,
          error:
            "La réception est en pause après une perte de connexion. Vérifiez l’appel puis reprenez-la.",
        });
      }
    } finally {
      if (lifecycle === this.requests) this.polling = false;
    }
  }
  private async received(call: IncomingMediaCall, generation: number) {
    if (this.call === call) return;
    if (
      !this.state.wanted ||
      this.call ||
      this.options.outgoingMedia() ||
      !/^[a-f0-9-]{36}$/.test(call.offerId)
    ) {
      call.reject();
      return;
    }
    this.call = call;
    for (const event of ["cancel", "disconnect", "error"])
      call.on(event, () => {
        if (
          !this.closed &&
          generation === this.generation &&
          this.call === call
        )
          this.mediaEnded(call);
      });
    this.update({ phase: "checking", local: true });
    try {
      const offer = await this.transport.offer(
        call.offerId,
        this.requests.signal,
      );
      if (this.closed || generation !== this.generation || this.call !== call) {
        call.reject();
        return;
      }
      if (
        offer.registration_id !== this.state.registrationId ||
        !["offered", "accepted"].includes(offer.state) ||
        offer.call_state !== "offered"
      ) {
        call.reject();
        this.clearOffer();
        return;
      }
      this.update({ offer, phase: "ringing", local: true, error: "" });
      call.on("accept", () => {
        if (
          !this.closed &&
          generation === this.generation &&
          this.call === call
        )
          this.update({ phase: "connected" });
      });
      call.on("reconnecting", () => {
        if (
          !this.closed &&
          generation === this.generation &&
          this.call === call
        )
          this.update({ phase: "reconnecting" });
      });
      call.on("reconnected", () => {
        if (
          !this.closed &&
          generation === this.generation &&
          this.call === call
        )
          this.update({ phase: "connected" });
      });
    } catch {
      call.reject();
      if (!this.closed && generation === this.generation) {
        this.call = null;
        this.update({
          wanted: false,
          phase: "idle",
          local: false,
          error: "Cet appel n’a pas pu être vérifié. Reprenez la réception.",
        });
      }
    }
  }
  async accept() {
    const offer = this.state.offer,
      call = this.call,
      generation = this.generation;
    if (
      !offer ||
      !call ||
      this.state.phase !== "ringing" ||
      !this.state.registrationId
    )
      return;
    this.update({ phase: "connecting", error: "" });
    try {
      await this.transport.choose(
        offer.id,
        this.state.registrationId,
        true,
        this.requests.signal,
      );
      if (this.closed || generation !== this.generation || this.call !== call)
        return;
      await call.accept(this.options.input());
    } catch {
      if (
        !this.closed &&
        generation === this.generation &&
        this.call === call
      ) {
        call.reject();
        this.mediaEnded(call);
        this.update({
          error:
            "L’appel n’a pas pu être accepté. Son état sera vérifié avant le suivant.",
        });
      }
    }
  }
  reject() {
    const offer = this.state.offer,
      call = this.call;
    if (
      !offer ||
      !call ||
      !this.state.registrationId ||
      !["ringing", "connecting"].includes(this.state.phase)
    )
      return;
    void this.transport
      .choose(offer.id, this.state.registrationId, false, this.requests.signal)
      .catch(() => {});
    call.reject();
    this.mediaEnded(call);
  }
  hangup() {
    const call = this.call;
    if (!call) return;
    call.disconnect();
    this.mediaEnded(call);
  }
  private mediaEnded(call: IncomingMediaCall) {
    if (this.call !== call) return;
    this.call = null;
    this.device?.releaseInput();
    this.update({
      local: false,
      phase: this.state.offer ? "checking" : "idle",
    });
    this.lastHeartbeat = 0;
    void this.tick();
  }
  private closeIdleReceiver() {
    if (this.call || this.state.offer) return;
    ++this.generation;
    this.device?.destroy();
    this.device = null;
    const id = this.state.registrationId;
    this.update({ registrationId: null, registered: false, phase: "idle" });
    if (id) void this.transport.leave(id).catch(() => {});
  }
  private clearOffer() {
    const call = this.call;
    this.call = null;
    try {
      call?.disconnect();
    } catch {
      /* Durable state is already terminal. */
    }
    this.device?.releaseInput();
    this.update({ offer: null, phase: "idle", local: false, error: "" });
    if (!this.state.wanted) this.closeIdleReceiver();
    this.lastHeartbeat = 0;
  }
  dispose() {
    if (this.closed) return;
    this.closed = true;
    ++this.generation;
    if (this.state.registrationId)
      void this.transport.leave(this.state.registrationId).catch(() => {});
    this.requests.abort();
    try {
      this.call?.disconnect();
    } catch {
      /* Provider reconciliation retains occupancy. */
    }
    this.call = null;
    this.device?.destroy();
    this.device = null;
    this.options.onBusy(false);
  }
  activate() {
    if (!this.closed) return;
    this.closed = false;
    this.requests = new AbortController();
    this.starting = false;
    this.polling = false;
    this.renewing = false;
    this.lastHeartbeat = 0;
    this.update({
      wanted: false,
      registered: false,
      local: false,
      phase: this.state.offer ? "checking" : "idle",
    });
    if (this.state.offer) void this.prepare();
  }
}
