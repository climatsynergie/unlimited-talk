import type {
  IncomingCallbacks,
  IncomingMediaCall,
  IncomingMediaDevice,
} from "./incoming-controller";

export async function createIncomingDevice(
  token: string,
  handlers: IncomingCallbacks,
): Promise<IncomingMediaDevice> {
  const { Device } = await import("@twilio/voice-sdk");
  const device = new Device(token, {
    logLevel: "silent",
    enableImprovedSignalingErrorPrecision: true,
    maxCallSignalingTimeoutMs: 10_000,
  });
  let destroyed = false;
  device.on("registered", handlers.registered);
  device.on("unregistered", handlers.unregistered);
  device.on("tokenWillExpire", handlers.tokenWillExpire);
  device.on("error", handlers.error);
  device.on("incoming", (call) => {
    if (destroyed) {
      call.reject();
      return;
    }
    const incoming: IncomingMediaCall = {
      offerId: call.customParameters.get("Offer") || "",
      on(event, callback) {
        call.on(event, callback);
      },
      async accept(input) {
        if (destroyed) throw new Error("Réception arrêtée");
        if (input && device.audio) await device.audio.setInputDevice(input);
        if (destroyed) {
          void device.audio?.unsetInputDevice().catch(() => {});
          throw new Error("Réception arrêtée");
        }
        call.accept({ rtcConstraints: { audio: true } });
      },
      reject() {
        call.reject();
      },
      disconnect() {
        call.disconnect();
      },
    };
    handlers.incoming(incoming);
  });
  return {
    async register() {
      if (!destroyed && device.state !== "registered") await device.register();
    },
    updateToken(value) {
      if (!destroyed) device.updateToken(value);
    },
    releaseInput() {
      void device.audio?.unsetInputDevice().catch(() => {});
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      void device.audio?.unsetInputDevice().catch(() => {});
      device.destroy();
    },
  };
}
