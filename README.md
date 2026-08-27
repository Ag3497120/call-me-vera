# call me vera

Shared, append-only project memory for AI coding agents.

Vera lets Claude, local models, Codex, and other MCP-compatible agents
continue the same project without sharing their sessions — by reading and
writing one event log instead.

```
Claude ──┐
Local ────┼── same .vera_store.db (SQLite, WAL) ── event_log (append-only)
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
* how to start a session (`vera_session_start` — reads project state before
  any work begins)
* how recording works (`vera_record` — call it whenever the user says
  "Vera")
* the exact behavior protocol the agent should follow
* how to switch languages (12 supported: en, ja, zh, es, fr, de, ko, pt,
  ru, it, ar, hi — ask in any of them, e.g. "Start Vera guide in German"
  or 「ドイツ語でVera guideを起動して」)

## Core idea

Sessions are temporary. The project memory is not.

```
Claude → Vera → Local → Vera → Claude
```

Every "Vera" turn is distilled into REQUEST / CHANGE / REASON / RESULT /
STATE and appended as separate, permanent records — never overwritten.
The append-only guarantee is enforced by the database itself (SQLite
triggers reject `UPDATE`/`DELETE` on the event log), not just a promise
in the code.

A new session calls `vera_session_start` first and gets back exactly what
it needs: the project's current state, active constraints, open
contradictions, and recent decisions — not the full history, and not
nothing.

## Why not just a memory MCP

Most memory MCPs answer "what did we say." Vera is built around a
narrower, more specific question: **what did an agent *do*, why, and does
what's being proposed now contradict something decided before?**

```bash
vera add-constraint "no external dependency — stdlib only"
# ... 40 sessions later, in a different agent:
vera check --action "install ezdxf via pip" \
  --proposal "add ezdxf as a dependency to fix DXF text rendering"
# -> {"status": "CONTRADICTION", "constraint": "no external dependency — stdlib only", ...}
```

Nothing here required the constraint to still be in context — it was on
disk, in a file every agent working on the project can read.

## Commands

```
vera init [dir]                 create the store in a project directory
vera start [--lang xx]          call BEFORE work: project state + protocol
vera guide [--lang xx]          full onboarding explanation, any language
vera record --request "..."     the structured "Vera" capture
vera search <query>             search across events, facts, constraints
vera check --action <a>         consistency check against constraints
vera constraints                list active constraints
vera interpretation             latest codebase-interpretation snapshots
vera event-log                  raw append-only event log
vera mcp                        start the MCP server
vera sync --remote <path>       merge two independently-grown stores
```

Full reference: [docs/VERA_SESSION.md](docs/VERA_SESSION.md).

## Design

* **Extraction and contradiction-checking are deterministic** — plain
  regex/keyword rules, not an LLM call. Reproducible, auditable, works
  offline. An LLM summarizer on top is a natural v2, not a redesign.
* **Explicit, not automatic, by design (v0.1).** Recording happens when
  the user says "Vera" or an agent calls `vera_record`. No hooks into git
  commits or tool calls yet — what gets remembered should be legible from
  day one, not inferred.
* **Same file, not routine sync.** Claude and a local agent sharing a
  filesystem write to the same SQLite store directly. `vera sync` exists
  for the case where two stores genuinely never shared a filesystem (a
  different machine) and need to reconcile afterward.

## License

MIT
