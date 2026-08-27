# Vera — technical reference

This is the reference for developers working on Vera itself, or who want
the detail behind what `vera guide` explains conversationally. If you
just want to *use* Vera, install it, run `vera init .`, connect the MCP
server, and say **"Vera guide"** to your agent instead of reading this.

## What's actually stored

Everything lives in one SQLite file (default `.vera_store.db`, WAL mode),
in two layers:

- **`events` / `facts` / `constraints` / `contradictions`** — the raw
  capture pipeline. `save_session()` records one event; `summarize()`
  extracts facts/decisions/constraints/todos/unresolved via regex
  (idempotent — content-hashed ids, re-running never duplicates rows).
  `check_consistency()` matches a proposed action/change against active
  constraints by keyword family (`stdlib`, `no external`, `local-first`,
  `deterministic` today — add more as your project's own recurring
  constraints show up). This is what powers `vera search` and `vera check`.

- **`event_log`** — the structured, per-turn log `record_turn()` writes.
  One call fans out into separate `request` / `change` / `decision` /
  `result` / `interpretation` / `unresolved` rows (also `observation` /
  `assumption` are valid types, reserved for finer-grained future use)
  sharing one `turn_id`, tagged `author: claude | local | vera`.
  **Enforced append-only at the database level** — SQLite triggers reject
  `UPDATE`/`DELETE` on this table outright, not just "please don't call
  that." `events.add_event()` similarly raises on a reused `session_id`
  instead of silently overwriting. `get_project_state()` reads the most
  recent rows here (plus active constraints/open contradictions) to build
  the PROJECT CONTEXT block `vera_session_start` returns.

- **`control_log`** — what Vera decided *not* to save, and why: a
  duplicate suppressed, a save skipped while paused, a pause/resume. Kept
  separate from `event_log`'s content stream (adding a new row *type*
  there would need a CHECK-constraint rebuild; a bookkeeping table
  doesn't), also append-only, also merged by `sync()`.

- **`session_control`** — one row, the pause switch (`vera pause` /
  `vera resume`). Persists across a restart on purpose; deliberately
  **not** carried by `sync()` — pausing is a local, per-store decision.

Both/all authors point at the same file by default — no explicit sync
needed while agents share a filesystem. `vera sync` merges two
independently-grown stores for the case where they never did (a
genuinely different machine); it's idempotent (a second sync is a no-op)
and carries the legacy tables, `event_log`, and `control_log`.

### Duplicate detection

Every `record_turn()` call computes
`fingerprint = sha256(author, session_id, time_key, request, result)`,
where `session_id` is generated fresh per `VeraStore` instance (one MCP
server process run, or one CLI invocation — see the comment on
`self.session_id` in [vera/store.py](../vera/store.py)) and `time_key` is
the caller's own `model_timestamp` if it gave one, otherwise the server's
receive time rounded to a 5-second bucket. A repeat of that exact
fingerprint returns `{"duplicate_suppressed": true, "turn_id": <original>}`
instead of inserting anything new, and the suppression itself is logged
to `control_log` — so a gap is traceable, not a silent no-op.

This deliberately dedups per *live connection*, not globally: two
identical `vera record` CLI invocations run as separate processes (and
thus separate `session_id`s) will **not** dedup against each other, even
seconds apart. The problem this solves is an agent retrying a tool call
within one running MCP server connection, not a human/script rerunning a
command on purpose — see `vera_status`/`vera status` for what actually
happened in the current process.

## Tools (MCP)

| Tool | What it does |
|------|---------------|
| `vera_guide(lang)` | full onboarding explanation, any supported language |
| `vera_session_start(lang)` | **call this first, every session** — current interpretation, active constraints, open contradictions, recent decisions/changes/unresolved/results, plus the agent protocol |
| `vera_record(request, author, change, reason, files, result, interpretation, unresolved, lang, model_timestamp)` | **call this when the user says "Vera"** — the structured, append-only capture; a repeat within the same connection is auto-suppressed, not double-saved |
| `vera_pause(by)` / `vera_resume(by)` | stop/restart `vera_record` saving content — use before a burst of activity you don't want recorded turn-by-turn |
| `vera_status()` | live state: paused or not, last event, last suppression/pause decision, running counts |
| `vera_add_interpretation(text, author, lang)` | standalone codebase-understanding snapshot, not tied to a turn |
| `vera_get_interpretation(n)` | most recent interpretation snapshots, for comparing how understanding has shifted |
| `vera_get_event_log(turn_id, type, k)` | raw event_log rows |
| `vera_search(query, k)` | text search across events, facts, constraints, summaries |
| `vera_check_consistency(current_action, current_proposal)` | check a proposal against every active constraint |
| `vera_save_session(...)` | lower-level raw capture (kept for simple/legacy use — prefer `vera_record` for anything triggered by "Vera") |
| `vera_list_facts` / `vera_add_constraint` / `vera_get_constraints` / `vera_list_contradictions` / `vera_get_session` / `vera_sync` / `vera_stats` | see docstrings in [vera/mcp_tools.py](../vera/mcp_tools.py) |

CLI equivalents exist for all of these — `vera <cmd>` (e.g. `vera start`,
`vera record --request ... --change ...`); see the README's Commands
section or `vera --help`.

## Supported guide languages

en, ja, zh, es, fr, de, ko, pt, ru, it, ar, hi — defined in
[vera/i18n.py](../vera/i18n.py). Structural field labels (REQUEST /
CHANGE / REASON / RESULT / STATE, and the PROJECT CONTEXT labels) stay as
short, fixed English tokens across every language so they're a reliable
anchor for an agent regardless of prose language; only the explanatory
text and protocol rules are localized. `resolve_lang()` accepts a
language's own code, English name, or native name ("de", "German",
"Deutsch", "ドイツ語" all resolve to `de`) and falls back to English on
anything unrecognized rather than erroring.

## Current limits

- **Deterministic, not an LLM call.** Extraction and contradiction
  checking are regex/keyword-based on purpose — reproducible, auditable,
  works offline. An optional LLM summarizer layered on top of the same
  event store is a natural v2, not a redesign of this one.
- **Explicit recording only (v0.1).** Nothing hooks into git commits,
  tool execution, or session-end yet — recording happens when an agent
  calls `vera_record`/`vera_session_start`, following the protocol text.
  This is deliberate: what gets remembered should be legible and trusted
  from day one.
- **`vera_session_start` shows a bounded recent window**, not full
  history — `vera_search` / `vera_get_event_log` reach further back on
  demand.
- **Contradiction detection is keyword-scoped**, not a general judge. It
  catches the "stdlib-only vs. add a dependency" class of drift well; a
  genuinely open-ended check needs either more keyword families in
  `check_consistency()` ([vera/store.py](../vera/store.py)) or an LLM
  judge layered on top later.
