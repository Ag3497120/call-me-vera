# Vera — technical reference

This is the reference for developers working on Vera itself, or who want
the detail behind what `vera guide` explains conversationally. If you
just want to *use* Vera, install it, run `vera init .`, connect the MCP
server, and say **"Vera guide"** to your agent instead of reading this.

## What's actually stored

Everything lives in one SQLite file (default `.vera_store.db`, WAL mode):

- **`event_log`** — the one content table. Every "Vera" turn fans out
  into separate `request` / `change` / `decision` / `result` /
  `interpretation` / `unresolved` rows (also `observation` /
  `assumption` are valid types, reserved for finer-grained future use)
  sharing one `turn_id`, tagged `author: claude | local | vera`. SQLite's
  own `rowid` (implicit — `id` is a TEXT primary key, not `INTEGER`) is
  the citation number every entry gets for free: `#12` means "the row
  with rowid 12." **Enforced append-only at the database level** —
  `UPDATE`/`DELETE` raise via SQLite triggers, not just "please don't."
- **`digests`** — AI-authored compressed summaries. Vera never writes one
  itself; an agent judges (via `vera_stats`' size estimate) that the
  uncompressed tail is getting large, reads the raw entries, and writes a
  digest citing specific numbers. `through_n` marks how far it reaches.
  Also append-only.
- **`control_log`** — what Vera decided *not* to save, and why: a
  duplicate suppressed, a save skipped while paused, a pause/resume. Kept
  separate from `event_log`'s content stream (a new row *type* there
  would need a CHECK-constraint rebuild; a bookkeeping table doesn't).
  Also append-only.
- **`session_control`** — one row, the pause switch (`vera pause` /
  `vera resume`). Persists across a restart on purpose; deliberately
  **not** carried by `sync` — pausing is a local, per-store decision.

Both/all authors point at the same file by default — no explicit sync
needed while agents share a filesystem. `vera sync` merges two
independently-grown stores for the case where they never did (a
genuinely different machine); it's idempotent (a second sync is a no-op)
and carries `event_log`, `digests`, and `control_log`.

## No interpretation

There is deliberately no fact extraction, constraint tracking, or
contradiction detection anywhere in this codebase. An earlier version had
all three (regex-based extraction feeding a keyword contradiction
checker); both were removed. Deciding what a piece of text means, or
whether it contradicts something recorded earlier, is exactly the kind of
judgment an LLM does well and a fixed rule set does not — so that
judgment belongs to whichever agent reads the memory, every time, not to
a heuristic baked into Vera. The one thing Vera does judge is structural,
not semantic: whether the uncompressed memory has grown past a character
count.

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
command on purpose — see `vera_stats`/`vera stats` for what actually
happened in the current process.

### Compression

`vera_stats`'s `size` field reports `uncompressed_entries`,
`uncompressed_chars`, `estimated_tokens` (a rough `chars/4` heuristic —
not exact for any real tokenizer, just a proxy), and `over_threshold`
against `threshold_tokens` (default 50,000). The count only covers what's
after the latest digest's `through_n` — the actual "how much would a
fresh agent have to load" question. The agent protocol tells the agent to
check this at session start; if it's over threshold, the agent reads the
raw entries, writes a digest citing the numbers it covers, tells the
user, and calls `vera_compress`. `vera_session_start` then shows that
digest plus only what's recorded after it, instead of the full history —
but nothing is deleted; every cited number stays reachable with
`vera_lookup`.

### Named stores — resuming the same memory across sessions/apps

Each MCP registration (or `--store` path) is its own file by default —
two registrations that were never deliberately pointed at the same path
have disjoint memories, even if both are called "vera". `claim_name()`
([vera/store.py](../vera/store.py)) fixes this: a name always resolves to
`~/.vera/stores/<name>.db` (`resolve_named_path()`), independent of
whatever `--store` path any given connection started with. Any tool call
that accepts a `name` parameter uses that fixed location instead of the
connection's own default store.

`claim_name(current_store, name)`:
- If the name is free: creates a store at the fixed path and `sync()`s
  everything from `current_store` into it (id-keyed, append-only-safe —
  `current_store`'s own file is untouched).
- If the name already belongs to a *different* store: refuses with
  `{"error": ..., "hint": 'vera_session_start(name="...")'}` rather than
  silently merging into a stranger's memory. Distinguished from a
  legitimate re-claim by checking whether any of `current_store`'s own
  `event_log` ids are already present at the target — only true if this
  exact store was synced there before.
- Re-claiming a name the current store already owns: idempotent
  success, and also pushes any newly recorded entries up to the shared
  copy (it's a real `sync()` every time, not a one-shot copy).

`vera_session_start`/`vera start` on a completely fresh, unnamed, empty
store returns a "NO MEMORY YET" prompt (in English only currently — not
yet localized across the 12 guide languages) instructing the agent to ask
the user for a name rather than a normal empty memory block.
`vera_guide`/`vera guide` accepts the same `name` and, when given,
appends a reminder of the exact reconnect call.

The MCP server process caches one `VeraStore` per name for its own
lifetime ([vera/mcp_tools.py](../vera/mcp_tools.py)'s `_resolve()`) —
reopening a fresh instance per call would mint a new `session_id` every
time (see Duplicate detection above) and silently break dedup for
anything routed through a name.

## Tools (MCP)

| Tool | What it does |
|------|---------------|
| `vera_session_start(lang)` | **call this first, every session** — the latest digest (if any) plus recent numbered entries, plus the agent protocol |
| `vera_record(request, author, change, reason, files, result, interpretation, unresolved, lang, model_timestamp)` | **call this when the user says "Vera"** — the structured, append-only, numbered capture; a repeat within the same connection is auto-suppressed |
| `vera_lookup(n)` | fetch one entry by its citation number |
| `vera_search(query, k)` | text search over entries and digests, results carry citation numbers |
| `vera_compress(text, through_n, author, lang)` | store an AI-authored digest citing specific entry numbers |
| `vera_pause(by)` / `vera_resume(by)` | stop/restart `vera_record` saving content |
| `vera_stats()` | entries, authors, size vs. compression threshold, pause state, last event/control decision |
| `vera_sync(remote_path)` | merge another store into this one |
| `vera_claim_name(name, source_name)` | name a memory so any session/app can resume it via `name=` on any other call |
| `vera_list_named_stores()` | list every claimed memory name |

Every tool above except `vera_guide`'s core text also accepts a `name`
parameter — pass it to operate on the named memory at
`~/.vera/stores/<name>.db` instead of this connection's own default
store; see "Named stores" above.

CLI equivalents exist for all of these — `vera <cmd>` (e.g. `vera start`,
`vera record --request ... --change ...`); see the README's Commands
section or `vera --help`.

## Supported guide languages

en, ja, zh, es, fr, de, ko, pt, ru, it, ar, hi — defined in
[vera/i18n.py](../vera/i18n.py). Structural field labels (REQUEST /
CHANGE / REASON / RESULT / STATE, and the memory-block labels) stay as
short, fixed English tokens across every language so they're a reliable
anchor for an agent regardless of prose language; only the explanatory
text and protocol rules are localized. `resolve_lang()` accepts a
language's own code, English name, native name, or a whole phrase
containing one ("de", "German", "Deutsch", "ドイツ語", "英語で開いて") and
falls back to English on anything unrecognized rather than erroring.

## Current limits

- **Explicit recording only (v0.1).** Nothing hooks into git commits,
  tool execution, or session-end yet — recording happens when an agent
  calls `vera_record`/`vera_session_start`, following the protocol text.
  This is deliberate: what gets remembered should be legible and trusted
  from day one.
- **`vera_session_start` shows a bounded window**, not full history —
  `vera_search` / `vera_lookup` reach further back on demand.
- **The "name this memory" prompt isn't localized yet** — it's returned
  in English regardless of `lang`, unlike the rest of the guide/protocol
  text. A small, tractable follow-up (a handful of short strings in
  `_LABELS`), just not done yet.
- **Naming is local-machine only.** `~/.vera/stores/` isn't itself synced
  anywhere — resuming a named memory from a genuinely different machine
  still needs `vera sync`, same as any other pair of stores.
- **The token estimate is a rough proxy** (`chars / 4`), not a real
  tokenizer count for any specific model — good enough to decide "this is
  clearly getting large," not precise.
- **Dedup and compression are both per-store, not cross-store** — syncing
  two stores does not re-run dedup against each other's history, and a
  digest written in one store doesn't automatically apply to another
  until synced.
