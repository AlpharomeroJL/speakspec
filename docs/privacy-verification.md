# Privacy verification (Wireshark)

The privacy guarantee is a release blocker and is verified by packet capture,
not by code review. Expected result: **zero outbound connections during a full
pipeline run with no cloud key configured**, except localhost traffic.

## Steps

1. **Clean machine state.** Fresh Windows 10/11 VM (or a machine where you can
   account for background traffic). Install Ollama, pull one model
   (`ollama pull qwen3:8b` class), install Speakspec from the release installer.
2. **Start capture.** Install Wireshark. Capture on the active network adapter
   with capture filter: `not (host 127.0.0.1 or host ::1)` — localhost traffic
   (the app ↔ Ollama on `:11434`) is in-machine and expected.
3. **Reduce noise.** Pause OneDrive/Windows Update if practical, close
   browsers. Note the time window precisely.
4. **Run the full loop.** Launch Speakspec → record a ~90s description →
   transcribe → review constraints → answer the interview → generate → open
   every results tab → export all formats.
5. **Inspect.** In Wireshark, filter to the time window and the Speakspec /
   python / ollama process traffic (use `Statistics → Conversations`, sort by
   packets; cross-reference PIDs with `netstat -b` elevated, or use
   ProcMon's network events for per-process attribution).

## Pass criteria

- Zero packets attributable to Speakspec, its Python sidecar, or its Node
  validator to any non-localhost address during the entire session.
- Expected allowed traffic, all local: WebView ↔ Vite (dev builds only),
  sidecar ↔ Ollama on `localhost:11434`.
- First-run model download is the one user-initiated network operation: it is
  Ollama pulling weights from the Ollama registry, happens only when the user
  clicks Pull, and carries no user content. Re-run the capture after models
  are installed to verify the steady state is silent.
- ASR model download (Hugging Face, first transcription only) likewise carries
  no user content; verify subsequent runs are silent.

## Known non-traffic

- No telemetry, crash reporting, or analytics exist in the codebase.
- No license validation or phone-home of any kind.
- Cloud Stage 3 (optional, off by default) sends transcript text only — never
  audio — and only after the user pastes an API key into settings. With no key
  configured, the code path is unreachable.

Record the capture file hash alongside the release notes when checking the
release-blocker box.

## Cloud Stage 3 verification (second capture)

When the user enables cloud Stage 3 and saves an API key in Settings:

1. Repeat steps 1–5 above with cloud Stage 3 enabled and a valid key.
2. **Pass criteria:** the only non-localhost traffic attributable to Speakspec
   is HTTPS to the configured provider (OpenAI or Anthropic). No audio bytes
   leave the machine; only architecture-spec text from Stage 3.
3. Mermaid diagram repair and local Ollama calls (if any) remain on localhost.
4. Archive this capture separately with its SHA-256 hash.
