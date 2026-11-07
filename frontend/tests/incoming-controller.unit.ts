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
    tokens = 0;
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
        register: async () => h.registered(),
        updateToken: () => {},
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
