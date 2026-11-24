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
  const options = {
    logLevel: "silent" as const,
    enableImprovedSignalingErrorPrecision: true,
    maxCallSignalingTimeoutMs: 10_000,
    tokenRefreshMs: 60_000,
  };
  let destroyed = false;
  let currentToken = token;
  let needsReset = false;
  let device = new Device(token, options);
  function listen(receiver: InstanceType<typeof Device>) {
    const current = () => !destroyed && device === receiver;
    receiver.on("registered", () => {
      if (!current()) return;
      needsReset = false;
      handlers.registered();
    });
    receiver.on("unregistered", () => {
      if (current()) handlers.unregistered();
    });
    receiver.on("tokenWillExpire", () => {
      if (current()) handlers.tokenWillExpire();
    });
    receiver.on("error", (error) => {
      if (!current()) return;
      // SDK errors, including token expiry, do not always change Device.state.
      // Reset the idle receiver on retry instead of trusting stale registration.
      needsReset = true;
      handlers.error(error);
    });
    receiver.on("incoming", (call) => {
      if (!current()) {
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
          if (input && receiver.audio)
            await receiver.audio.setInputDevice(input);
          if (!current()) {
            void receiver.audio?.unsetInputDevice().catch(() => {});
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
  }
  listen(device);
  return {
    async register() {
      if (destroyed) return;
      if (needsReset) {
        const previous = device;
        device = new Device(currentToken, options);
        needsReset = false;
        listen(device);
        previous.destroy();
      }
      const receiver = device;
      if (receiver.state === "registered") {
        handlers.registered();
        return;
      }
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([
          receiver.register(),
          new Promise<never>((_resolve, reject) => {
            timer = setTimeout(
              () =>
                reject(
                  new Error("La connexion du téléphone prend trop de temps."),
                ),
              10_000,
            );
          }),
        ]);
      } catch (error) {
        if (!destroyed && receiver === device) needsReset = true;
        throw error;
      } finally {
        clearTimeout(timer);
      }
    },
    updateToken(value) {
      currentToken = value;
      if (!destroyed && !needsReset) device.updateToken(value);
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
