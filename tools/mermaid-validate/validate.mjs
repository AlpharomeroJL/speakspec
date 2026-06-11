/**
 * Mermaid 11 validation service.
 *
 * Reads NDJSON lines {"id": string, "source": string} on stdin; writes one
 * NDJSON line {"id", "ok": boolean, "diagramType"?: string, "error"?: string}
 * per request on stdout. Exits on stdin EOF. Spawned by the Python sidecar
 * (see sidecar/speakspec/mermaid_repair.py); also usable one-shot in CI.
 *
 * mermaid.parse() needs browser globals, provided here by jsdom.
 */
import { createInterface } from "node:readline";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
  url: "http://localhost/",
  pretendToBeVisual: true,
});
for (const key of [
  "window",
  "document",
  "navigator",
  "DOMParser",
  "XMLSerializer",
  "SVGElement",
  "HTMLElement",
]) {
  const value = key === "window" ? dom.window : dom.window[key];
  try {
    Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  } catch {
    // Node may expose the global as non-configurable (e.g. navigator on
    // some versions); the built-in is good enough for mermaid then.
  }
}

const mermaid = (await import("mermaid")).default;
mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });

/** Validate one source; never throws. */
async function check(source) {
  try {
    const result = await mermaid.parse(source);
    return { ok: true, diagramType: result?.diagramType ?? "unknown" };
  } catch (err) {
    return { ok: false, error: String(err?.message ?? err).slice(0, 1000) };
  }
}

const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
process.stdout.write(JSON.stringify({ id: "__ready__", ok: true }) + "\n");
for await (const line of rl) {
  const trimmed = line.trim();
  if (!trimmed) continue;
  let req;
  try {
    req = JSON.parse(trimmed);
  } catch {
    process.stdout.write(
      JSON.stringify({ id: "unknown", ok: false, error: "malformed request line" }) + "\n",
    );
    continue;
  }
  const verdict = await check(String(req.source ?? ""));
  process.stdout.write(JSON.stringify({ id: String(req.id ?? "unknown"), ...verdict }) + "\n");
}
