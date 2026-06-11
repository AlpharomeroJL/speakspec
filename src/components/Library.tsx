/**
 * Session library (DOD 2.12): persisted sessions with full-text search,
 * re-open, and delete (removes all files). Renders fine at 0, 1, or 50+
 * sessions because it is a flat list.
 */
import { createResource, createSignal, For, Show } from "solid-js";
import {
  deleteSession,
  listSessions,
  loadSession,
  searchSessions,
  type SessionSummary,
} from "../lib/ipc";
import { errorText, openStoredSession, setError } from "../state";

export default function Library(props: { onClose: () => void }) {
  const [query, setQuery] = createSignal("");
  const [sessions, { refetch }] = createResource<SessionSummary[], string>(
    query,
    (q) => (q.trim() ? searchSessions(q) : listSessions()),
    { initialValue: [] },
  );

  async function open(id: string) {
    try {
      const stored = await loadSession(id);
      openStoredSession(stored.transcript, stored.spec_json, stored.dir);
      props.onClose();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function remove(id: string) {
    try {
      await deleteSession(id);
      void refetch();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <section class="panel">
      <div class="row gap">
        <h2>Session library</h2>
        <span class="spacer" />
        <button type="button" onClick={() => props.onClose()}>
          Close
        </button>
      </div>
      <input
        placeholder="Search transcripts and titles…"
        value={query()}
        data-testid="library-search"
        onInput={(e) => setQuery(e.currentTarget.value)}
      />
      <Show
        when={(sessions() ?? []).length > 0}
        fallback={<p class="hint">No sessions yet — record one and it lands here.</p>}
      >
        <ul class="session-list" data-testid="session-list">
          <For each={sessions()}>
            {(session) => (
              <li class="row gap">
                <button type="button" class="link" onClick={() => void open(session.id)}>
                  {session.title || "(untitled)"}
                </button>
                <span class="hint">
                  {new Date(session.created_at).toLocaleString()}
                  {session.has_spec ? "" : " — no spec"}
                </span>
                <span class="spacer" />
                <button type="button" onClick={() => void remove(session.id)}>
                  Delete
                </button>
              </li>
            )}
          </For>
        </ul>
      </Show>
    </section>
  );
}
