"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const { randomBytes, randomUUID } = require("node:crypto");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { Device, Call } = require("@twilio/voice-sdk");
const errors = require(
  path.resolve(
    path.dirname(require.resolve("@twilio/voice-sdk")),
    "twilio/errors/index.js",
  ),
);

// These tests execute the installed SDK's real Device.connect/_makeCall and
// Call constructor/lifecycle. Only RTC, microphone, transport, publisher, sound
// and statistics collection are fake. They establish no live audio acceptance.
class Audio extends EventEmitter {
  _getInputDevicePromise() {
    return null;
  }
  _destroy() {}
  _maybeStopPollingVolume() {}
  _maybeStartPollingVolume() {}
  outgoing() {
    return false;
  }
  incoming() {
    return false;
  }
  disconnect() {
    return false;
  }
}
class Publisher extends EventEmitter {
  info() {}
  error() {}
  debug() {}
  warn() {}
  post() {}
  setToken() {}
  disable() {}
}
class Sound {
  stop() {}
  play() {
    return Promise.resolve();
  }
}
class Monitor extends EventEmitter {
  disableWarnings() {}
  enableWarnings() {}
  disable() {}
}
class MediaHandler {
  openDefaultDeviceWithConstraints() {
    return Promise.resolve();
  }
  _setSinkIds() {
    return Promise.resolve();
  }
  makeOutgoingCall() {}
  reject() {}
  close() {
    this.onclose?.();
  }
}
class LocalMediaCall extends Call {
  constructor(config, options) {
    super(config, { ...options, MediaHandler, StatsMonitor: Monitor });
  }
}
function sid() {
  return "CA" + randomBytes(16).toString("hex");
}
function jwt() {
  const encode = (value) =>
    Buffer.from(JSON.stringify(value)).toString("base64url");
  return [
    encode({ alg: "HS256", typ: "JWT" }),
    encode({ jti: randomUUID(), sub: "synthetic-sdk-test" }),
    randomBytes(32).toString("base64url"),
  ].join(".");
}
function isolate(t) {
  // SDK Call schedules a statistics-warning timeout; fake timers prevent a
  // twenty-second process hold and are automatically restored by node:test.
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(Device.prototype, "_setupStream", () => {
    throw new Error("Unexpected real signaling setup");
  });
}
function makeDevice(t, token = jwt()) {
  const device = new Device(token, {
    logLevel: "silent",
    enableImprovedSignalingErrorPrecision: true,
    AudioHelper: Audio,
    Publisher,
    Sound,
    Call: LocalMediaCall,
  });
  const stream = new EventEmitter();
  const proof = { destroyedWithDeviceListener: null };
  stream.status = "connected";
  stream.updatePreferredURI = () => {};
  stream.hangup = () => {};
  stream.reject = () => {};
  stream.on("error", () => {}); // Synthetic post-destroy errors must not throw.
  stream.on("error", device._onSignalingError);
  stream.on("close", device._onSignalingClose);
  stream.destroy = () => {
    proof.destroyedWithDeviceListener = stream
      .listeners("error")
      .includes(device._onSignalingError);
    stream.status = "disconnected";
    stream.emit("error", {
      error: { code: 53000, message: "Synthetic shutdown only" },
    });
    stream.emit("close");
  };
  device._stream = stream;
  device._streamConnectedPromise = Promise.resolve(stream);
  device._publishNetworkChange = () => {};
  t.after(() => {
    if (device.state !== "destroyed") device.destroy();
  });
  return { device, stream, proof };
}
const turn = () => new Promise((resolve) => setImmediate(resolve));

test(
  "SDK 2.18.5 outgoing errors lack a Call association; actual incoming offers use the calls list",
  { timeout: 5_000 },
  async (t) => {
    isolate(t);
    const { device, stream } = makeDevice(t);
    const call = await device.connect({ params: { Intent: randomUUID() } });
    await turn();
    const callSid = sid();
    stream.emit("ringing", { callsid: callSid });
    assert.ok(call instanceof Call);
    assert.equal(call.direction, "OUTGOING");
    assert.equal(device._activeCall, call);
    assert.equal(device.calls.length, 0);
    assert.equal(device._findCall(callSid), null);
    const events = [];
    device.on("error", (error, associated) =>
      events.push({ code: error.code, associated }),
    );
    stream.emit("error", {
      callsid: callSid,
      error: { code: 31486, message: "Synthetic busy" },
    });
    assert.equal(events.length, 1);
    assert.equal(events[0].code, 31486);
    assert.equal(events[0].associated, undefined);
    const lifecycle = [];
    call.on("error", (error) => lifecycle.push(error.code));
    call.on("disconnect", () => lifecycle.push("disconnect"));
    stream.emit("hangup", {
      callsid: callSid,
      error: { code: 31486, message: "Synthetic remote busy" },
    });
    assert.deepEqual(lifecycle, [31486, "disconnect"]);
    assert.equal(call.status(), "closed");
    assert.equal(device._activeCall, null);
    const incomingSid = sid();
    await device._onSignalingInvite({
      callsid: incomingSid,
      sdp: "v=0\r\n",
      parameters: { CallSid: incomingSid },
    });
    await turn();
    const incoming = device.calls[0];
    assert.ok(incoming instanceof Call);
    assert.equal(incoming.direction, "INCOMING");
    assert.equal(device._findCall(incomingSid), incoming);
    stream.emit("error", {
      callsid: incomingSid,
      error: { code: 31486, message: "Synthetic incoming busy" },
    });
    assert.equal(events.at(-1).associated, incoming);
  },
);

test(
  "SDK preserves nested WebSocket 53000 under outer 31005 and detaches errors before stream destruction",
  { timeout: 5_000 },
  async (t) => {
    isolate(t);
    const { device, stream, proof } = makeDevice(t);
    const call = await device.connect({ params: { Intent: randomUUID() } });
    await turn();
    const events = [];
    device.on("error", (error, associated) =>
      events.push({ error, associated }),
    );
    stream.emit("error", {
      error: {
        code: 31005,
        message: "Synthetic abnormal WebSocket close",
        twilioError: new errors.SignalingErrors.ConnectionError(),
      },
    });
    assert.equal(events.length, 1);
    assert.equal(events[0].associated, undefined);
    assert.equal(events[0].error.code, 31005);
    assert.equal(events[0].error.originalError.twilioError.code, 53000);
    assert.equal(device._activeCall, call);
    device.destroy();
    assert.equal(call.status(), "closed");
    assert.equal(proof.destroyedWithDeviceListener, false);
    assert.equal(
      events.length,
      1,
      "intentional stream shutdown cannot emit another Device error",
    );
  },
);

async function controllerFixture(t) {
  isolate(t);
  const { PhoneController } = await import(
    pathToFileURL(path.resolve(__dirname, "../src/phone-controller.ts")).href
  );
  let now = 0;
  t.mock.method(performance, "now", () => now);
  let row = {
    mode: "stopped",
    generation: 0,
    campaign_id: null,
    browser_id: null,
  };
  const records = new Map(),
    devices = [],
    actions = [];
  let nextCount = 0;
  const transport = {
    session: async () => ({
      enabled: true,
      destination: null,
      max_duration_seconds: 1800,
      active: null,
    }),
    reserve: async () => {
      throw new Error("Unexpected manual reservation");
    },
    history: async (id) => ({ intent: records.get(id) }),
    cancel: async (id) => records.get(id),
  };
  const automatic = {
    session: async () => ({ enabled: true, dialer: { ...row } }),
    control: async (body) => {
      actions.push(body.action);
      row = {
        ...row,
        mode: body.action === "start" ? "running" : "paused",
        generation: row.generation + 1,
        browser_id: body.browser_id,
        campaign_id: body.campaign_id || row.campaign_id,
      };
      return { dialer: { ...row } };
    },
    heartbeat: async () => ({ dialer: { ...row } }),
    next: async (body) => {
      nextCount++;
      const intent = {
        id: body.id,
        state: "ringing",
        outcome: null,
        automatic: true,
        owned_session: true,
        destination: "+14165550101",
      };
      records.set(body.id, intent);
      return { intent, token: jwt(), dialer: { ...row } };
    },
  };
  const controller = new PhoneController(
    transport,
    async (token) => {
      const actual = makeDevice(t, token);
      devices.push(actual);
      return {
        onError: (listener) => actual.device.on("error", listener),
        connect: (id) =>
          actual.device.connect({
            params: { Intent: id },
            rtcConstraints: { audio: true },
          }),
        destroy: () => actual.device.destroy(),
      };
    },
    automatic,
  );
  t.after(() => controller.dispose());
  await controller.refresh();
  await controller.startAutomatic(randomUUID());
  await controller.automaticTick();
  await turn();
  return {
    controller,
    records,
    devices,
    actions,
    get nextCount() {
      return nextCount;
    },
    advance: (value) => {
      now = value;
    },
  };
}

test(
  "actual SDK unassociated busy reconciles without pausing and waits for terminal state plus ten seconds",
  { timeout: 5_000 },
  async (t) => {
    const f = await controllerFixture(t);
    const first = f.devices[0],
      id = [...f.records.keys()][0];
    const callSid = sid();
    first.stream.emit("ringing", { callsid: callSid });
    first.stream.emit("error", {
      callsid: callSid,
      error: { code: 31486, message: "Synthetic busy" },
    });
    await turn();
    assert.equal(f.controller.state.phase, "checking");
    assert.equal(f.controller.state.automaticRunning, true);
    assert.equal(f.controller.state.automaticNextAt, null);
    assert.deepEqual(f.actions, ["start"]);
    f.advance(30_000);
    await f.controller.automaticTick();
    assert.equal(f.nextCount, 1, "uncertain provider state must never redial");
    f.records.set(id, {
      ...f.records.get(id),
      state: "finished",
      outcome: "busy",
    });
    await f.controller.refresh();
    assert.equal(f.controller.state.automaticNextAt, 40_000);
    f.advance(39_999);
    await f.controller.automaticTick();
    assert.equal(f.nextCount, 1);
    f.advance(40_000);
    await f.controller.automaticTick();
    assert.equal(f.nextCount, 2);
    assert.deepEqual(f.actions, ["start"]);
  },
);

test(
  "actual SDK mapped WebSocket failure keeps automatic dialing paused after a terminal no-answer",
  { timeout: 5_000 },
  async (t) => {
    const f = await controllerFixture(t);
    const id = [...f.records.keys()][0];
    f.devices[0].stream.emit("error", {
      error: {
        code: 31005,
        message: "Synthetic abnormal WebSocket close",
        twilioError: new errors.SignalingErrors.ConnectionError(),
      },
    });
    await turn();
    f.records.set(id, {
      ...f.records.get(id),
      state: "finished",
      outcome: "no-answer",
    });
    await f.controller.refresh();
    f.advance(60_000);
    await f.controller.automaticTick();
    assert.equal(f.controller.state.automaticRunning, false);
    assert.deepEqual(f.actions, ["start", "pause"]);
    assert.equal(f.nextCount, 1);
  },
);
