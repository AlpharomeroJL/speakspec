/**
 * Phase 2 shell: proves the full IPC round trip on screen.
 *
 * Later phases replace this with the recording / review / pipeline UI; the
 * IPC plumbing it exercises stays identical.
 */
import { createSignal, onCleanup, onMount } from "solid-js";
import {
  EVENTS,
  frontendLog,
  onEvent,
  pingSidecar,
  type PingResult,
  type SidecarStatusPayload,
  type SidecarStreamPayload,
} from "./lib/ipc";
import "./App.css";

function App() {
  const [status, setStatus] = createSignal<string>("waiting for sidecar…");
  const [progressLine, setProgressLine] = createSignal<string>("");
  const [pingResult, setPingResult] = createSignal<string>("");
  const unlisteners: Array<() => void> = [];

  async function runPing(): Promise<boolean> {
    setPingResult("pinging…");
    try {
      const result: PingResult = await pingSidecar({ hello: "from-frontend" });
      const rendered = JSON.stringify(result);
      setPingResult(rendered);
      // Land the proof in the Rust dev console for automated verification.
      await frontendLog(`FRONTEND RECEIVED PING RESULT: ${rendered}`);
      return true;
    } catch (err) {
      setPingResult(`ping failed: ${JSON.stringify(err)}`);
      return false;
    }
  }

  onMount(async () => {
    unlisteners.push(
      await onEvent<SidecarStatusPayload>(EVENTS.sidecarStatus, (p) => {
        setStatus(`${p.status}${p.message ? ` — ${p.message}` : ""}`);
        if (p.status === "ready") void runPing();
      }),
    );
    unlisteners.push(
      await onEvent<SidecarStreamPayload>(EVENTS.sidecarProgress, (p) => {
        const line = JSON.stringify(p.data);
        setProgressLine(line);
        void frontendLog(`FRONTEND RECEIVED PROGRESS EVENT: ${line}`);
      }),
    );
    // The "ready" status may fire before these subscriptions attach, so also
    // poll until the first ping lands.
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    for (let attempt = 0; attempt < 30; attempt++) {
      if (await runPing()) break;
      await sleep(1000);
    }
  });

  onCleanup(() => unlisteners.forEach((u) => u()));

  return (
    <main class="container">
      <h1>Speakspec</h1>
      <p>Local-first voice-to-architecture. Phase 2 IPC shell.</p>
      <section>
        <h2>Sidecar</h2>
        <p data-testid="sidecar-status">status: {status()}</p>
        <p data-testid="sidecar-progress">last progress event: {progressLine() || "—"}</p>
        <button type="button" onClick={() => void runPing()}>
          Ping sidecar
        </button>
        <pre data-testid="ping-result">{pingResult()}</pre>
      </section>
    </main>
  );
}

export default App;
