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
  error: (error?: { code?: number }) => void;
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
  recovering: boolean;
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
    recovering: false,
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
  private retryAt = 0;
  private tokenDueAt = Infinity;
  private availabilityRevision = 0;
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
    ++this.availabilityRevision;
    this.retryAt = 0;
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
      // Refresh ahead of the SDK's last-second expiry warning, including after
      // a sleeping/background tab resumes. The server issues five-minute JWTs.
      this.tokenDueAt = performance.now() + 240_000;
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
        error: (error) => {
          if (!this.closed && generation === this.generation) {
            this.update({ registered: false });
            this.renewDue = true;
            this.lastHeartbeat = 0;
            this.failed(error);
          }
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
        recovering: false,
      });
      await this.beat();
    } catch (error) {
      if (!this.closed && generation === this.generation) {
        if (this.device) {
          // Registration can already have admitted an incoming call before
          // the final setup heartbeat returns. Keep its media on control-plane
          // failure, just as later heartbeat failures preserve ongoing calls.
          this.failed(error);
          if (!this.call)
            this.update({ phase: this.state.offer ? "checking" : "idle" });
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
    const revision = ++this.availabilityRevision;
    this.retryAt = 0;
    this.update({ wanted: false, recovering: false, error: "" });
    await this.beat()
      .then(() => {
        if (
          revision === this.availabilityRevision &&
          !this.state.wanted &&
          !this.state.offer &&
          !this.call
        )
          this.closeIdleReceiver();
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
    const generation = this.generation;
    const expectedOffer = this.state.offer?.id;
    const wanted = this.state.wanted;
    const revision = this.availabilityRevision;
    const result = await this.transport.heartbeat(
      id,
      wanted,
      this.state.registered &&
        !this.state.recovering &&
        !(this.state.phase === "checking" && !this.call),
      lifecycle.signal,
    );
    if (
      this.closed ||
      lifecycle !== this.requests ||
      generation !== this.generation
    )
      return;
    this.lastHeartbeat =
      revision === this.availabilityRevision ? performance.now() : 0;
    if (id !== this.state.registrationId) return;
    if (
      !result.available &&
      wanted &&
      this.state.wanted &&
      revision === this.availabilityRevision
    )
      this.update({
        wanted: false,
        recovering: false,
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
      !this.state.wanted ||
      !this.state.registrationId
    )
      return;
    this.renewing = true;
    const generation = this.generation;
    const revision = this.availabilityRevision;
    try {
      const refreshed = await this.transport.token(
        this.state.registrationId,
        this.requests.signal,
      );
      if (
        this.closed ||
        generation !== this.generation ||
        this.call ||
        !this.state.wanted ||
        revision !== this.availabilityRevision
      )
        return;
      this.device.updateToken(refreshed.token);
      if (!this.state.registered) await this.device.register();
      if (!this.closed && generation === this.generation) {
        this.renewDue = false;
        this.tokenDueAt = performance.now() + 240_000;
      }
    } finally {
      if (generation === this.generation) this.renewing = false;
    }
  }
  wake() {
    if (this.closed || !this.state.wanted) return;
    this.retryAt = 0;
    this.lastHeartbeat = 0;
    void this.tick();
  }
  async tick() {
    if (
      this.closed ||
      this.starting ||
      this.polling ||
      performance.now() < this.retryAt ||
      (!this.state.registrationId && !this.state.offer)
    )
      return;
    this.polling = true;
    const lifecycle = this.requests;
    const generation = this.generation;
    try {
      // Renew before waiting on HTTP presence. A slow heartbeat must not use
      // the entire remaining lifetime of a token. Avoid token updates in audio.
      if (
        this.state.wanted &&
        !this.call &&
        !this.options.outgoingMedia() &&
        (this.renewDue ||
          !this.state.registered ||
          performance.now() >= this.tokenDueAt)
      )
        await this.renew();
      if (
        this.closed ||
        lifecycle !== this.requests ||
        generation !== this.generation
      )
        return;
      if (performance.now() - this.lastHeartbeat >= 10000) await this.beat();
      if (
        this.closed ||
        lifecycle !== this.requests ||
        generation !== this.generation
      )
        return;
      const offer = this.state.offer;
      if (offer) {
        if (offer.owned_session === false) await this.prepare();
        else {
          const fresh = await this.transport.offer(offer.id, lifecycle.signal);
          if (
            !this.closed &&
            lifecycle === this.requests &&
            generation === this.generation &&
            this.state.offer?.id === offer.id
          ) {
            if (fresh.state === "finished") this.clearOffer();
            else this.update({ offer: fresh });
          }
        }
      }
      this.failures = 0;
      this.retryAt = 0;
      if (this.state.wanted && this.state.registered && this.state.recovering) {
        this.update({ recovering: false, error: "" });
        this.lastHeartbeat = 0;
        await this.beat();
      }
    } catch (error) {
      if (
        this.closed ||
        lifecycle !== this.requests ||
        generation !== this.generation
      )
        return;
      this.failed(error);
    } finally {
      if (lifecycle === this.requests && generation === this.generation)
        this.polling = false;
    }
  }
  private failed(error: unknown) {
    const status =
      error && typeof error === "object" && "status" in error
        ? Number(error.status)
        : 0;
    const code =
      error && typeof error === "object" && "code" in error
        ? Number(error.code)
        : 0;
    // Expired JWTs (20104/31205), transport failures and server outages retry.
    // Revoked application access, invalid configuration and denied microphone
    // permissions require intervention; never turn a manual pause back on.
    const blocked =
      [401, 403, 404, 409].includes(status) ||
      [
        20101, 20151, 31201, 31202, 31203, 31204, 31206, 31207, 31209, 31210,
        31212, 31401, 31402,
      ].includes(code);
    if (blocked) {
      ++this.availabilityRevision;
      if ([401, 403].includes(status) && this.call) this.hangup();
      if (status === 404 && !this.call && !this.state.offer) {
        this.device?.destroy();
        this.device = null;
        this.update({ registrationId: null, registered: false });
      }
      this.update({
        wanted: false,
        recovering: false,
        error: code
          ? `Réception interrompue (code ${code}). Vérifiez les autorisations du téléphone puis reprenez-la.`
          : "La réception est en pause. Vérifiez votre connexion au compte et votre attribution puis reprenez-la.",
      });
      return;
    }
    if (!this.state.wanted) return;
    this.failures++;
    this.retryAt =
      performance.now() +
      Math.min(30_000, 2000 * 2 ** Math.min(this.failures - 1, 4));
    this.update({
      recovering: true,
      error:
        "Connexion à la réception interrompue. Reconnexion automatique en cours…",
    });
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
    } catch (error) {
      call.reject();
      if (!this.closed && generation === this.generation) {
        this.call = null;
        this.update({
          phase: "idle",
          local: false,
        });
        // A caller may have hung up while metadata was loading. A failed
        // offer lookup does not revoke the receiver's own registration.
        if (
          error &&
          typeof error === "object" &&
          "status" in error &&
          Number(error.status) === 404
        )
          this.update({
            error:
              "Cet appel n’est plus disponible. La réception reste ouverte.",
          });
        else this.failed(error);
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
    this.tokenDueAt = Infinity;
    this.renewDue = false;
    this.retryAt = 0;
    this.renewing = false;
    this.polling = false;
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
    this.retryAt = 0;
    this.tokenDueAt = Infinity;
    this.renewDue = false;
    this.update({
      wanted: false,
      registered: false,
      recovering: false,
      local: false,
      phase: this.state.offer ? "checking" : "idle",
    });
    if (this.state.offer) void this.prepare();
  }
}
