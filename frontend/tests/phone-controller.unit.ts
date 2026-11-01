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
  listeners = new Map<string, () => void>();
  disconnected = 0;
  on(event: string, listener: () => void) {
    this.listeners.set(event, listener);
  }
  emit(event: string) {
    this.listeners.get(event)?.();
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
  error = () => {};
  onError(listener: () => void) {
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
  t.mock.timers.tick(420_000);
  assert.equal(f.device.call.disconnected, 1);
  f.controller.dispose();
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

test("composeur : lancement explicite, un seul appel puis enchaînement après résultat serveur", async (t) => {
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
  f.rows.set(id, {
    ...f.rows.get(id)!,
    state: "finished",
    outcome: "completed",
  });
  await f.controller.refresh();
  await f.controller.automaticTick();
  assert.equal(f.nextCount, 2);
  assert.equal(f.device.connections.length, 2);
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
  assert.equal(f.controller.state.automaticRunning, false);
  assert.equal(f.device.call.disconnected, 0);
  assert.notEqual(f.controller.state.phase, "idle");
  assert.equal(f.nextCount, 1);
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
