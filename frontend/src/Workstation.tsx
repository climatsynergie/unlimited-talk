import { useCallback, useEffect, useRef, useState } from "react";
import { Icon, Notice } from "./ui";
import { CallHistory } from "./CallHistory";

type Microphone = {
  context?: AudioContext;
  stream?: MediaStream;
  source?: MediaStreamAudioSourceNode;
  frame?: number;
  timer?: number;
};
type Output = { context?: AudioContext; tone?: OscillatorNode };
type MicroState = "idle" | "requesting" | "active";

function audioError(error: unknown): string {
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "L’accès au microphone est bloqué. Autorisez-le dans les réglages de ce site, puis recommencez.";
  if (name === "NotFoundError" || name === "OverconstrainedError")
    return "Ce microphone est introuvable. Branchez votre casque ou choisissez un autre microphone.";
  if (name === "NotReadableError")
    return "Le microphone est indisponible. Vérifiez son branchement et fermez les applications qui l’utilisent.";
  return "Le test audio n’a pas pu démarrer. Vérifiez votre équipement et réessayez.";
}

export function Workstation() {
  const [microState, setMicroState] = useState<MicroState>("idle");
  const [level, setLevel] = useState(0);
  const [detected, setDetected] = useState(false);
  const [microStatus, setMicroStatus] = useState("Microphone arrêté.");
  const [error, setError] = useState("");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [playing, setPlaying] = useState(false);
  const [played, setPlayed] = useState(false);
  const [heard, setHeard] = useState(false);
  const mounted = useRef(false);
  const generation = useRef(0);
  const microphone = useRef<Microphone>({});
  const output = useRef<Output>({});

  const stopMicrophone = useCallback((status = "Microphone arrêté.") => {
    generation.current += 1;
    const current = microphone.current;
    microphone.current = {};
    if (current.frame !== undefined) cancelAnimationFrame(current.frame);
    if (current.timer !== undefined) window.clearTimeout(current.timer);
    current.stream?.getTracks().forEach((track) => {
      track.onended = null;
      track.stop();
    });
    current.source?.disconnect();
    if (current.context && current.context.state !== "closed")
      void current.context.close().catch(() => {});
    if (mounted.current) {
      setMicroState("idle");
      setLevel(0);
      setMicroStatus(status);
    }
  }, []);

  const stopOutput = useCallback(() => {
    const current = output.current;
    output.current = {};
    if (current.tone) {
      current.tone.onended = null;
      try {
        current.tone.stop();
      } catch {
        // The short sound may already have ended.
      }
      current.tone.disconnect();
    }
    if (current.context && current.context.state !== "closed")
      void current.context.close().catch(() => {});
    if (mounted.current) setPlaying(false);
  }, []);

  useEffect(() => {
    mounted.current = true;
    function suspend() {
      stopMicrophone("Test arrêté en quittant la page.");
      stopOutput();
    }
    function visibility() {
      if (document.visibilityState === "hidden") suspend();
    }
    window.addEventListener("pagehide", suspend);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      mounted.current = false;
      stopMicrophone();
      stopOutput();
      window.removeEventListener("pagehide", suspend);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [stopMicrophone, stopOutput]);

  async function startMicrophone() {
    stopMicrophone();
    const request = ++generation.current;
    setError("");
    setDetected(false);
    if (
      !window.isSecureContext ||
      !navigator.mediaDevices?.getUserMedia ||
      typeof AudioContext === "undefined"
    ) {
      setError(
        "Le test audio nécessite un navigateur récent et une connexion HTTPS.",
      );
      return;
    }
    setMicroState("requesting");
    setMicroStatus("Autorisez le microphone dans la fenêtre du navigateur.");
    const current: Microphone = {};
    microphone.current = current;
    try {
      const context = new AudioContext();
      current.context = context;
      await context.resume();
      if (!mounted.current || request !== generation.current) return;
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
          echoCancellation: true,
          noiseSuppression: true,
        },
        video: false,
      });
      if (
        !mounted.current ||
        request !== generation.current ||
        document.visibilityState === "hidden"
      ) {
        stream.getTracks().forEach((track) => track.stop());
        if (mounted.current && request === generation.current) stopMicrophone();
        return;
      }
      current.stream = stream;
      const track = stream.getAudioTracks()[0];
      if (!track || track.readyState !== "live")
        throw new DOMException("", "NotFoundError");
      track.onended = () => {
        if (request !== generation.current) return;
        stopMicrophone("Microphone déconnecté.");
        setError(
          "Le microphone a été déconnecté. Rebranchez-le, puis recommencez le test.",
        );
      };
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      current.source = context.createMediaStreamSource(stream);
      current.source.connect(analyser);
      // No connection to the speakers: avoid playing the live microphone back.
      const samples = new Float32Array(analyser.fftSize);
      let lastUpdate = 0;
      function measure(now: number) {
        if (!mounted.current || request !== generation.current) return;
        if (now - lastUpdate >= 100) {
          analyser.getFloatTimeDomainData(samples);
          const rms = Math.sqrt(
            samples.reduce((sum, sample) => sum + sample * sample, 0) /
              samples.length,
          );
          setLevel(Math.min(100, Math.round(rms * 250)));
          if (rms > 0.01) setDetected(true);
          lastUpdate = now;
        }
        current.frame = requestAnimationFrame(measure);
      }
      current.frame = requestAnimationFrame(measure);
      current.timer = window.setTimeout(() => {
        if (request === generation.current)
          stopMicrophone("Test terminé : microphone arrêté après 30 secondes.");
      }, 30_000);
      setMicroState("active");
      setMicroStatus(
        "Microphone actif. Parlez pour vérifier le niveau sonore.",
      );
      void navigator.mediaDevices
        .enumerateDevices()
        .then((available) => {
          if (mounted.current && request === generation.current)
            setDevices(
              available.filter(
                (device) =>
                  device.kind === "audioinput" &&
                  device.deviceId &&
                  device.deviceId !== "default",
              ),
            );
        })
        .catch(() => {});
    } catch (failure) {
      if (!mounted.current || request !== generation.current) return;
      stopMicrophone();
      setError(audioError(failure));
    }
  }

  async function playSound() {
    stopOutput();
    setError("");
    setHeard(false);
    setPlayed(false);
    if (typeof AudioContext === "undefined") {
      setError("La lecture audio nécessite un navigateur récent.");
      return;
    }
    const current: Output = {};
    output.current = current;
    setPlaying(true);
    try {
      const context = new AudioContext();
      current.context = context;
      await context.resume();
      if (!mounted.current || output.current !== current) return;
      const tone = context.createOscillator();
      current.tone = tone;
      const volume = context.createGain();
      tone.frequency.value = 440;
      volume.gain.setValueAtTime(0, context.currentTime);
      volume.gain.linearRampToValueAtTime(0.04, context.currentTime + 0.03);
      volume.gain.setValueAtTime(0.04, context.currentTime + 0.6);
      volume.gain.linearRampToValueAtTime(0, context.currentTime + 0.7);
      tone.connect(volume);
      volume.connect(context.destination);
      tone.onended = () => {
        if (!mounted.current || output.current !== current) return;
        stopOutput();
        setPlayed(true);
      };
      tone.start();
      tone.stop(context.currentTime + 0.75);
    } catch {
      if (!mounted.current || output.current !== current) return;
      stopOutput();
      setError(
        "Le son n’a pas pu être joué. Vérifiez la sortie audio de votre navigateur, puis réessayez.",
      );
    }
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">VOTRE ÉQUIPEMENT</span>
          <h1>Poste d’appel</h1>
          <p>Vérifiez votre microphone et le son dans votre casque.</p>
        </div>
      </div>
      {error ? <Notice error>{error}</Notice> : null}
      <div className="audio-grid">
        <section
          className="panel audio-panel"
          aria-labelledby="microphone-heading"
        >
          <div className="audio-heading">
            <Icon name="headset" />
            <h2 id="microphone-heading">1. Tester le microphone</h2>
          </div>
          <p>Branchez votre casque, puis autorisez l’accès au microphone.</p>
          <label className="field" htmlFor="microphone-choice">
            Microphone
            <select
              id="microphone-choice"
              value={deviceId}
              onChange={(event) => {
                stopMicrophone();
                setDeviceId(event.currentTarget.value);
                setDetected(false);
                setError("");
              }}
            >
              <option value="">Microphone par défaut</option>
              {devices.map((device, index) => (
                <option key={device.deviceId} value={device.deviceId}>
                  {device.label || `Microphone ${index + 1}`}
                </option>
              ))}
            </select>
          </label>
          <label className="audio-meter-label" htmlFor="microphone-level">
            Niveau du microphone
          </label>
          <progress
            id="microphone-level"
            className="audio-meter"
            max="100"
            value={level}
          />
          <p className="audio-status" role="status">
            {microStatus}
          </p>
          <p className="audio-result">
            {detected
              ? "Un signal audio a été détecté pendant le test."
              : "Parlez normalement : la barre doit réagir à votre voix."}
          </p>
          <div className="audio-actions">
            {microState === "idle" ? (
              <button
                type="button"
                className="button primary"
                onClick={() => void startMicrophone()}
              >
                Tester mon microphone
              </button>
            ) : (
              <button
                type="button"
                className="button secondary"
                onClick={() => stopMicrophone()}
              >
                {microState === "requesting"
                  ? "Annuler le test du micro"
                  : "Arrêter le microphone"}
              </button>
            )}
          </div>
          <p className="audio-hint">
            Arrêt automatique après 30 secondes. L’audio du microphone reste sur
            cet appareil.
          </p>
        </section>
        <section
          className="panel audio-panel"
          aria-labelledby="headphones-heading"
        >
          <div className="audio-heading">
            <Icon name="headset" />
            <h2 id="headphones-heading">2. Tester le son</h2>
          </div>
          <p>
            Utilisez la sortie audio de votre casque dans les réglages de votre
            ordinateur.
          </p>
          <div className="audio-actions">
            <button
              type="button"
              className="button primary"
              disabled={playing}
              onClick={() => void playSound()}
            >
              {playing ? "Son en cours…" : "Écouter un son de test"}
            </button>
          </div>
          <p className="audio-status" role="status">
            {playing
              ? "Un son court est en cours de lecture."
              : played
                ? "Le son a été joué. Confirmez si vous l’avez entendu."
                : "Un son court vous permettra de vérifier votre casque."}
          </p>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={heard}
              disabled={!played}
              onChange={(event) => setHeard(event.currentTarget.checked)}
            />
            J’ai entendu le son dans mon casque
          </label>
          {heard ? <p className="audio-result">Écoute confirmée.</p> : null}
        </section>
      </div>
      <section
        className="panel audio-panel audio-call-status"
        aria-labelledby="calls-heading"
      >
        <h2 id="calls-heading">Appels téléphoniques</h2>
        <p>
          Le test ci-dessus vérifie votre équipement. Les appels téléphoniques
          ne sont pas encore activés.
        </p>
      </section>
      <CallHistory />
    </>
  );
}
