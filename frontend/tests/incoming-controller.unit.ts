import { test } from "node:test";
import assert from "node:assert/strict";
import { IncomingController } from "../src/incoming-controller.ts";
import type {
  IncomingCallbacks,
  IncomingMediaCall,
  IncomingOffer,
  IncomingTransport,
} from "../src/incoming-controller.ts";
const offerId = "00000000-0000-0000-0000-000000000021";
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
const turn = () => new Promise<void>((r) => setImmediate(r));
function fixture() {
  const offer: IncomingOffer = {
    id: offerId,
    call_id: "call",
    registration_id: "reg",
    caller_number: "+14165550101",
    called_number: "+14165550102",
    queue_name: "Réception",
    state: "offered",
    call_state: "offered",
  };
  const active = () => {
    const { id, ...rest } = offer;
    return { ...rest, offer_id: id };
  };
  let handlers!: IncomingCallbacks;
  let destroyed = 0,
    accepted = 0,
    rejected = 0,
    disconnected = 0,
    tokens = 0,
    registrations = 0;
  const updatedTokens: string[] = [];
  let busy = false;
  let live = false;
  let metadata: Promise<IncomingOffer> | null = null;
  let heartbeatGate: ReturnType<
    typeof deferred<ReturnType<typeof active> | null>
  > | null = null;
  const calls: string[] = [];
  const transport: IncomingTransport = {
    session: async () => ({
      enabled: true,
      queues: [],
      registration: null,
      active: live ? active() : null,
    }),
    register: async () => ({ id: "reg", token: "PRIVATE_TOKEN" }),
    heartbeat: async (_id, available, ready) => ({
      available,
      media_ready: ready,
      active: heartbeatGate
        ? await heartbeatGate.promise
        : live
          ? active()
          : null,
    }),
    token: async () => {
      tokens++;
      return { token: "REFRESHED_PRIVATE" };
    },
    offer: async () => metadata || { ...offer },
    choose: async (id, registration, accept) => {
      calls.push(`${id}:${registration}:${accept}`);
      return { ...offer };
    },
    leave: async () => {},
  };
  const controller = new IncomingController(
    transport,
    async (_token, h) => {
      handlers = h;
      return {
        register: async () => {
          registrations++;
          h.registered();
        },
        updateToken: (token: string) => {
          updatedTokens.push(token);
        },
        releaseInput: () => {},
        destroy: () => {
          destroyed++;
        },
      };
    },
    {
      onBusy: (v) => {
        busy = v;
      },
      input: () => "micro",
      probe: async () => {},
      outgoingMedia: () => false,
      browserId: "browser",
    },
  );
  class Media implements IncomingMediaCall {
    offerId = offerId;
    events = new Map<string, () => void>();
    on(event: string, fn: () => void) {
      this.events.set(event, fn);
    }
    emit(event: string) {
      this.events.get(event)?.();
    }
    async accept(input: string) {
      assert.equal(input, "micro");
      accepted++;
      this.emit("accept");
    }
    reject() {
      rejected++;
    }
    disconnect() {
      disconnected++;
    }
  }
  return {
    controller,
    transport,
    offer,
    calls,
    active,
    Media,
    get handlers() {
      return handlers;
    },
    set live(v: boolean) {
      live = v;
    },
    set metadata(v: Promise<IncomingOffer> | null) {
      metadata = v;
    },
    set heartbeatGate(v: typeof heartbeatGate) {
      heartbeatGate = v;
    },
    stats: () => ({
      accepted,
      rejected,
      disconnected,
      destroyed,
      tokens,
      registrations,
      updatedTokens: [...updatedTokens],
      busy,
    }),
  };
}
test("incoming accept is bound to canonical offer and media disconnect never frees provider occupancy", async () => {
  const f = fixture();
  await f.controller.start();
  f.live = true;
  const call = new f.Media();
  f.handlers.incoming(call);
  await turn();
  assert.equal(f.controller.state.phase, "ringing");
  assert.equal(f.stats().busy, true);
  assert.equal(JSON.stringify(f.controller.state).includes("PRIVATE"), false);
  await f.controller.accept();
  assert.equal(f.controller.state.phase, "connected");
  assert.deepEqual(f.calls, [`${offerId}:reg:true`]);
  f.controller.hangup();
  await turn();
  assert.equal(f.stats().disconnected, 1);
  assert.equal(f.controller.state.phase, "checking");
  assert.equal(f.stats().busy, true);
  f.offer.state = "finished";
  f.offer.call_state = "finished";
  await f.controller.tick();
  assert.equal(f.stats().busy, false);
  assert.equal(f.controller.state.phase, "idle");
  f.controller.dispose();
});
test("caller cancellation while identity is loading cannot leave stale audio or ring afterwards", async () => {
  const f = fixture();
  await f.controller.start();
  const gate = deferred<IncomingOffer>();
  f.metadata = gate.promise;
  const call = new f.Media();
  f.handlers.incoming(call);
  call.emit("cancel");
  gate.resolve(f.offer);
  await turn();
  assert.equal(f.controller.state.local, false);
  assert.equal(f.controller.state.offer, null);
  assert.equal(f.stats().busy, false);
  f.controller.dispose();
});
test("heartbeat started before a new ring cannot clear that new offer", async () => {
  const f = fixture();
  await f.controller.start();
  const gate = deferred<ReturnType<typeof f.active> | null>();
  f.heartbeatGate = gate;
  const pause = f.controller.pause();
  f.live = true;
  // Resume reception while the earlier pause acknowledgement is delayed.
  const resume = f.controller.start();
  f.handlers.incoming(new f.Media());
  await turn();
  assert.equal(f.controller.state.offer?.id, offerId);
  gate.resolve(null);
  await pause;
  await resume;
  assert.equal(f.controller.state.offer?.id, offerId);
  f.controller.dispose();
});
test("credential renewal waits for end of audio; reception pause preserves current call", async () => {
  const f = fixture();
  await f.controller.start();
  f.live = true;
  f.handlers.incoming(new f.Media());
  await turn();
  await f.controller.accept();
  f.handlers.tokenWillExpire();
  await f.controller.tick();
  assert.equal(f.stats().tokens, 0);
  await f.controller.pause();
  assert.equal(f.stats().disconnected, 0);
  assert.equal(f.controller.state.wanted, false);
  f.controller.hangup();
  f.offer.state = "finished";
  f.live = false;
  await turn();
  await f.controller.tick();
  assert.equal(f.controller.state.offer, null);
  assert.equal(f.controller.state.registered, false);
  assert.equal(f.stats().destroyed, 1);
  f.controller.dispose();
});
test("logout during setup destroys a late device and ignores its callbacks", async () => {
  const f = fixture();
  const gate = deferred<{ id: string; token: string }>();
  f.transport.register = () => gate.promise;
  const start = f.controller.start();
  await turn();
  f.controller.dispose();
  gate.resolve({ id: "reg", token: "PRIVATE" });
  await start;
  assert.equal(f.stats().accepted, 0);
  assert.equal(f.controller.state.registered, false);
  f.controller.activate();
  await f.controller.prepare();
  assert.equal(f.stats().busy, false);
  f.controller.dispose();
});
test("three network failures pause new reception without dropping existing audio", async () => {
  const f = fixture();
  await f.controller.start();
  f.live = true;
  f.handlers.incoming(new f.Media());
  await turn();
  await f.controller.accept();
  f.transport.offer = async () => {
    throw new Error("network");
  };
  await f.controller.tick();
  await f.controller.tick();
  await f.controller.tick();
  assert.equal(f.controller.state.wanted, false);
  assert.equal(f.stats().disconnected, 0);
  assert.equal(f.stats().busy, true);
  f.controller.dispose();
});

test("a late initial heartbeat failure cannot destroy an accepted incoming call", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  const heartbeat = f.transport.heartbeat;
  let count = 0,
    fail!: (error: Error) => void;
  f.transport.heartbeat = async (...args) => {
    if (++count === 2)
      return new Promise((_resolve, reject) => {
        fail = reject;
      });
    return heartbeat(...args);
  };
  const starting = f.controller.start();
  await turn();
  assert.equal(count, 2);
  f.live = true;
  f.handlers.incoming(new f.Media());
  await turn();
  await f.controller.accept();
  assert.equal(f.controller.state.phase, "connected");
  fail(new Error("initial heartbeat timed out"));
  await starting;
  assert.equal(
    f.stats().destroyed,
    0,
    "a control-plane timeout must preserve accepted audio",
  );
  assert.equal(f.controller.state.phase, "connected");
  assert.equal(f.controller.state.local, true);
  assert.equal(
    f.controller.state.wanted,
    false,
    "only future offers should pause",
  );
});

test("a session response begun before a newer call cannot clear its uncertain offer", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.start();
  const stale = deferred<Awaited<ReturnType<typeof f.transport.session>>>();
  f.transport.session = () => stale.promise;
  const checking = f.controller.prepare();
  f.live = true;
  const call = new f.Media();
  f.handlers.incoming(call);
  await turn();
  await f.controller.accept();
  call.emit("disconnect");
  await turn();
  assert.equal(f.controller.state.phase, "checking");
  assert.equal(f.stats().busy, true);
  stale.resolve({
    enabled: true,
    queues: [],
    registration: null,
    active: null,
  });
  await checking;
  assert.equal(
    f.controller.state.offer?.id,
    offerId,
    "an older empty session is not terminal proof for a newer call",
  );
  assert.equal(f.controller.state.phase, "checking");
  assert.equal(f.stats().busy, true);
});

test("idle incoming token renewal updates the existing device and restores lost registration", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.start();
  f.handlers.tokenWillExpire();
  await f.controller.tick();
  assert.equal(f.stats().tokens, 1);
  assert.deepEqual(f.stats().updatedTokens, ["REFRESHED_PRIVATE"]);
  assert.equal(
    f.stats().registrations,
    1,
    "a registered receiver is not registered twice",
  );
  await f.controller.tick();
  assert.equal(f.stats().tokens, 1, "successful renewal clears the due flag");
  f.handlers.unregistered();
  await f.controller.tick();
  assert.equal(f.stats().tokens, 2);
  assert.equal(f.stats().registrations, 2);
  assert.equal(f.controller.state.registered, true);
  assert.equal(f.controller.state.wanted, true);
  assert.equal(f.stats().destroyed, 0);
});

test("idle token network failures pause reception and explicit retry renews without replacing media", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.start();
  const token = f.transport.token;
  let attempts = 0;
  f.transport.token = async () => {
    attempts++;
    throw new Error("synthetic token network failure");
  };
  f.handlers.tokenWillExpire();
  await f.controller.tick();
  assert.equal(
    f.controller.state.wanted,
    true,
    "one transient failure permits retry",
  );
  await f.controller.tick();
  await f.controller.tick();
  assert.equal(attempts, 3);
  assert.equal(f.controller.state.wanted, false);
  assert.match(f.controller.state.error, /perte de connexion/);
  assert.deepEqual(f.stats().updatedTokens, []);
  assert.equal(f.stats().destroyed, 0);
  f.transport.token = token;
  await f.controller.start();
  assert.equal(f.controller.state.wanted, true);
  assert.equal(f.controller.state.registered, true);
  assert.equal(f.stats().tokens, 1);
  assert.equal(f.stats().registrations, 1);
  assert.deepEqual(f.stats().updatedTokens, ["REFRESHED_PRIVATE"]);
});

for (const reactivate of [false, true]) {
  test(`a deferred incoming token after disposal cannot update ${reactivate ? "a new receiver" : "the destroyed receiver"}`, async (t) => {
    const f = fixture();
    t.after(() => f.controller.dispose());
    await f.controller.start();
    const gate = deferred<{ token: string }>();
    let requests = 0;
    f.transport.token = async () => {
      requests++;
      return gate.promise;
    };
    f.handlers.tokenWillExpire();
    const renewing = f.controller.tick();
    await turn();
    assert.equal(requests, 1);
    f.controller.dispose();
    assert.equal(f.stats().destroyed, 1);
    if (reactivate) {
      f.controller.activate();
      await f.controller.start();
      assert.equal(f.controller.state.registered, true);
    }
    const snapshot = f.controller.snapshot();
    const registrations = f.stats().registrations;
    gate.resolve({ token: "LATE_SYNTHETIC_TOKEN" });
    await renewing;
    assert.deepEqual(f.stats().updatedTokens, []);
    assert.equal(f.stats().registrations, registrations);
    assert.strictEqual(
      f.controller.snapshot(),
      snapshot,
      "obsolete response cannot mutate the current lifecycle",
    );
  });
}

test("explicit incoming rejection with a lost acknowledgement retains occupancy until durable terminal proof", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.start();
  f.live = true;
  f.handlers.incoming(new f.Media());
  await turn();
  const choose = f.transport.choose;
  f.transport.choose = async (...args) => {
    await choose(...args);
    throw new Error("synthetic rejection response lost");
  };
  f.controller.reject();
  await turn();
  assert.deepEqual(f.calls, [`${offerId}:reg:false`]);
  assert.equal(f.stats().rejected, 1);
  assert.equal(f.stats().accepted, 0);
  assert.equal(f.controller.state.local, false);
  assert.equal(f.controller.state.phase, "checking");
  assert.equal(f.controller.state.offer?.id, offerId);
  assert.equal(f.stats().busy, true);
  await f.controller.tick();
  assert.equal(
    f.stats().busy,
    true,
    "a browser rejection is not provider terminal confirmation",
  );
  f.offer.state = "finished";
  f.offer.call_state = "finished";
  f.live = false;
  await f.controller.tick();
  assert.equal(f.controller.state.offer, null);
  assert.equal(f.stats().busy, false);
});

test("incoming acceptance failure closes local media and retains the canonical offer until terminal proof", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.start();
  f.live = true;
  f.handlers.incoming(new f.Media());
  await turn();
  f.transport.choose = async () => {
    throw new Error("synthetic acceptance outage");
  };
  await f.controller.accept();
  await turn();
  assert.equal(f.stats().accepted, 0);
  assert.equal(f.stats().rejected, 1);
  assert.equal(f.controller.state.local, false);
  assert.equal(f.controller.state.phase, "checking");
  assert.match(f.controller.state.error, /n’a pas pu être accepté/);
  assert.equal(f.controller.state.offer?.id, offerId);
  assert.equal(f.stats().busy, true);
  f.offer.state = "finished";
  f.offer.call_state = "finished";
  f.live = false;
  await f.controller.tick();
  assert.equal(f.controller.state.offer, null);
  assert.equal(f.stats().busy, false);
});
