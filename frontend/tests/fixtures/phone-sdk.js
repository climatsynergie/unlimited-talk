// Replaces only the lazily imported SDK module in Playwright. Never shipped.
const proof = (window.phoneProof ||= {
  created: 0,
  destroyed: 0,
  connections: [],
  disconnected: 0,
  mode: "normal",
});
class FakeCall {
  handlers = new Map();
  on(event, handler) {
    this.handlers.set(event, handler);
  }
  emit(event) {
    this.handlers.get(event)?.();
  }
  disconnect() {
    proof.disconnected += 1;
  }
}
export class Device {
  audio = { setInputDevice: async () => {}, unsetInputDevice: async () => {} };
  constructor() {
    proof.created += 1;
  }
  on(event, handler) {
    if (event === "error") proof.error = handler;
  }
  async connect(options) {
    proof.connections.push(options.params);
    const call = new FakeCall();
    proof.call = call;
    if (proof.mode === "pending")
      await new Promise((resolve) => {
        proof.resolve = resolve;
      });
    return call;
  }
  destroy() {
    proof.destroyed += 1;
  }
}
