# call me vera

Shared, append-only, citable memory for AI coding agents.

Vera lets Claude, local models, Codex, and other MCP-compatible agents
continue the same project without sharing their sessions — by reading and
writing one memory log instead. Vera does not interpret what it stores:
no fact extraction, no contradiction detection. Every entry just gets a
citable number; making sense of it is the agent's job.

```
Claude ──┐
Local ────┼── same .vera_store.db (SQLite, WAL) ── numbered, append-only memory
Codex ────┘        author: claude | local | vera
```

## Install

```bash
pip install -e ".[mcp]"
```

## Start

```bash
vera init .
claude mcp add vera -- vera mcp --store ./.vera_store.db
```

Connect Vera to your agent. Then say:

> Vera guide

Vera explains itself — directly to the agent, in whichever language you
asked in:

* what Vera is and how sessions continue across agents
* how to start a session (`vera_session_start` — reads the memory before
  any work begins)
* how recording works (`vera_record` — call it whenever the user says
  "Vera")
* the exact behavior protocol the agent should follow, including citing
  memory by number and watching for when compression is worth suggesting
* how to switch languages (12 supported: en, ja, zh, es, fr, de, ko, pt,
  ru, it, ar, hi — ask in any of them, e.g. "Start Vera guide in German"
  or 「ドイツ語でVera guideを起動して」)

## Core idea

Sessions are temporary. The project memory is not.

```
Claude → Vera → Local → Vera → Claude
```

A new session calls `vera_session_start` and gets back the memory it
needs to continue: the latest compression digest (if there is one) plus
everything recorded since, or just the most recent entries if there's no
digest yet — every one of them numbered.

Every "Vera" turn is distilled into REQUEST / CHANGE / REASON / RESULT /
STATE and appended as separate, permanent, numbered records — never
overwritten. The append-only guarantee is enforced by the database itself
(SQLite triggers reject `UPDATE`/`DELETE`), not just a promise in the code.

## Why not fact extraction or contradiction detection

An earlier version of Vera tried regex-based fact/constraint extraction
and a keyword contradiction checker. Both were removed on purpose: deciding
what a piece of text *means*, or whether it contradicts something else, is
exactly the kind of judgment an LLM is good at and a fixed set of rules
is not. Vera's job is narrower and more reliable — record what happened,
in order, permanently, with a citable number on everything — and hand
that back to whichever agent asks next. What the agent does with it is up
to the agent: compare it against what it's about to do, summarize it,
cite specific entries back to the user. Vera stays out of the way.

```bash
vera record --request "switch auth to OAuth" --result "done" \
  --interpretation "auth/ now owns all authentication"
vera lookup 4
# {"n": 4, "type": "interpretation", "content": "auth/ now owns all authentication", ...}
```

## Compression, when the memory gets large

`vera stats` reports whether the *uncompressed* memory has grown past a
token-count threshold — the actual "would loading this into a fresh
agent's context overflow it" question, as a character count, not an
opinion about content. When it has, the agent is expected to read
through the memory, write a digest that cites specific entry numbers
("per #3, #7: the project uses X"), and tell the user compression may
help before calling `vera compress`. Nothing gets deleted — every cited
entry stays reachable with `vera lookup` — but a new session's starting
context stays small: `vera start` shows the latest digest plus only
what's been recorded since it, not the full history.

## Commands

```
vera init [dir]                 create the store in a project directory
vera guide [--lang xx]          full onboarding explanation, any language
vera start [--lang xx]          call BEFORE work: memory + agent protocol
vera record --request "..."     the structured "Vera" capture (auto-dedups a retry)
vera lookup <n>                 fetch one entry by its citation number
vera search <query>             text search, results carry citation numbers
vera compress --text "..."      store an AI-authored digest citing entry numbers
vera pause / vera resume        stop/restart recording for a burst of activity
vera stats                      entries, size vs. compression threshold, state
vera sync --remote <path>       merge two independently-grown stores
vera mcp                        start the MCP server
```

Full reference: [docs/VERA_SESSION.md](docs/VERA_SESSION.md).

## Design

* **No interpretation, on purpose.** No fact extraction, no constraint
  tracking, no contradiction detection — the agent reading the memory
  does all of that. Vera's own judgment is limited to something
  structural and deterministic: a character count against a compression
  threshold, not an opinion about what anything means.
* **Explicit, not automatic (v0.1).** Recording happens when the user
  says "Vera" or an agent calls `vera_record`. No hooks into git commits
  or tool calls yet — what gets remembered should be legible from day
  one, not inferred.
* **Same file, not routine sync.** Claude and a local agent sharing a
  filesystem write to the same SQLite store directly. `vera sync` exists
  for the case where two stores genuinely never shared a filesystem (a
  different machine) and need to reconcile afterward.
* **A retried save doesn't become two entries.** An agent re-sending the
  same `vera_record` call — different models, different clocks — is
  recognized by a fingerprint over (author, session, request, result) and
  suppressed, not duplicated; the suppression itself is logged, never
  silently dropped. `vera pause` stops recording for a burst of activity
  you don't want captured turn-by-turn.

## License

MIT
