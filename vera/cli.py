"""vera — the call-me-vera CLI: shared, append-only project memory for AI
coding agents.

Subcommands:
  vera init [dir]                create the store in a project directory
  vera start [--lang xx]         call BEFORE work: project state + protocol
  vera record --request "..." [--change ...] [--reason ...] ...
                                  the structured "Vera" capture (REQUEST/
                                  CHANGE/REASON/RESULT/STATE)
  vera guide [--lang xx]         full onboarding explanation, any language
  vera save <prompt>             lower-level raw capture (author=local)
  vera summarize <sid>           generate summary for a session
  vera search <query>            search across all records
  vera check --action <a>        consistency check against constraints
  vera facts                     list recorded facts
  vera constraints                list active constraints
  vera contradictions            list detected contradictions
  vera interpretation            latest codebase-interpretation snapshots
  vera event-log                 raw append-only event_log rows
  vera mcp                       start the Vera MCP server
  vera sync                      sync two independently-grown stores

Usage patterns:
  # From Claude (MCP tool call):
    vera_record(request="fix DXF labels", author="claude", change="...", ...)

  # From local CLI, the same structured capture:
    vera record --request "Fixed Japanese labels in QCAD export" \\
      --change "edited dxf.py TEXT entity encoding" --author local

  # Sync between Claude's machine and a local machine that never shared a filesystem:
    vera sync --local . --remote ../other-machine-checkout

  Author tagging:
    "claude" = recorded from within Claude / MCP
    "local"  = recorded from local CLI (terminal)
    "vera"   = a standalone interpretation snapshot, not tied to a turn
    All authors write to the same SQLite store; sync merges deterministically.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


DEFAULT_STORE = ".vera_store.db"


def _store_path(args) -> Path:
    p = Path(getattr(args, "store", None) or DEFAULT_STORE)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_session_init(args) -> int:
    """Initialize a Vera store in the current project."""
    from .store import init_store

    path = Path(getattr(args, "dir", ".") or ".") / DEFAULT_STORE
    store = init_store(path)
    store.close()
    _print({"init": True, "path": str(path)})
    return 0


def cmd_session_save(args) -> int:
    """Save a session event from the local side."""
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        sid = store.save_session(
            author=args.author or "local",
            user_prompt=args.prompt,
            tool_calls=json.loads(args.tool_calls) if args.tool_calls else [],
            tool_results=json.loads(args.tool_results) if args.tool_results else [],
            git_diff=args.diff or "",
            actions=json.loads(args.actions) if args.actions else [],
            observations=json.loads(args.observations) if args.observations else [],
            working_directory=str(Path.cwd()),
        )
        # Auto-generate summary
        store.summarize(sid)
        _print({"session_id": sid, "author": args.author or "local", "saved": True})
    finally:
        store.close()
    return 0


def cmd_session_start(args) -> int:
    """Call BEFORE doing any work in a new session: prints the project's
    current state (interpretation/constraints/contradictions/recent
    decisions & changes/unresolved) plus the agent behavior protocol."""
    from .i18n import render_project_state
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        state = store.get_project_state()
        print(render_project_state(state, getattr(args, "lang", "en")))
    finally:
        store.close()
    return 0


def cmd_session_guide(args) -> int:
    """Print the full Vera onboarding explanation in the requested language."""
    from .i18n import render_guide

    print(render_guide(getattr(args, "lang", "en")))
    return 0


def cmd_session_record(args) -> int:
    """The structured "Vera" capture: REQUEST/CHANGE/REASON/RESULT/STATE,
    each becoming its own permanent, append-only event."""
    from .i18n import resolve_lang
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        result = store.record_turn(
            author=args.author or "local",
            request=args.request,
            change=args.change or "",
            reason=args.reason or "",
            files=json.loads(args.files) if args.files else [],
            result=args.result or "",
            interpretation=args.interpretation or "",
            unresolved=args.unresolved or "",
            lang=resolve_lang(args.lang),
        )
        _print(result)
    finally:
        store.close()
    return 0


def cmd_interpretation(args) -> int:
    """List the most recent codebase-interpretation snapshots."""
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        _print(store.get_latest_interpretation(n=args.n or 2))
    finally:
        store.close()
    return 0


def cmd_add_interpretation(args) -> int:
    """Record a standalone codebase-interpretation snapshot."""
    from .i18n import resolve_lang
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        eid = store.add_interpretation(
            args.text, author=args.author or "vera", lang=resolve_lang(args.lang)
        )
        _print({"event_id": eid})
    finally:
        store.close()
    return 0


def cmd_event_log(args) -> int:
    """List raw append-only event_log rows."""
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        _print(store.get_event_log(turn_id=args.turn or "", type_=args.type or "", k=args.k or 50))
    finally:
        store.close()
    return 0


def cmd_session_summarize(args) -> int:
    """Generate a summary for a session."""
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        s = store.summarize(args.session_id)
        if not s:
            print(f"session not found: {args.session_id}", file=sys.stderr)
            return 1
        _print({
            "session_id": s.session_id,
            "facts": s.facts,
            "decisions": s.decisions,
            "constraints": s.constraints,
            "todos": s.todos,
            "unresolved": s.unresolved,
        })
    finally:
        store.close()
    return 0


def cmd_search(args) -> int:
    """Search across Vera records."""
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        results = store.search(args.query, k=args.k or 10)
        _print(results)
    finally:
        store.close()
    return 0


def cmd_check(args) -> int:
    """Check consistency of current action against stored constraints."""
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        result = store.check_consistency(
            current_action=args.action or "",
            current_proposal=args.proposal or "",
        )
        _print(result)
    finally:
        store.close()
    return 0


def cmd_facts(args) -> int:
    """List recorded facts."""
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        result = store.list_facts(category=args.category or "")
        _print(result)
    finally:
        store.close()
    return 0


def cmd_constraints(args) -> int:
    """List active constraints."""
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        result = store.get_constraints()
        _print(result)
    finally:
        store.close()
    return 0


def cmd_contradictions(args) -> int:
    """List detected contradictions."""
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        result = store.list_contradictions(resolved_only=args.resolved or False)
        _print(result)
    finally:
        store.close()
    return 0


def cmd_stats(args) -> int:
    """Vera store statistics."""
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        result = store.report()
        _print(result)
    finally:
        store.close()
    return 0


def cmd_add_constraint(args) -> int:
    """Add a constraint manually."""
    from .store import VeraStore

    store = VeraStore(_store_path(args))
    try:
        cid = store.add_constraint(args.text, source_session=getattr(args, "session", ""))
        _print({"constraint_id": cid, "text": args.text})
    finally:
        store.close()
    return 0


def cmd_mcp(args) -> int:
    """Start the Vera MCP server."""
    from .mcp_tools import vera_serve

    return vera_serve(str(_store_path(args)))


def cmd_sync(args) -> int:
    """Sync two Vera stores (local ↔ Claude)."""
    from .store import VeraStore

    local_path = Path(getattr(args, "local", ".") or ".") / DEFAULT_STORE
    remote_str = getattr(args, "remote", "") or ""
    if not remote_str:
        # No remote specified — nothing to sync
        print("usage: vera sync --remote <path>")
        return 1
    remote_path = Path(remote_str) / DEFAULT_STORE

    local = VeraStore(local_path)
    remote = VeraStore(remote_path)
    try:
        merged = local.sync(remote.db_path)
        _print({"synced": True, "merged": merged})
    finally:
        local.close()
        remote.close()
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="vera",
        description="Vera — shared, append-only project memory for AI coding agents.",
    )
    # --store is accepted both before AND after the sub-command (argparse
    # only honors a parent-parser flag when it precedes the sub-command
    # name, and "vera mcp --store X" is the natural order people actually
    # type) — so it's declared on a shared parent, included in every
    # sub-parser via `parents=[...]`, *and* kept on the top-level parser
    # for the "--store X <cmd>" order too.
    store_parent = argparse.ArgumentParser(add_help=False)
    store_parent.add_argument("--store", default=DEFAULT_STORE, help="Vera store path")
    ap.add_argument("--store", default=DEFAULT_STORE, help="Vera store path")

    sub = ap.add_subparsers(dest="cmd", required=True)

    # init
    p = sub.add_parser("init", help="create Vera store in a project directory", parents=[store_parent])
    p.add_argument("dir", nargs="?", default=".")
    p.set_defaults(fn=cmd_session_init)

    # save
    p = sub.add_parser("save", help="record a session event (from local side)", parents=[store_parent])
    p.add_argument("prompt", help="user prompt / description")
    p.add_argument("--author", default="local", choices=["claude", "local"])
    p.add_argument("--tool-calls", default=None, help="JSON array of tool call strings")
    p.add_argument("--tool-results", default=None, help="JSON array of tool result strings")
    p.add_argument("--diff", default="", help="git diff output")
    p.add_argument("--actions", default=None, help="JSON array of action descriptions")
    p.add_argument("--observations", default=None, help="JSON array of observations")
    p.set_defaults(fn=cmd_session_save)

    # start
    p = sub.add_parser("start", help="call BEFORE work: project state + agent protocol", parents=[store_parent])
    p.add_argument("--lang", default="en", help="output language (code or name, e.g. de / German / Deutsch)")
    p.set_defaults(fn=cmd_session_start)

    # guide
    p = sub.add_parser("guide", help="full onboarding explanation, any language", parents=[store_parent])
    p.add_argument("--lang", default="en", help="output language (code or name, e.g. de / German / Deutsch)")
    p.set_defaults(fn=cmd_session_guide)

    # record
    p = sub.add_parser(
        "record",
        help='the structured "Vera" capture: REQUEST/CHANGE/REASON/RESULT/STATE',
        parents=[store_parent],
    )
    p.add_argument("--request", required=True, help="what was asked (REQUEST)")
    p.add_argument("--author", default="local", choices=["claude", "local"])
    p.add_argument("--change", default="", help="what you did (CHANGE)")
    p.add_argument("--reason", default="", help="why you structured it that way (REASON)")
    p.add_argument("--files", default=None, help="JSON array of file paths touched")
    p.add_argument("--result", default="", help="what happened (RESULT)")
    p.add_argument("--interpretation", default="", help="current understanding of the codebase (STATE)")
    p.add_argument("--unresolved", default="", help="anything left open")
    p.add_argument("--lang", default="en", help="language this turn is recorded in")
    p.set_defaults(fn=cmd_session_record)

    # interpretation
    p = sub.add_parser("interpretation", help="latest codebase-interpretation snapshots", parents=[store_parent])
    p.add_argument("-n", type=int, default=2, help="how many snapshots, newest first")
    p.set_defaults(fn=cmd_interpretation)

    # add-interpretation
    p = sub.add_parser("add-interpretation", help="record a standalone interpretation snapshot", parents=[store_parent])
    p.add_argument("text")
    p.add_argument("--author", default="vera", choices=["claude", "local", "vera"])
    p.add_argument("--lang", default="en")
    p.set_defaults(fn=cmd_add_interpretation)

    # event-log
    p = sub.add_parser("event-log", help="raw append-only event_log rows", parents=[store_parent])
    p.add_argument("--turn", default="", help="filter by turn_id")
    p.add_argument("--type", default="", help="filter by type (request|change|decision|result|observation|assumption|unresolved|interpretation)")
    p.add_argument("-k", type=int, default=50)
    p.set_defaults(fn=cmd_event_log)

    # summarize
    p = sub.add_parser("summarize", help="generate summary for a session", parents=[store_parent])
    p.add_argument("session_id")
    p.set_defaults(fn=cmd_session_summarize)

    # search
    p = sub.add_parser("search", help="search across all Vera records", parents=[store_parent])
    p.add_argument("query")
    p.add_argument("-k", type=int, default=10)
    p.set_defaults(fn=cmd_search)

    # check
    p = sub.add_parser("check", help="check consistency against stored constraints", parents=[store_parent])
    p.add_argument("--action", default="", help="current action being taken")
    p.add_argument("--proposal", default="", help="current proposal under consideration")
    p.set_defaults(fn=cmd_check)

    # facts
    p = sub.add_parser("facts", help="list recorded facts", parents=[store_parent])
    p.add_argument("--category", default="")
    p.set_defaults(fn=cmd_facts)

    # constraints
    p = sub.add_parser("constraints", help="list active constraints", parents=[store_parent])
    p.set_defaults(fn=cmd_constraints)

    # add-constraint
    p = sub.add_parser("add-constraint", help="add a constraint manually", parents=[store_parent])
    p.add_argument("text")
    p.add_argument("--session", default="", help="source session ID")
    p.set_defaults(fn=cmd_add_constraint)

    # contradictions
    p = sub.add_parser("contradictions", help="list detected contradictions", parents=[store_parent])
    p.add_argument("--resolved", action="store_true")
    p.set_defaults(fn=cmd_contradictions)

    # stats
    p = sub.add_parser("stats", help="Vera store statistics", parents=[store_parent])
    p.set_defaults(fn=cmd_stats)

    # mcp
    p = sub.add_parser("mcp", help="start the Vera MCP server", parents=[store_parent])
    p.set_defaults(fn=cmd_mcp)

    # sync
    p = sub.add_parser("sync", help="sync two Vera stores (local ↔ Claude)", parents=[store_parent])
    p.add_argument("--local", default=".")
    p.add_argument("--remote", default="")
    p.set_defaults(fn=cmd_sync)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
