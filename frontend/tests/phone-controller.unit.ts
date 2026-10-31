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
  error = () => {};
  onError(listener: () => void) {
    this.error = listener;
  }
  async connect(id: string) {
    this.connections.push(id);
    return this.call;
  }
  destroy() {
    ++this.destroyed;
  }
}
function fixture() {
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
  const controller = new PhoneController(api, create);
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
  await f.controller.start();
  await f.controller.refresh();
  await f.controller.start();
  assert.equal(f.reservations(), 0);
  assert.equal(f.creations(), 0);
});
test("double clic : une réservation, un SDK, transitions et fin serveur obligatoires", async (t) => {
  const f = fixture();
  t.after(() => f.controller.dispose());
  await f.controller.refresh();
  await Promise.all([f.controller.start(), f.controller.start()]);
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
  await f.controller.start();
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
  await f.controller.start();
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
  const starting = controller.start();
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
  const starting = f.controller.start();
  await setImmediate();
  const id = f.device.connections[0];
  f.rows.set(id, { id, state: "authorized", outcome: null });
  f.controller.hangup();
  connected.resolve(f.device.call);
  await starting;
  assert.equal(f.device.call.disconnected, 1);
  assert.ok(f.device.destroyed >= 1);
  await f.controller.refresh();
  await f.controller.start();
  assert.equal(f.reservations(), 1);
});
test("déconnexion de session pendant une réservation : aucun SDK même après réponse tardive", async () => {
  const f = fixture(),
    reserved = deferred<{ intent: Intent; token: string }>();
  f.api.reserve = () => reserved.promise;
  await f.controller.refresh();
  const starting = f.controller.start();
  f.controller.dispose();
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
  await f.controller.start();
  f.api.session = async () => {
    throw new Error("offline");
  };
  f.device.call.emit("error");
  await setImmediate();
  assert.equal(f.controller.state.phase, "checking");
  assert.equal(f.device.destroyed, 1);
  await f.controller.start();
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
  const oldStart = f.controller.start();
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
  await controller.start();
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
  const starting = f.controller.start();
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
  await f.controller.start();
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
  await f.controller.start();
  await f.controller.refresh();
  assert.equal(f.controller.state.intent?.id, active.id);
  assert.equal(f.controller.state.phase, "checking");
  assert.equal(f.creations(), 0);
});
