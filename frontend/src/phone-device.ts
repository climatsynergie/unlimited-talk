import type { MediaDevice } from "./phone-controller";

export async function createPhoneDevice(token: string): Promise<MediaDevice> {
  const { Device } = await import("@twilio/voice-sdk");
  const device = new Device(token, {
    logLevel: "silent",
    enableImprovedSignalingErrorPrecision: true,
    maxCallSignalingTimeoutMs: 10_000,
  });
  let destroyed = false;
  return {
    onError(listener) {
      device.on("error", listener);
    },
    async connect(id, input) {
      if (destroyed) throw new Error("Téléphone arrêté");
      const audio = device.audio;
      if (input && audio) await audio.setInputDevice(input);
      if (destroyed) {
        await audio?.unsetInputDevice().catch(() => {});
        throw new Error("Téléphone arrêté");
      }
      return device.connect({
        params: { Intent: id },
        rtcConstraints: { audio: true },
      });
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      void device.audio?.unsetInputDevice().catch(() => {});
      device.destroy();
    },
  };
}
