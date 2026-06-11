# Template presets and the OSS knowledge base

Both files are plain JSON, community-editable, and picked up at runtime — no
code changes, no rebuild.

## Template presets — `templates/presets.json`

```json
{
  "presets": [
    {
      "name": "Solo MVP",
      "optimize_for": "Fastest path to a working product for one builder: …",
      "default_language_tendency": "Go or Rust"
    }
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Shown in the constraint review screen; passed to Stage 2 as `TEMPLATE PRESET`. |
| `optimize_for` | yes | One paragraph; passed verbatim as `TEMPLATE OPTIMIZES FOR` — this is the lever that changes the architecture. |
| `default_language_tendency` | no | Documentation of where the matrix usually lands; informational. |

Built-in presets: **Solo MVP**, **API service**, **CLI tool**,
**Browser extension**, **Data pipeline**. All five produce different output
from the same transcript (verified in the release checklist).

A malformed presets file produces a clear `unknown-template` /
JSON-parse error in the UI — never a crash.

## OSS knowledge base — `templates/oss-knowledge-base.json`

Injected into Stage 2 so the model recommends mature libraries instead of
custom builds, and carries the **language selection matrix** (technical fit
only; an explicit user preference overrides it and is flagged).

- `domains.<area>[]` — `{ name, language, version, use_for }`. Versions are
  known-good minimums as of the file's `version` stamp.
- `language_selection_matrix[]` — `{ constraints, language, confidence }`,
  one row per constraint combination (see PRD §8.1).

Keep recommendations current: superseded libraries are removed. PRs that only
touch this file are the easiest way to contribute.
