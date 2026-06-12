/**
 * Results: the artifact bundle. AGENTS.md is the hero tab; diagrams render
 * live via mermaid 11 in the webview (the same parser family as the repair
 * loop) with one-click copy of the raw source (DOD 2.9).
 */
import { createEffect, createSignal, For, Show } from "solid-js";
import { exportBundle, showInFolder } from "../lib/ipc";
import { errorText, resetSession, setError, state } from "../state";

type MermaidApi = typeof import("mermaid")["default"];
let mermaidPromise: Promise<MermaidApi> | null = null;

function loadMermaid(): Promise<MermaidApi> {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((mod) => {
      mod.default.initialize({
        startOnLoad: false,
        securityLevel: "loose",
        theme: "neutral",
      });
      return mod.default;
    });
  }
  return mermaidPromise;
}

const TABS = ["AGENTS.md", "CLAUDE.md", "ADRs", "Diagrams", "File tree", "First PR", "JSON"];
const DIAGRAM_KINDS = ["sequence", "er", "component", "c4_context", "c4_container"] as const;

export default function Results() {
  const [tab, setTab] = createSignal("AGENTS.md");
  const [copied, setCopied] = createSignal("");
  const bundle = () => state.stage3 as Record<string, unknown> | null;
  const diagrams = () => (bundle()?.diagrams ?? {}) as Record<string, string>;
  const adrs = () => (bundle()?.adrs ?? []) as Array<{ filename: string; markdown: string }>;
  const firstPr = () => bundle()?.first_pr as Record<string, unknown> | undefined;

  async function copy(text: string, label: string) {
    await navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(""), 1500);
  }

  function reportFor(kind: string) {
    return state.diagramReports.find((r) => r.kind === kind) as
      | { status?: string }
      | undefined;
  }

  function MermaidView(props: { kind: string; source: string }) {
    let host: HTMLDivElement | undefined;
    createEffect(() => {
      const source = props.source;
      if (!host || !source) return;
      void loadMermaid()
        .then((mermaid) => mermaid.render(`d-${props.kind}-${Date.now()}`, source))
        .then(({ svg }) => {
          if (host) host.innerHTML = svg;
        })
        .catch((err: unknown) => {
          if (host) {
            host.textContent = `render failed (flagged for manual review): ${String(err)}`;
          }
        });
    });
    return <div class="mermaid-host" ref={host} />;
  }

  const [exported, setExported] = createSignal<string[]>([]);

  async function onExport() {
    if (!state.sessionDir || !state.stage2 || !bundle()) return;
    try {
      const result = await exportBundle({
        session_dir: state.sessionDir,
        architecture_spec: state.stage2,
        output_bundle: bundle()!,
        diagram_reports: state.diagramReports,
      });
      setExported(result.written);
      if (result.written[0]) void showInFolder(result.written[0]);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <section class="panel wide">
      <div class="row gap wrap">
        <h2>Your architecture bundle</h2>
        <span class="spacer" />
        <button type="button" class="primary" data-testid="export-all" onClick={() => void onExport()}>
          Export all…
        </button>
        <button type="button" onClick={() => resetSession()}>
          New session
        </button>
      </div>
      <Show when={exported().length > 0}>
        <p class="copied">{exported().length} files written ✓</p>
      </Show>
      <nav class="tabs">
        <For each={TABS}>
          {(t) => (
            <button
              type="button"
              classList={{ tab: true, active: tab() === t }}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          )}
        </For>
      </nav>
      <Show when={copied()}>
        <p class="copied">copied {copied()} ✓</p>
      </Show>

      <Show when={tab() === "AGENTS.md"}>
        <div class="row right gap">
          <button
            type="button"
            class="primary"
            onClick={() => void copy(String(bundle()?.agents_md ?? ""), "AGENTS.md")}
          >
            Copy AGENTS.md
          </button>
        </div>
        <pre class="artifact" data-testid="agents-md">
          {String(bundle()?.agents_md ?? "")}
        </pre>
      </Show>

      <Show when={tab() === "CLAUDE.md"}>
        <div class="row right gap">
          <button
            type="button"
            onClick={() => void copy(String(bundle()?.claude_md_shim ?? ""), "CLAUDE.md")}
          >
            Copy CLAUDE.md
          </button>
        </div>
        <pre class="artifact">{String(bundle()?.claude_md_shim ?? "")}</pre>
      </Show>

      <Show when={tab() === "ADRs"}>
        <For each={adrs()}>
          {(adr) => (
            <details class="adr">
              <summary>
                {adr.filename}
                <button type="button" class="link" onClick={() => void copy(adr.markdown, adr.filename)}>
                  copy
                </button>
              </summary>
              <pre class="artifact">{adr.markdown}</pre>
            </details>
          )}
        </For>
      </Show>

      <Show when={tab() === "Diagrams"}>
        <For each={[...DIAGRAM_KINDS]}>
          {(kind) => (
            <div class="diagram-block">
              <div class="row gap">
                <h3>{kind}</h3>
                <Show when={reportFor(kind)?.status}>
                  <span classList={{ badge: true, [String(reportFor(kind)?.status)]: true }}>
                    {reportFor(kind)?.status}
                  </span>
                </Show>
                <span class="spacer" />
                <button type="button" onClick={() => void copy(diagrams()[kind] ?? "", kind)}>
                  Copy source
                </button>
              </div>
              <MermaidView kind={kind} source={diagrams()[kind] ?? ""} />
            </div>
          )}
        </For>
      </Show>

      <Show when={tab() === "File tree"}>
        <div class="row right gap">
          <button type="button" onClick={() => void copy(String(bundle()?.file_tree ?? ""), "file tree")}>
            Copy
          </button>
        </div>
        <pre class="artifact">{String(bundle()?.file_tree ?? "")}</pre>
      </Show>

      <Show when={tab() === "First PR"}>
        <Show when={firstPr()}>
          <h3>{String(firstPr()?.title ?? "")}</h3>
          <p>{String(firstPr()?.scope ?? "")}</p>
          <p class="hint">estimate: {String(firstPr()?.time_estimate ?? "")}</p>
          <h4>Tasks</h4>
          <ol>
            <For each={(firstPr()?.tasks ?? []) as string[]}>{(t) => <li>{t}</li>}</For>
          </ol>
          <h4>Out of scope</h4>
          <ul>
            <For each={(firstPr()?.out_of_scope ?? []) as string[]}>{(t) => <li>{t}</li>}</For>
          </ul>
        </Show>
      </Show>

      <Show when={tab() === "JSON"}>
        <div class="row right gap">
          <button
            type="button"
            onClick={() => void copy(JSON.stringify({ stage2: state.stage2, stage3: bundle() }, null, 2), "JSON")}
          >
            Copy full spec JSON
          </button>
        </div>
        <pre class="artifact">{JSON.stringify({ stage2: state.stage2, stage3: bundle() }, null, 2)}</pre>
      </Show>
    </section>
  );
}
