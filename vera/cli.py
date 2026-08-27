"""vera — the call-me-vera CLI: shared, append-only, citable memory for
AI coding agents.

Deliberately small: `vera guide` explains everything else conversationally,
so this reference only needs the bare list.

Subcommands:
  vera init [dir]                   create the store in a project directory
  vera guide [--lang xx]            full onboarding explanation, any language
  vera start [--lang xx] [--name N] call BEFORE work: memory + agent protocol
  vera record --request "..." ...   the structured "Vera" capture
  vera lookup <n>                   fetch one entry by its citation number
  vera search <query>               text search, results carry citation numbers
  vera compress --text "..." [--through <n>]
                                     store an AI-authored digest citing numbers
  vera stats                        entries, size vs. compression threshold, state
  vera sync --remote <path>         merge two independently-grown stores
  vera claim-name <name>            name this memory so any session/app can resume it
  vera names                        list every claimed memory name
  vera mcp                          start the MCP server

Any command above also accepts --name <N> instead of --store <path> — this
routes it to a NAMED memory (see `vera claim-name`) at its fixed, shared
location (~/.vera/stores/<name>.db) rather than this invocation's own
--store path. That's the actual mechanism behind "resume this memory from
a different session/app": pass the same --name anywhere, get the same
memory.

Usage patterns:
  # From Claude (MCP tool call):
    vera_record(request="fix DXF labels", author="claude", change="...", ...)

  # From local CLI, the same structured capture:
    vera record --request "Fixed Japanese labels in QCAD export" \\
      --change "edited dxf.py TEXT entity encoding" --author local

  # Sync between Claude's machine and a local machine that never shared a filesystem:
    vera sync --local . --remote ../other-machine-checkout

  # Name a memory so it's reachable from anywhere by name:
    vera claim-name project-vera
    vera start --name project-vera        # from any other session/app

  Author tagging:
    "claude" = recorded from within Claude / MCP
    "local"  = recorded from local CLI (terminal)
    "vera"   = reserved for future non-agent-authored entries
    All authors write to the same SQLite store; sync merges deterministically.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

DEFAULT_STORE = ".vera_store.db"


def _store_path(args) -> Path:
    p = Path(getattr(args, "store", None) or DEFAULT_STORE)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def _open_store(args):
    """Resolve --name (a shared, named memory) or --store (a plain path)
    to an open VeraStore — --name takes precedence when both are given."""
    from .store import VeraStore, resolve_named_path

    name = (getattr(args, "name", None) or "").strip()
    if name:
        return VeraStore(resolve_named_path(name))
    return VeraStore(_store_path(args))


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_init(args) -> int:
    """Initialize a Vera store in the current project."""
    from .store import init_store

    path = Path(getattr(args, "dir", ".") or ".") / DEFAULT_STORE
    store = init_store(path)
    store.close()
    _print({"init": True, "path": str(path)})
    return 0


def cmd_guide(args) -> int:
    """Print the full Vera onboarding explanation in the requested language."""
    from .i18n import render_guide

    text = render_guide(getattr(args, "lang", "en"))
    name = (getattr(args, "name", None) or "").strip()
    if name:
        text += (
            f'\n\nThis session\'s memory is named "{name}". To resume it from '
            f'any other session or app: vera start --name {name} '
            f'(MCP: vera_session_start(name="{name}")).'
        )
    print(text)
    return 0


def cmd_start(args) -> int:
    """Call BEFORE doing any work in a new session: prints the latest
    compression digest (if any) plus everything since it, or the most
    recent entries if there's no digest yet, plus the agent protocol.
    If this is a brand-new, unnamed, empty memory, prints a prompt to
    name it instead (see `vera claim-name`) so it can be resumed by name
    from elsewhere."""
    from .i18n import render_project_state

    name = (getattr(args, "name", None) or "").strip()
    store = _open_store(args)
    try:
        state = store.get_project_state()
        lang = getattr(args, "lang", "en")
        if not name and not state["name"] and state["size"]["uncompressed_entries"] == 0 and not state["digest"]:
            print(
                "NO MEMORY YET\n"
                "This looks like a brand-new, unnamed memory. Consider naming it "
                "so it can be resumed from any other session or app:\n"
                "  vera claim-name <name>\n"
                "  vera start --name <name>   # from anywhere, to resume it\n\n"
            )
        print(render_project_state(state, lang))
    finally:
        store.close()
    return 0


def cmd_record(args) -> int:
    """The structured "Vera" capture: REQUEST/CHANGE/REASON/RESULT/STATE,
    each becoming its own permanent, numbered, append-only entry."""
    from .i18n import resolve_lang

    store = _open_store(args)
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
            model_timestamp=getattr(args, "model_timestamp", "") or "",
        )
        _print(result)
    finally:
        store.close()
    return 0


def cmd_lookup(args) -> int:
    """Fetch one entry by its citation number."""
    store = _open_store(args)
    try:
        entry = store.lookup(args.n)
        if entry is None:
            print(f"no entry #{args.n}")
            return 1
        _print(entry)
    finally:
        store.close()
    return 0


def cmd_search(args) -> int:
    """Search across memory entries and compression digests."""
    store = _open_store(args)
    try:
        _print(store.search(args.query, k=args.k or 10))
    finally:
        store.close()
    return 0


def cmd_compress(args) -> int:
    """Store an AI-authored compressed digest citing specific entry numbers."""
    from .i18n import resolve_lang

    store = _open_store(args)
    try:
        _print(store.add_digest(
            args.text, through_n=args.through or 0,
            author=args.author or "claude", lang=resolve_lang(args.lang),
        ))
    finally:
        store.close()
    return 0


def cmd_stats(args) -> int:
    """Entries, authors, size vs. compression threshold, last event."""
    store = _open_store(args)
    try:
        _print(store.stats())
    finally:
        store.close()
    return 0


def cmd_sync(args) -> int:
    """Sync two Vera stores (e.g. Claude's machine and local, reconciled after the fact)."""
    from .store import VeraStore

    local_path = Path(getattr(args, "local", ".") or ".") / DEFAULT_STORE
    remote_str = getattr(args, "remote", "") or ""
    if not remote_str:
        print("usage: vera sync --remote <path>")
        return 1
    remote_path = Path(remote_str) / DEFAULT_STORE

    local = VeraStore(local_path)
    try:
        merged = local.sync(remote_path)
        _print({"synced": True, "merged": merged})
    finally:
        local.close()
    return 0


def cmd_claim_name(args) -> int:
    """Give a memory a name so it can be resumed from any other
    session/app via `vera start --name <name>`, instead of needing a
    filesystem path. Refuses if the name is already used by a genuinely
    different memory; re-claiming a name this same memory already has is
    a safe no-op."""
    from .store import claim_name

    store = _open_store(args)
    try:
        _print(claim_name(store, args.claim_target))
    finally:
        store.close()
    return 0


def cmd_names(args) -> int:
    """List every memory name currently claimed."""
    from .store import list_named_stores

    _print(list_named_stores())
    return 0


def cmd_mcp(args) -> int:
    """Start the Vera MCP server. With --name, the server's own default
    store IS the named memory (~/.vera/stores/<name>.db) — every tool
    call operates on it automatically, with no need for the connected
    agent to pass `name` itself on each call. This is how an MCP
    registration (claude mcp add vera -- vera mcp --name X) converges
    with other registrations pointed at the same name, permanently,
    rather than relying on each session remembering to pass it."""
    from .mcp_tools import vera_serve
    from .store import resolve_named_path

    name = (getattr(args, "name", None) or "").strip()
    path = resolve_named_path(name) if name else _store_path(args)
    return vera_serve(str(path))


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="vera",
        description="Vera — shared, append-only, citable memory for AI coding agents.",
    )
    # --store/--name are accepted both before AND after the sub-command
    # (argparse only honors a parent-parser flag when it precedes the
    # sub-command name, and "vera mcp --store X" is the natural order
    # people actually type) — so they're declared on a shared parent,
    # included in every sub-parser via `parents=[...]`, *and* kept on the
    # top-level parser for the "--store X <cmd>" order too.
    #
    # default=SUPPRESS here is load-bearing: if the sub-parser's copy had
    # a real default, argparse would apply it to the merged namespace
    # whenever the flag isn't repeated after the sub-command name — even
    # though the top-level parser already parsed a real value for it —
    # silently discarding "vera --store X <cmd>" and falling back to
    # DEFAULT_STORE. SUPPRESS means the sub-parser only ever touches
    # args.store/args.name when the flag actually appears after the
    # sub-command, leaving the top-level-parsed value alone otherwise.
    store_parent = argparse.ArgumentParser(add_help=False)
    store_parent.add_argument("--store", default=argparse.SUPPRESS, help="Vera store path")
    store_parent.add_argument("--name", default=argparse.SUPPRESS, help="use a named, shared memory instead of --store")
    ap.add_argument("--store", default=DEFAULT_STORE, help="Vera store path")
    ap.add_argument("--name", default=None, help="use a named, shared memory instead of --store")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create the store in a project directory", parents=[store_parent])
    p.add_argument("dir", nargs="?", default=".")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("guide", help="full onboarding explanation, any language", parents=[store_parent])
    p.add_argument("--lang", default="en", help="output language (code or name, e.g. de / German / Deutsch)")
    p.set_defaults(fn=cmd_guide)

    p = sub.add_parser("start", help="call BEFORE work: memory + agent protocol", parents=[store_parent])
    p.add_argument("--lang", default="en", help="output language (code or name, e.g. de / German / Deutsch)")
    p.set_defaults(fn=cmd_start)

    p = sub.add_parser(
        "record",
        help='the structured "Vera" capture: REQUEST/CHANGE/REASON/RESULT/STATE',
        parents=[store_parent],
    )
    p.add_argument("--request", required=True, help="what was asked (REQUEST)")
    p.add_argument("--author", default="local", choices=["claude", "local", "vera"])
    p.add_argument("--change", default="", help="what you did (CHANGE)")
    p.add_argument("--reason", default="", help="why you structured it that way (REASON)")
    p.add_argument("--files", default=None, help="JSON array of file paths touched")
    p.add_argument("--result", default="", help="what happened (RESULT)")
    p.add_argument("--interpretation", default="", help="current understanding (STATE)")
    p.add_argument("--unresolved", default="", help="anything left open")
    p.add_argument("--lang", default="en", help="language this turn is recorded in")
    p.add_argument("--model-timestamp", dest="model_timestamp", default="",
                    help="ISO 8601 timestamp from the calling agent's own clock, "
                         "if it has one — sharpens duplicate detection; optional")
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("lookup", help="fetch one entry by its citation number", parents=[store_parent])
    p.add_argument("n", type=int)
    p.set_defaults(fn=cmd_lookup)

    p = sub.add_parser("search", help="text search, results carry citation numbers", parents=[store_parent])
    p.add_argument("query")
    p.add_argument("-k", type=int, default=10)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("compress", help="store an AI-authored digest citing entry numbers", parents=[store_parent])
    p.add_argument("--text", required=True, help="the digest text, citing entry numbers (e.g. \"per #3, #7: ...\")")
    p.add_argument("--through", type=int, default=0, help="covers entries up to this number (0 = everything so far)")
    p.add_argument("--author", default="claude", choices=["claude", "local", "vera"])
    p.add_argument("--lang", default="en")
    p.set_defaults(fn=cmd_compress)

    p = sub.add_parser("stats", help="entries, size vs. threshold, last event", parents=[store_parent])
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("sync", help="sync two Vera stores (local ↔ Claude)", parents=[store_parent])
    p.add_argument("--local", default=".")
    p.add_argument("--remote", default="")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("claim-name", help="name this memory so it can be resumed from anywhere", parents=[store_parent])
    p.add_argument("claim_target", metavar="name")
    p.set_defaults(fn=cmd_claim_name)

    p = sub.add_parser("names", help="list every claimed memory name", parents=[store_parent])
    p.set_defaults(fn=cmd_names)

    p = sub.add_parser("mcp", help="start the Vera MCP server", parents=[store_parent])
    p.set_defaults(fn=cmd_mcp)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
