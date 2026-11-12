import { test } from "node:test";
import assert from "node:assert/strict";
import { setImmediate } from "node:timers/promises";
import { PhoneController } from "../src/phone-controller.ts";
import type {
  Intent,
  MediaCall,
  MediaDevice,
  Session,
  Transport,
  AutomaticTransport,
  Dialer,
} from "../src/phone-controller.ts";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
class FakeCall implements MediaCall {
  listeners = new Map<string, (error?: { code?: number }) => void>();
  disconnected = 0;
  on(event: string, listener: (error?: { code?: number }) => void) {
    this.listeners.set(event, listener);
  }
  emit(event: string, error?: { code?: number }) {
    this.listeners.get(event)?.(error);
  }
  disconnect() {
    ++this.disconnected;
  }
}
class FakeDevice implements MediaDevice {
  call = new FakeCall();
  destroyed = 0;
  connections: string[] = [];
  inputs: string[] = [];
  error: (error?: { code?: number }, call?: MediaCall) => void = () => {};
  onError(listener: (error?: { code?: number }, call?: MediaCall) => void) {
    this.error = listener;
  }
  async connect(id: string, input: string) {
    this.connections.push(id);
    this.inputs.push(input);
    return this.call;
  }
  destroy() {
    ++this.destroyed;
  }
}
function fixture(automatic?: AutomaticTransport) {
  const session: Session = {
    enabled: true,
    destination: "+14165550101",
    max_duration_seconds: 180,
    active: null,
  };
  const rows = new Map<string, Intent>();
  const device = new FakeDevice();
  let reservations = 0,
    creations = 0;
  const api: Transport = {
    session: async () => ({ ...session }),
    reserve: async (id) => {
      ++reservations;
      const intent = {
        id,
        state: "reserved",
        outcome: null,
        owned_session: true,
      };
      rows.set(id, intent);
      return { intent, token: "synthetic-token" };
    },
    history: async (id) => {
      const intent = rows.get(id);
      if (!intent) throw { status: 404 };
      return { intent };
    },
    cancel: async (id) => {
      const intent = rows.get(id);
      if (!intent) throw { status: 404 };
      if (intent.state === "cancelled") return intent;
      if (intent.state !== "reserved") throw { status: 409 };
      const result = { ...intent, state: "cancelled" };
      rows.set(id, result);
      return result;
    },
  };
  const create = async () => {
    ++creations;
    return device;
  };
  const controller = new PhoneController(api, create, automatic);
  return {
    session,
    rows,
    api,
    create,
    controller,
    device,
    reservations: () => reservations,
    creations: () => creations,
  };
}

test("aucun jeton ni média avant activation et clic explicite", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  f.session.enabled = false;
  await f.controller.start("", "+14165550101");
  await f.controller.refresh();
  await f.controller.start("", "+14165550101");
  assert.equal(f.reservations(), 0);
  assert.equal(f.creations(), 0);
});
test("double clic : une réservation, un SDK, transitions et fin serveur obligatoires", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await Promise.all([
    f.controller.start("", "+14165550101"),
    f.controller.start("", "+14165550101"),
  ]);
  assert.equal(f.reservations(), 1);
  assert.equal(f.device.connections.length, 1);
  assert.equal(
    JSON.stringify(f.controller.state).includes("synthetic-token"),
    false,
  );
  const id = f.device.connections[0];
  f.rows.set(id, { id, state: "answered", outcome: null });
  f.device.call.emit("ringing");
  assert.equal(f.controller.state.phase, "ringing");
  f.device.call.emit("accept");
  assert.equal(f.controller.state.phase, "connected");
  f.device.call.emit("reconnecting");
  assert.equal(f.controller.state.phase, "reconnecting");
  await f.controller.refresh();
  assert.equal(f.controller.state.phase, "reconnecting");
  f.device.call.emit("reconnected");
  assert.equal(f.controller.state.phase, "connected");
  f.controller.hangup();
  await setImmediate();
  assert.equal(f.device.destroyed, 1);
  assert.equal(f.device.call.disconnected, 1);
  await f.controller.start("", "+14165550101");
  assert.equal(f.reservations(), 1);
  f.rows.set(id, { id, state: "finished", outcome: "completed" });
  await f.controller.refresh();
  assert.equal(f.controller.state.phase, "idle");
  assert.equal(f.controller.state.result, "completed");
});
test("rechargement avec appel actif : lecture seule, aucune reconnexion ni relance", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  const intent = {
    id: crypto.randomUUID(),
    state: "answered",
    outcome: null,
    owned_session: false,
  };
  f.session.active = intent;
  f.rows.set(intent.id, intent);
  await f.controller.refresh();
  await f.controller.refresh();
  await f.controller.start("", "+14165550101");
  assert.equal(f.controller.state.phase, "checking");
  assert.equal(f.controller.state.local, false);
  assert.equal(f.controller.state.intent?.owned_session, false);
  assert.equal(f.reservations(), 0);
  assert.equal(f.creations(), 0);
});
test("annulation d’une préparation récupérée et liée à la session", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  const intent = {
    id: crypto.randomUUID(),
    state: "reserved",
    outcome: null,
    owned_session: true,
  };
  f.session.active = intent;
  f.rows.set(intent.id, intent);
  await f.controller.refresh();
  await f.controller.cancelPreparation();
  assert.equal(f.controller.state.phase, "idle");
  assert.equal(f.rows.get(intent.id)?.state, "cancelled");
  assert.equal(f.creations(), 0);
});
test("raccrochage pendant le chargement SDK : fermeture tardive, aucune connexion", async (t) => {
  const f = fixture(),
    loaded = deferred<MediaDevice>();
  const controller = new PhoneController(f.api, () => loaded.promise);
  t.after(() => controller.dispose());
  await controller.refresh();
  const starting = controller.start("", "+14165550101");
  await setImmediate();
  controller.hangup();
  loaded.resolve(f.device);
  await starting;
  assert.equal(f.device.connections.length, 0);
  assert.equal(f.device.destroyed, 1);
  await controller.refresh();
  await controller.cancelPreparation();
  assert.equal(controller.state.phase, "idle");
});
test("raccrochage avant résolution de connect : le média tardif est immédiatement fermé", async (t) => {
  const f = fixture(),
    connected = deferred<MediaCall>();
  t.after(() => f.controller.dispose());
  f.device.connect = async (id) => {
    f.device.connections.push(id);
    return connected.promise;
  };
  await f.controller.refresh();
  const starting = f.controller.start("", "+14165550101");
  await setImmediate();
  const id = f.device.connections[0];
  f.rows.set(id, { id, state: "authorized", outcome: null });
  f.controller.hangup();
  connected.resolve(f.device.call);
  await starting;
  assert.equal(f.device.call.disconnected, 1);
  assert.ok(f.device.destroyed >= 1);
  await f.controller.refresh();
  await f.controller.start("", "+14165550101");
  assert.equal(f.reservations(), 1);
});
test("déconnexion de session pendant une réservation : aucun SDK même après réponse tardive", async () => {
  const f = fixture(),
    reserved = deferred<{ intent: Intent; token: string }>();
  let requestSignal: AbortSignal | undefined;
  f.api.reserve = (_id, signal) => {
    requestSignal = signal;
    return reserved.promise;
  };
  await f.controller.refresh();
  const starting = f.controller.start("", "+14165550101");
  f.controller.dispose();
  assert.equal(requestSignal?.aborted, true);
  const before = f.controller.state;
  reserved.resolve({
    intent: { id: crypto.randomUUID(), state: "reserved", outcome: null },
    token: "synthetic-token",
  });
  await starting;
  assert.equal(f.creations(), 0);
  assert.equal(f.controller.state, before);
});
test("perte réseau après connexion : résultat inconnu conserve le blocage", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.start("", "+14165550101");
  f.api.session = async () => {
    throw new Error("offline");
  };
  f.device.call.emit("error");
  await setImmediate();
  assert.equal(f.controller.state.phase, "checking");
  assert.equal(f.device.destroyed, 1);
  await f.controller.start("", "+14165550101");
  assert.equal(f.reservations(), 1);
  assert.ok(f.controller.state.error.includes("ne peut pas être confirmé"));
});
test("fin serveur avant résolution de connect et appel suivant : ancien résultat sans effet", async (t) => {
  const f = fixture(),
    connected = deferred<MediaCall>();
  t.after(() => f.controller.dispose());
  f.device.connect = async (id) => {
    f.device.connections.push(id);
    return connected.promise;
  };
  await f.controller.refresh();
  const oldStart = f.controller.start("", "+14165550101");
  await setImmediate();
  const id = f.device.connections[0];
  f.rows.set(id, { id, state: "finished", outcome: "failed" });
  await f.controller.refresh();
  assert.equal(f.controller.state.phase, "idle");
  connected.resolve(f.device.call);
  await oldStart;
  assert.equal(f.device.call.disconnected, 1);
  assert.equal(f.controller.state.phase, "idle");
});
test("échec avant connect : annulation confirmée, pas de fuite de message fournisseur", async (t) => {
  const f = fixture();
  const controller = new PhoneController(f.api, async () => {
    throw new Error("secret must not appear");
  });
  t.after(() => controller.dispose());
  await controller.refresh();
  await controller.start("", "+14165550101");
  assert.equal(controller.state.phase, "idle");
  assert.equal(controller.state.result, "cancelled");
  assert.ok(controller.state.error.includes("n’a pas pu démarrer"));
  assert.equal(JSON.stringify(controller.state).includes("secret"), false);
});

test("plafond de préparation : annulation atomique puis fermeture du média tardif", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = fixture(),
    connected = deferred<MediaCall>();
  t.after(() => f.controller.dispose());
  f.device.connect = async (id) => {
    f.device.connections.push(id);
    return connected.promise;
  };
  await f.controller.refresh();
  const starting = f.controller.start("", "+14165550101");
  await setImmediate();
  t.mock.timers.tick(45_000);
  await setImmediate();
  assert.equal(f.rows.get(f.device.connections[0])?.state, "cancelled");
  assert.equal(f.controller.state.phase, "idle");
  connected.resolve(f.device.call);
  await starting;
  assert.equal(f.device.call.disconnected, 1);
});

test("restauration de page après fermeture média : état relu sans nouvel appel", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.start("", "+14165550101");
  const id = f.device.connections[0];
  f.rows.set(id, { id, state: "answered", outcome: null });
  f.controller.dispose();
  f.controller.activate();
  await f.controller.refresh();
  assert.equal(f.controller.state.phase, "checking");
  assert.equal(f.controller.state.local, false);
  assert.equal(f.reservations(), 1);
  assert.equal(f.creations(), 1);
  assert.equal(f.device.destroyed, 1);
});

test("un autre onglet réserve entre la vérification et le clic : récupération de son appel", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  const active = {
    id: crypto.randomUUID(),
    state: "answered",
    outcome: null,
    owned_session: false,
  };
  f.session.active = active;
  f.rows.set(active.id, active);
  f.api.reserve = async () => {
    throw { status: 409 };
  };
  await f.controller.start("", "+14165550101");
  await f.controller.refresh();
  assert.equal(f.controller.state.intent?.id, active.id);
  assert.equal(f.controller.state.phase, "checking");
  assert.equal(f.creations(), 0);
});

test("numéro saisi : normalisation avant réservation et brouillon conservé", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  const reserve = f.api.reserve;
  let sent = "";
  f.api.reserve = (id, signal, destination) => {
    sent = destination;
    return reserve(id, signal, destination);
  };
  f.controller.setDialNumber("+1 (416) 555-0101");
  await f.controller.refresh();
  assert.equal(f.controller.state.dialNumber, "+1 (416) 555-0101");
  await f.controller.start();
  assert.equal(sent, "+14165550101");
  assert.equal(f.controller.state.destination, sent);
  f.controller.setDialNumber("+442079460123");
  assert.equal(f.controller.state.dialNumber, "+1 (416) 555-0101");
});

test("numéro absent ou ambigu : aucune réservation ni autorisation microphone", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  for (const value of [
    "",
    "4165550101",
    "+14165550101 ext 2",
    "+14165550101\n",
    "++14165550101",
    "sip:test@example.invalid",
  ]) {
    f.controller.setDialNumber(value);
    await f.controller.start();
    assert.equal(f.controller.state.phase, "idle");
    assert.ok(f.controller.state.error);
  }
  assert.equal(f.reservations(), 0);
  assert.equal(f.creations(), 0);
});

test("numéro refusé par le serveur : correction immédiate, aucune substitution", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  let cancellations = 0;
  f.api.reserve = async () => {
    throw Object.assign(
      new Error("Les appels vers ce numéro ne sont pas encore activés."),
      { status: 400 },
    );
  };
  f.api.cancel = async () => {
    cancellations++;
    throw { status: 404 };
  };
  await f.controller.refresh();
  f.controller.setDialNumber("+442079460123");
  await f.controller.start();
  assert.equal(f.controller.state.phase, "idle");
  assert.equal(f.controller.state.dialNumber, "+442079460123");
  assert.match(f.controller.state.error, /ce numéro/);
  assert.equal(f.creations(), 0);
  assert.equal(cancellations, 0);
});

test("refus de réservation : message exact, aucune annulation fictive et tentative suivante possible", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  const original = f.api.reserve;
  let cancellations = 0;
  f.api.cancel = async () => {
    cancellations++;
    throw { status: 404 };
  };
  await f.controller.refresh();
  for (const status of [403, 404, 409, 422, 429]) {
    f.api.reserve = async () => {
      throw Object.assign(new Error(`Refus précis ${status}`), { status });
    };
    await f.controller.start("", "+14165550101");
    assert.equal(f.controller.state.phase, "idle");
    assert.equal(f.controller.state.error, `Refus précis ${status}`);
    assert.equal(f.creations(), 0);
  }
  assert.equal(cancellations, 0);
  f.api.reserve = original;
  await f.controller.start("", "+14165550101");
  assert.equal(f.creations(), 1);
});

test("saisie libre : la campagne automatique sélectionnée ne modifie pas l’appel manuel", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  f.controller.setCampaignId("automatic-campaign");
  const reserve = f.api.reserve;
  let campaign: string | undefined;
  f.api.reserve = async (id, signal, destination, source) => {
    campaign = source;
    return reserve(id, signal, destination, source);
  };
  await f.controller.start("", "+14165550101");
  assert.equal(campaign, undefined);
});

test("durée normale et microphone conservé : aucun raccrochage après le plafond du mode de validation", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = fixture();
  f.session.max_duration_seconds = 600;
  await f.controller.refresh();
  f.controller.setDialNumber("+14165550101");
  f.controller.setInputDevice("selected-headset");
  await f.controller.start();
  assert.deepEqual(f.device.inputs, ["selected-headset"]);
  t.mock.timers.tick(210_000);
  assert.equal(f.device.call.disconnected, 0);
  t.mock.timers.tick(480_000);
  assert.equal(f.device.call.disconnected, 1);
  f.controller.dispose();
});

test("appel normal : trente minutes autorisées, dix minutes ne coupent pas", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = fixture();
  t.after(() => f.controller.dispose());
  f.session.max_duration_seconds = 1800;
  await f.controller.refresh();
  assert.equal(f.controller.state.maxDurationSeconds, 1800);
  await f.controller.start("", "+14165550101");
  t.mock.timers.tick(60_000); // Long ringing must not consume conversation time.
  f.device.call.emit("accept");
  t.mock.timers.tick(11 * 60 * 1000);
  assert.equal(f.controller.state.phase, "connected");
  assert.equal(f.device.call.disconnected, 0);
  t.mock.timers.tick(19 * 60 * 1000);
  assert.equal(f.device.call.disconnected, 0);
  t.mock.timers.tick(30_000);
  assert.equal(f.device.call.disconnected, 1);
});

test("fin du média pendant une actualisation : résultat serveur repris sans prochain sondage", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.start("", "+14165550101");
  const id = f.device.connections[0];
  const gate = deferred<Session>();
  f.api.session = () => gate.promise;
  const stale = f.controller.refresh();
  f.rows.set(id, { id, state: "finished", outcome: "completed" });
  f.device.call.emit("disconnect");
  f.api.session = async () => ({ ...f.session });
  gate.resolve({ ...f.session });
  await stale;
  await setImmediate();
  assert.equal(f.controller.state.phase, "idle");
  assert.equal(f.controller.state.result, "completed");
});

function automaticFixture() {
  let row: Dialer = {
    mode: "stopped",
    generation: 0,
    campaign_id: null,
    browser_id: null,
  };
  let nextGate: Promise<void> | null = null;
  let heartbeatFailure = false;
  let heartbeatCount = 0;
  let idle = false;
  let nextCount = 0;
  let f!: ReturnType<typeof fixture>;
  const automatic: AutomaticTransport = {
    session: async () => ({ dialer: { ...row }, enabled: true }),
    control: async (body) => {
      const action = String(body.action);
      if (action === "start")
        row = {
          mode: "running",
          generation: row.generation + 1,
          campaign_id: String(body.campaign_id),
          browser_id: String(body.browser_id),
        };
      else if (action === "hold")
        row = {
          ...row,
          mode: "booking",
          generation: row.generation + 1,
          hold_token: String(body.hold_token),
        };
      else if (action === "release")
        row = {
          ...row,
          mode: "running",
          generation: row.generation + 1,
          hold_token: null,
        };
      else {
        row = {
          ...row,
          mode: action === "stop" ? "stopped" : "paused",
          generation: row.generation + 1,
          hold_token: null,
        };
        for (const [id, intent] of f.rows)
          if (intent.state === "reserved")
            f.rows.set(id, { ...intent, state: "cancelled" });
      }
      return { dialer: { ...row } };
    },
    heartbeat: async () => {
      heartbeatCount += 1;
      if (heartbeatFailure) throw new Error("offline");
      return { dialer: { ...row } };
    },
    next: async (body, signal) => {
      ++nextCount;
      if (idle) return { idle: "empty", dialer: { ...row } };
      const reserved = await f.api.reserve(body.id, signal, "+14165550101");
      const result = {
        ...reserved,
        intent: {
          ...reserved.intent,
          destination: "+14165550101",
          automatic: true,
        },
        dialer: { ...row },
      };
      f.rows.set(body.id, result.intent);
      if (nextGate) await nextGate;
      return result;
    },
  };
  f = fixture(automatic);
  return {
    ...f,
    automatic,
    get nextCount() {
      return nextCount;
    },
    get heartbeatCount() {
      return heartbeatCount;
    },
    setGate: (value: Promise<void> | null) => {
      nextGate = value;
    },
    failHeartbeat: () => {
      heartbeatFailure = true;
    },
    recoverHeartbeat: () => {
      heartbeatFailure = false;
    },
    empty: () => {
      idle = true;
    },
    foreign: () => {
      row = {
        mode: "running",
        generation: 3,
        campaign_id: "campaign",
        browser_id: "another-browser",
      };
    },
  };
}

for (const source of ["call", "device-call"] as const)
  for (const outcome of ["no-answer", "busy", "failed", "completed"])
    test(`composeur : erreur ${source}, résultat serveur ${outcome}, poursuit après dix secondes`, async (t) => {
      let now = 0;
      t.mock.method(performance, "now", () => now);
      const f = automaticFixture();
      t.after(() => f.controller.dispose());
      await f.controller.refresh();
      await f.controller.startAutomatic("campaign");
      await f.controller.automaticTick();
      const id = f.device.connections[0];
      // The media error can arrive before the provider's terminal webhook.
      f.rows.set(id, { ...f.rows.get(id)!, state: "ringing" });
      if (source === "call") f.device.call.emit("error", { code: 31005 });
      else f.device.error({ code: 31005 }, f.device.call);
      await setImmediate();
      assert.equal(f.controller.state.automaticRunning, true);
      assert.equal(f.controller.state.automatic?.mode, "running");
      now = 60_000;
      await f.controller.automaticTick();
      assert.equal(f.nextCount, 1, "unconfirmed media failure cannot redial");
      assert.equal(f.controller.state.automaticNextAt, null);
      f.rows.set(id, { ...f.rows.get(id)!, state: "finished", outcome });
      await f.controller.refresh();
      assert.equal(f.controller.state.automaticNextAt, 70_000);
      now = 69_999;
      await f.controller.automaticTick();
      assert.equal(f.nextCount, 1);
      now = 70_000;
      await f.controller.automaticTick();
      assert.equal(f.nextCount, 2);
    });

for (const code of [31480, 31486, 31603])
  test(`composeur : résultat opérateur ${code} sans référence Call poursuit après confirmation serveur`, async (t) => {
    let now = 0;
    t.mock.method(performance, "now", () => now);
    const f = automaticFixture();
    t.after(() => f.controller.dispose());
    await f.controller.refresh();
    await f.controller.startAutomatic("campaign");
    await f.controller.automaticTick();
    const id = f.device.connections[0];
    f.rows.set(id, { ...f.rows.get(id)!, state: "ringing" });
    // SDK Device._findCall only searches incoming _calls, not _activeCall.
    f.device.error({ code });
    await setImmediate();
    assert.equal(f.controller.state.automaticRunning, true);
    now = 60_000;
    await f.controller.automaticTick();
    assert.equal(f.nextCount, 1);
    assert.equal(f.controller.state.automaticNextAt, null);
    f.rows.set(id, { ...f.rows.get(id)!, state: "finished", outcome: "busy" });
    await f.controller.refresh();
    assert.equal(f.controller.state.automaticNextAt, 70_000);
    now = 69_999;
    await f.controller.automaticTick();
    assert.equal(f.nextCount, 1);
    now = 70_000;
    await f.controller.automaticTick();
    assert.equal(f.nextCount, 2);
  });

for (const status of [0, 429, 500, 502, 503, 504])
  test(`composeur : échec temporaire next ${status}, nouvelle tentative avec le même identifiant`, async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const f = automaticFixture();
    t.after(() => f.controller.dispose());
    const next = f.automatic.next;
    const requests: string[] = [];
    f.automatic.next = async (body, signal) => {
      requests.push(body.id);
      if (requests.length === 1)
        throw Object.assign(new Error("temporary"), { status });
      return next(body, signal);
    };
    await f.controller.refresh();
    await f.controller.startAutomatic("campaign");
    const pending = f.controller.automaticTick();
    await setImmediate();
    assert.equal(f.controller.state.automaticRunning, true);
    assert.equal(f.device.connections.length, 0);
    t.mock.timers.tick(2_000);
    await pending;
    assert.equal(requests.length, 2);
    assert.equal(requests[0], requests[1]);
    assert.equal(f.device.connections.length, 1);
    assert.equal(f.controller.state.automatic?.mode, "running");
  });

test("composeur : réponse perdue après réservation, réutilise la même réservation une seule fois", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  const next = f.automatic.next;
  const requests: string[] = [];
  let committed: Awaited<ReturnType<typeof next>> | null = null;
  f.automatic.next = async (body, signal) => {
    requests.push(body.id);
    if (!committed) {
      committed = await next(body, signal);
      throw Object.assign(new Error("response lost"), { status: 0 });
    }
    assert.equal(body.id, committed.intent!.id);
    return committed;
  };
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  const pending = f.controller.automaticTick();
  await setImmediate();
  assert.equal(f.controller.state.automaticRunning, true);
  assert.equal(f.device.connections.length, 0);
  t.mock.timers.tick(2_000);
  await pending;
  assert.deepEqual(requests, [requests[0], requests[0]]);
  assert.equal(f.rows.size, 1);
  assert.equal(f.nextCount, 1);
  assert.equal(f.device.connections.length, 1);
});

test("composeur : échec serveur persistant, trois demandes identiques puis pause sans média", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  const requests: string[] = [];
  f.automatic.next = async (body) => {
    requests.push(body.id);
    throw Object.assign(new Error("temporary"), { status: 500 });
  };
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  const pending = f.controller.automaticTick();
  await setImmediate();
  t.mock.timers.tick(2_000);
  await setImmediate();
  t.mock.timers.tick(4_000);
  await pending;
  assert.equal(requests.length, 3);
  assert.equal(new Set(requests).size, 1);
  assert.equal(f.device.connections.length, 0);
  assert.equal(f.controller.state.automatic?.mode, "paused");
  t.mock.timers.tick(60_000);
  await f.controller.automaticTick();
  assert.equal(requests.length, 3);
});

for (const status of [400, 401, 403, 404, 409, 422])
  test(`composeur : refus next ${status}, aucune répétition ni création média`, async (t) => {
    const f = automaticFixture();
    t.after(() => f.controller.dispose());
    let requests = 0;
    f.automatic.next = async () => {
      requests++;
      throw Object.assign(new Error("denied"), { status });
    };
    await f.controller.refresh();
    await f.controller.startAutomatic("campaign");
    await f.controller.automaticTick();
    assert.equal(requests, 1);
    assert.equal(f.device.connections.length, 0);
    assert.equal(f.controller.state.automaticRunning, false);
  });

for (const action of ["pause", "stop", "hold", "dispose"] as const)
  test(`composeur : ${action} pendant une récupération interdit la répétition tardive`, async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const f = automaticFixture();
    t.after(() => f.controller.dispose());
    let requests = 0;
    f.automatic.next = async () => {
      requests++;
      throw Object.assign(new Error("temporary"), { status: 500 });
    };
    await f.controller.refresh();
    await f.controller.startAutomatic("campaign");
    const pending = f.controller.automaticTick();
    await setImmediate();
    if (action === "dispose") f.controller.dispose();
    else if (action === "hold") await f.controller.beginBooking("campaign");
    else await f.controller.pauseAutomatic(action === "stop");
    t.mock.timers.tick(2_000);
    await pending;
    assert.equal(requests, 1);
    assert.equal(f.device.connections.length, 0);
    if (action !== "dispose") {
      assert.equal(f.controller.state.automaticRunning, false);
      assert.equal(
        f.controller.state.automatic?.mode,
        action === "hold"
          ? "booking"
          : action === "stop"
            ? "stopped"
            : "paused",
      );
    }
  });

for (const action of ["pause", "stop", "hold"] as const)
  test(`composeur : refus tardif next ne remplace pas ${action}`, async (t) => {
    const f = automaticFixture();
    t.after(() => f.controller.dispose());
    const response = deferred<never>();
    f.automatic.next = async () => response.promise;
    await f.controller.refresh();
    await f.controller.startAutomatic("campaign");
    const pending = f.controller.automaticTick();
    await setImmediate();
    if (action === "hold") await f.controller.beginBooking("campaign");
    else await f.controller.pauseAutomatic(action === "stop");
    const mode = f.controller.state.automatic?.mode;
    response.reject(
      Object.assign(new Error("old generation"), { status: 409 }),
    );
    await pending;
    assert.equal(f.controller.state.automatic?.mode, mode);
    assert.equal(f.device.connections.length, 0);
  });

for (const code of [31000, 31005, 31009, 53000, 53405])
  test(`composeur : erreur globale ambiguë ${code} conserve la pause`, async (t) => {
    const f = automaticFixture();
    t.after(() => f.controller.dispose());
    await f.controller.refresh();
    await f.controller.startAutomatic("campaign");
    await f.controller.automaticTick();
    f.device.error({ code });
    await setImmediate();
    assert.equal(f.controller.state.automaticRunning, false);
    assert.equal(f.controller.state.automatic?.mode, "paused");
    assert.equal(f.nextCount, 1);
  });

test("composeur : diagnostic SDK borné sans texte privé, pause manuelle sans cause inventée", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  const control = f.automatic.control;
  const pauses: Record<string, unknown>[] = [];
  f.automatic.control = async (body, signal) => {
    if (body.action === "pause") pauses.push(body);
    return control(body, signal);
  };
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  f.device.error(
    Object.assign({ code: 53000 }, { message: "PRIVATE_NUMBER_OR_SECRET" }),
  );
  await setImmediate();
  assert.equal(pauses[0].pause_cause, "sdk_device");
  assert.equal(pauses[0].failure_code, 53000);
  assert.equal(
    JSON.stringify(pauses).includes("PRIVATE_NUMBER_OR_SECRET"),
    false,
  );
  await f.controller.pauseAutomatic();
  assert.equal("pause_cause" in pauses[1], false);
  assert.equal("failure_code" in pauses[1], false);
});

test("composeur : retour à une ancienne API sans diagnostic, pause toujours confirmée", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  const control = f.automatic.control;
  const requests: Record<string, unknown>[] = [];
  f.automatic.control = async (body, signal) => {
    if (body.action === "pause") {
      requests.push(body);
      if ("pause_cause" in body)
        throw Object.assign(new Error("older schema"), { status: 422 });
    }
    return control(body, signal);
  };
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  f.device.error({ code: 53000 });
  await setImmediate();
  assert.equal(requests.length, 2);
  assert.equal(requests[0].pause_cause, "sdk_device");
  assert.equal("pause_cause" in requests[1], false);
  assert.equal(requests[0].generation, requests[1].generation);
  assert.equal(f.controller.state.automatic?.mode, "paused");
});

test("composeur : une validation ancienne tardive ne remplace pas un nouvel arrêt", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  const control = f.automatic.control;
  const response = deferred<never>();
  let pauses = 0;
  f.automatic.control = async (body, signal) => {
    if (body.action === "pause") {
      pauses++;
      return response.promise;
    }
    return control(body, signal);
  };
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  f.device.error({ code: 53000 });
  await f.controller.pauseAutomatic(true);
  response.reject(Object.assign(new Error("older schema"), { status: 422 }));
  await setImmediate();
  assert.equal(pauses, 1);
  assert.equal(f.controller.state.automatic?.mode, "stopped");
});

test("composeur : erreurs d’appel dupliquées et ancien téléphone ne perturbent pas l’appel suivant", async (t) => {
  let now = 0;
  t.mock.method(performance, "now", () => now);
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  const id = f.device.connections[0];
  const oldError = f.device.error;
  const oldCall = f.device.call;
  f.rows.set(id, {
    ...f.rows.get(id)!,
    state: "finished",
    outcome: "no-answer",
  });
  oldCall.emit("error", { code: 31005 });
  oldError({ code: 31005 }, oldCall);
  await setImmediate();
  assert.equal(f.controller.state.automaticNextAt, 10_000);
  now = 10_000;
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 2);
  oldError({ code: 31205 });
  assert.equal(f.controller.state.automaticRunning, true);
  assert.equal(f.controller.state.phase, "connecting");
  assert.equal(f.nextCount, 2);
});

test("composeur : erreur d’appel puis serveur indisponible interdit un départ sans résultat vérifié", async (t) => {
  let now = 0;
  t.mock.method(performance, "now", () => now);
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  const id = f.device.connections[0];
  const history = f.api.history;
  f.api.history = async () => {
    throw new Error("offline");
  };
  f.device.call.emit("error", { code: 31005 });
  await setImmediate();
  now = 60_000;
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 1);
  assert.equal(f.controller.state.phase, "checking");
  assert.equal(f.controller.state.automaticNextAt, null);
  f.api.history = history;
  f.rows.set(id, {
    ...f.rows.get(id)!,
    state: "finished",
    outcome: "no-answer",
  });
  await f.controller.refresh();
  assert.equal(f.controller.state.automaticNextAt, 70_000);
  now = 70_000;
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 2);
});

for (const action of ["pause", "stop", "hold", "presence-loss"] as const)
  test(`composeur : erreur d’appel puis ${action}, un résultat tardif ne réarme jamais`, async (t) => {
    let now = 0;
    t.mock.method(performance, "now", () => now);
    const f = automaticFixture();
    t.after(() => f.controller.dispose());
    await f.controller.refresh();
    await f.controller.startAutomatic("campaign");
    await f.controller.automaticTick();
    const id = f.device.connections[0];
    f.rows.set(id, { ...f.rows.get(id)!, state: "ringing" });
    f.device.call.emit("error", { code: 31005 });
    await setImmediate();
    if (action === "hold") await f.controller.beginBooking("campaign");
    else if (action === "presence-loss") {
      f.failHeartbeat();
      for (let i = 0; i < 3; i++) await f.controller.automaticTick();
      f.recoverHeartbeat();
    } else await f.controller.pauseAutomatic(action === "stop");
    f.rows.set(id, {
      ...f.rows.get(id)!,
      state: "finished",
      outcome: "no-answer",
    });
    await f.controller.refresh();
    now = 60_000;
    await f.controller.automaticTick();
    assert.equal(f.nextCount, 1);
    assert.equal(f.controller.state.automaticRunning, false);
  });

for (const action of ["pause", "stop", "hold"] as const)
  test(`composeur : erreur audio tardive préserve ${action} et ne réarme pas après libération`, async (t) => {
    let now = 0;
    t.mock.method(performance, "now", () => now);
    const f = automaticFixture();
    t.after(() => f.controller.dispose());
    await f.controller.refresh();
    await f.controller.startAutomatic("campaign");
    await f.controller.automaticTick();
    const id = f.device.connections[0];
    f.rows.set(id, { ...f.rows.get(id)!, state: "ringing" });
    f.device.call.emit("disconnect");
    await setImmediate();
    const hold =
      action === "hold" ? await f.controller.beginBooking("campaign") : null;
    if (action !== "hold") await f.controller.pauseAutomatic(action === "stop");
    const mode = f.controller.state.automatic?.mode;
    f.device.call.emit("error", { code: 53405 });
    await setImmediate();
    assert.equal(f.controller.state.automatic?.mode, mode);
    f.rows.set(id, {
      ...f.rows.get(id)!,
      state: "finished",
      outcome: "completed",
    });
    await f.controller.refresh();
    if (hold) await f.controller.endBooking(hold);
    now = 60_000;
    await f.controller.automaticTick();
    assert.equal(f.controller.state.automaticRunning, false);
    assert.equal(f.nextCount, 1);
  });

for (const source of ["call", "device-call"] as const)
  for (const code of [
    20101, 20104, 20151, 31001, 31102, 31201, 31202, 31204, 31205, 31206, 31401,
    31402, 53000, 53001, 53405,
  ])
    test(`composeur : erreur persistante ${code} sur ${source} conserve la pause`, async (t) => {
      let now = 0;
      t.mock.method(performance, "now", () => now);
      const f = automaticFixture();
      t.after(() => f.controller.dispose());
      await f.controller.refresh();
      await f.controller.startAutomatic("campaign");
      await f.controller.automaticTick();
      const id = f.device.connections[0];
      f.rows.set(id, {
        ...f.rows.get(id)!,
        state: "finished",
        outcome: "no-answer",
      });
      if (source === "call") f.device.call.emit("error", { code });
      else f.device.error({ code }, f.device.call);
      await setImmediate();
      now = 60_000;
      await f.controller.automaticTick();
      assert.equal(f.controller.state.automaticRunning, false);
      assert.equal(f.controller.state.automatic?.mode, "paused");
      assert.equal(f.nextCount, 1);
    });

test("composeur : une erreur fatale émise par Call et Device ne demande qu’une seule pause", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  const control = f.automatic.control;
  let pauses = 0;
  f.automatic.control = async (body, signal) => {
    if (body.action === "pause") pauses++;
    return control(body, signal);
  };
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  const oldError = f.device.error;
  f.device.call.emit("disconnect");
  f.device.call.emit("error", { code: 53405 });
  oldError({ code: 53405 }, f.device.call);
  await setImmediate();
  assert.equal(pauses, 1);
  assert.equal(f.controller.state.automaticRunning, false);
});

test("composeur : un ancien téléphone détruit ne modifie pas la session réactivée", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  const control = f.automatic.control;
  let pauses = 0;
  f.automatic.control = async (body, signal) => {
    if (body.action === "pause") pauses++;
    return control(body, signal);
  };
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  const oldError = f.device.error;
  f.controller.dispose();
  oldError({ code: 53405 });
  f.controller.activate();
  oldError({ code: 53405 });
  await setImmediate();
  assert.equal(pauses, 0);
});

for (const source of ["call", "device-call"] as const)
  test(`composeur : déconnexion puis erreur audio ${source} du même appel conserve la pause`, async (t) => {
    let now = 0;
    t.mock.method(performance, "now", () => now);
    const f = automaticFixture();
    t.after(() => f.controller.dispose());
    await f.controller.refresh();
    await f.controller.startAutomatic("campaign");
    await f.controller.automaticTick();
    const id = f.device.connections[0];
    const oldError = f.device.error;
    f.rows.set(id, {
      ...f.rows.get(id)!,
      state: "finished",
      outcome: "completed",
    });
    // SDK PeerConnection.close emits disconnect before the fatal media error.
    f.device.call.emit("disconnect");
    if (source === "call") f.device.call.emit("error", { code: 53405 });
    else oldError({ code: 53405 }, f.device.call);
    await setImmediate();
    now = 60_000;
    await f.controller.automaticTick();
    assert.equal(f.controller.state.automaticRunning, false);
    assert.equal(f.controller.state.automatic?.mode, "paused");
    assert.equal(f.nextCount, 1);
  });

test("composeur : erreur globale du téléphone conserve la pause même avec un résultat sans réponse", async (t) => {
  let now = 0;
  t.mock.method(performance, "now", () => now);
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  const id = f.device.connections[0];
  f.rows.set(id, {
    ...f.rows.get(id)!,
    state: "finished",
    outcome: "no-answer",
  });
  f.device.error();
  await setImmediate();
  now = 60_000;
  await f.controller.automaticTick();
  assert.equal(f.controller.state.automaticRunning, false);
  assert.equal(f.nextCount, 1);
});

test("composeur : dix secondes complètes après la fin serveur, jamais après le seul média", async (t) => {
  let now = 0;
  t.mock.method(performance, "now", () => now);
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.refreshAutomatic();
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 0);
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 1);
  assert.equal(f.device.connections.length, 1);
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 1);
  const id = f.device.connections[0];
  f.device.call.emit("disconnect");
  await setImmediate();
  now = 60_000;
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 1);
  assert.equal(f.controller.state.automaticNextAt, null);
  f.rows.set(id, {
    ...f.rows.get(id)!,
    state: "finished",
    outcome: "completed",
  });
  await f.controller.refresh();
  assert.equal(f.controller.state.automaticNextAt, 70_000);
  now = 69_999;
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 1);
  assert.equal(f.controller.state.automaticNextAt, 70_000);
  now = 70_000;
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 2);
  assert.equal(f.device.connections.length, 2);
});

test("composeur : Attendre annule le départ suivant, permet un appel manuel et exige une reprise", async (t) => {
  let now = 0;
  t.mock.method(performance, "now", () => now);
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  const id = f.device.connections[0];
  f.rows.set(id, {
    ...f.rows.get(id)!,
    state: "finished",
    outcome: "completed",
  });
  await f.controller.refresh();
  now = 9_999;
  await f.controller.pauseAutomatic();
  now = 60_000;
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 1);
  assert.equal(f.controller.state.automaticNextAt, null);
  assert.equal(f.controller.state.automaticRunning, false);
  await f.controller.start("", "+14165550101");
  assert.equal(f.device.connections.length, 2);
  assert.equal(f.nextCount, 1);
  const manual = f.device.connections[1];
  f.rows.set(manual, {
    ...f.rows.get(manual)!,
    state: "finished",
    outcome: "completed",
  });
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 2);
});

test("composeur : perte de présence pendant les dix secondes interdit tout départ tardif", async (t) => {
  let now = 0;
  t.mock.method(performance, "now", () => now);
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  const id = f.device.connections[0];
  f.rows.set(id, {
    ...f.rows.get(id)!,
    state: "finished",
    outcome: "completed",
  });
  await f.controller.refresh();
  f.failHeartbeat();
  await f.controller.automaticTick();
  await f.controller.automaticTick();
  await f.controller.automaticTick();
  now = 10_000;
  await f.controller.automaticTick();
  assert.equal(f.controller.state.automaticNextAt, null);
  assert.equal(f.controller.state.automaticRunning, false);
  assert.equal(f.nextCount, 1);
});

test("composeur : un RDV pendant le décompte conserve le délai, une restauration exige une reprise", async (t) => {
  let now = 0;
  t.mock.method(performance, "now", () => now);
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  const id = f.device.connections[0];
  f.rows.set(id, {
    ...f.rows.get(id)!,
    state: "finished",
    outcome: "completed",
  });
  await f.controller.refresh();
  const hold = await f.controller.beginBooking("campaign");
  now = 1_000;
  await f.controller.endBooking(hold);
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 1);
  assert.equal(f.controller.state.automaticNextAt, 10_000);
  f.controller.dispose();
  f.controller.activate();
  now = 10_000;
  await f.controller.refreshAutomatic();
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 1);
  assert.equal(f.controller.state.automaticNextAt, null);
  assert.equal(f.controller.state.automaticRunning, false);
});

test("composeur : pause pendant une réponse de réservation perdue, aucun SDK ni appel tardif", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  const gate = deferred<void>();
  f.setGate(gate.promise);
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  const pending = f.controller.automaticTick();
  await setImmediate();
  await f.controller.pauseAutomatic();
  gate.resolve();
  await pending;
  assert.equal(f.device.connections.length, 0);
  assert.equal(f.controller.state.automaticRunning, false);
  assert.equal(f.controller.state.phase, "idle");
});

test("composeur : pause ne raccroche pas une conversation déjà connectée", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  const id = f.device.connections[0];
  f.rows.set(id, { ...f.rows.get(id)!, state: "answered" });
  f.device.call.emit("accept");
  await f.controller.pauseAutomatic();
  assert.equal(f.device.call.disconnected, 0);
  f.rows.set(id, {
    ...f.rows.get(id)!,
    state: "finished",
    outcome: "completed",
  });
  await f.controller.refresh();
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 1);
});

test("composeur : perte de présence suspend l’enchaînement sans inventer la fin de l’appel", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  f.failHeartbeat();
  await f.controller.automaticTick();
  assert.equal(f.controller.state.automaticRunning, true);
  await f.controller.automaticTick();
  assert.equal(f.controller.state.automaticRunning, true);
  await f.controller.automaticTick();
  assert.equal(f.controller.state.automaticRunning, false);
  assert.equal(f.device.call.disconnected, 0);
  assert.notEqual(f.controller.state.phase, "idle");
  assert.equal(f.nextCount, 1);
});

test("composeur : une microcoupure ne lance aucun appel, puis la vérification réussie permet de continuer", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  f.empty();
  f.failHeartbeat();
  await f.controller.automaticTick();
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 0);
  assert.equal(f.controller.state.automaticRunning, true);
  f.recoverHeartbeat();
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 1);
  assert.equal(f.controller.state.automaticError, "");
  f.failHeartbeat();
  await f.controller.automaticTick();
  assert.equal(f.controller.state.automaticRunning, true);
  assert.equal(f.nextCount, 1);
});

test("composeur : une autorisation révoquée suspend dès le premier refus", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  f.automatic.heartbeat = async () => {
    throw Object.assign(new Error("Accès refusé"), { status: 403 });
  };
  await f.controller.automaticTick();
  assert.equal(f.controller.state.automaticRunning, false);
  assert.equal(f.nextCount, 0);
});

test("composeur : la saisie RDV suspend, puis reprend seulement si aucune pause n’a été demandée", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  const hold = await f.controller.beginBooking("campaign");
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 0);
  assert.equal(f.heartbeatCount, 1);
  await f.controller.endBooking(hold);
  assert.equal(f.controller.state.automaticRunning, true);
  const second = await f.controller.beginBooking("campaign");
  await f.controller.pauseAutomatic();
  await f.controller.endBooking(second);
  assert.equal(f.controller.state.automaticRunning, false);
});

test("composeur : une perte de présence pendant le RDV exige une reprise explicite", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  const hold = await f.controller.beginBooking("campaign");
  f.failHeartbeat();
  await f.controller.automaticTick();
  await f.controller.automaticTick();
  await f.controller.automaticTick();
  await f.controller.endBooking(hold);
  assert.equal(f.controller.state.automaticRunning, false);
  assert.equal(f.nextCount, 0);
});

test("composeur : un autre navigateur ou une restauration ne redémarre jamais les appels seul", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  f.foreign();
  await f.controller.refresh();
  await f.controller.refreshAutomatic();
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 0);
  await f.controller.startAutomatic("campaign");
  f.controller.dispose();
  f.controller.activate();
  await f.controller.refreshAutomatic();
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 0);
});

test("composeur : une file vide ne crée ni réservation, ni SDK, ni faux historique", async (t) => {
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  f.empty();
  await f.controller.refresh();
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  assert.equal(f.controller.state.phase, "idle");
  assert.equal(f.rows.size, 0);
  assert.equal(f.device.connections.length, 0);
  assert.equal(f.controller.state.automaticRunning, true);
});

test("boîte vocale : raccroche immédiatement et enregistre le bon appel malgré le suivant", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  const saved = deferred<unknown>();
  const recorded: string[] = [];
  f.api.voicemail = async (id) => {
    recorded.push(id);
    return saved.promise;
  };
  await f.controller.refresh();
  await f.controller.start("", "+14165550101");
  const first = f.controller.state.intent!;
  first.state = "answered";
  const saving = f.controller.voicemail();
  assert.equal(f.device.call.disconnected, 1);
  assert.deepEqual(recorded, [first.id]);
  f.rows.set(first.id, { ...first, state: "finished", outcome: "completed" });
  await setImmediate();
  await f.controller.refresh();
  await f.controller.start("", "+14165550102");
  const second = f.controller.state.intent!;
  assert.notEqual(second.id, first.id);
  saved.resolve({});
  await saving;
  assert.equal(f.controller.state.intent?.id, second.id);
  assert.equal(f.controller.state.voicemailPending.length, 0);
  assert.deepEqual(recorded, [first.id]);
});

test("boîte vocale : une réponse perdue est reprise sans perdre le contexte après réactivation", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  const response = deferred<unknown>();
  const recorded: string[] = [];
  f.api.voicemail = async (id) => {
    recorded.push(id);
    return response.promise;
  };
  await f.controller.refresh();
  await f.controller.start("", "+14165550101");
  const id = f.controller.state.intent!.id;
  const saving = f.controller.voicemail();
  f.controller.dispose();
  f.controller.activate();
  response.reject(new Error("synthetic lost response"));
  await saving;
  assert.deepEqual(
    f.controller.state.voicemailFailures.map((row) => row.id),
    [id],
  );
  f.api.voicemail = async (target) => {
    recorded.push(target);
  };
  await f.controller.retryVoicemail(id);
  assert.equal(f.controller.state.voicemailFailures.length, 0);
  assert.deepEqual(recorded, [id, id]);
});

test("un appel entrant suspend les départs sortants, garde la présence et laisse dix secondes après sa fin", async (t) => {
  let now = 0;
  t.mock.method(performance, "now", () => now);
  const f = automaticFixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await f.controller.refreshAutomatic();
  f.controller.setInboundBusy(true);
  await f.controller.startAutomatic("campaign");
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 0);
  assert.equal(f.creations(), 0);
  assert.ok(f.heartbeatCount > 0);
  now = 20000;
  f.controller.setInboundBusy(false);
  assert.equal(f.controller.state.automaticNextAt, 30000);
  now = 29999;
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 0);
  now = 30000;
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 1);
});

test("boîte vocale : une ancienne réponse après réactivation ne supprime pas la nouvelle tentative", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  const old = deferred<unknown>(),
    retry = deferred<unknown>();
  let requests = 0;
  f.api.voicemail = async () =>
    ++requests === 1 ? old.promise : retry.promise;
  await f.controller.refresh();
  await f.controller.start("", "+14165550101");
  const id = f.controller.state.intent!.id;
  const saving = f.controller.voicemail();
  f.controller.dispose();
  f.controller.activate();
  const resaving = f.controller.retryVoicemail(id);
  assert.equal(requests, 2);
  assert.deepEqual(f.controller.state.voicemailPending, [id]);
  old.resolve({});
  await saving;
  assert.deepEqual(f.controller.state.voicemailPending, [id]);
  assert.equal(f.controller.state.voicemailFailures.length, 1);
  retry.resolve({});
  await resaving;
  assert.deepEqual(f.controller.state.voicemailPending, []);
  assert.deepEqual(f.controller.state.voicemailFailures, []);
});
