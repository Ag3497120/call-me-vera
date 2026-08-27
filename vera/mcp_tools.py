"""Vera MCP tools — shared, append-only, citable memory for AI coding agents.

Deliberately small: vera_guide explains everything else, so the tool
surface itself stays close to just "read the memory" / "write to it" /
"compress it when it's getting large" / "sync" / "name it so other
sessions/apps can find it".

MCP server name: "vera"
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .i18n import render_guide, render_project_state, resolve_lang
from .store import VeraStore, claim_name, init_store, list_named_stores, resolve_named_path


def vera_serve(store_path: str) -> int:
    """Start the Vera MCP server."""
    try:
        # mcp SDK v1: FastMCP lives at mcp.server.fastmcp.
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        try:
            # mcp SDK v2 renamed it to MCPServer at a new import path; the
            # decorator-based @mcp.tool()/.run() interface used below is
            # unchanged, so this is a drop-in alias, not a rewrite.
            from mcp.server.mcpserver import MCPServer as FastMCP
        except ImportError:
            print("MCP SDK not installed. Run:  pip install \"mcp[cli]\"")
            return 2

    path = Path(store_path)
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    store = init_store(path)

    # Named stores (see vera_claim_name) live at a fixed path derived only
    # from the name, independent of this process's own --store path — the
    # actual mechanism behind "resume this memory from a different
    # session/app". Cached per name for the life of this server process:
    # reopening a fresh VeraStore on every call would mint a new
    # session_id each time (VeraStore.session_id is generated once in
    # __init__), which would silently break same-session dedup for
    # anything routed through a name.
    _named_cache: Dict[str, VeraStore] = {}

    def _resolve(name: str) -> VeraStore:
        name = (name or "").strip()
        if not name:
            return store
        if name not in _named_cache:
            _named_cache[name] = VeraStore(resolve_named_path(name))
        return _named_cache[name]

    mcp = FastMCP("vera")

    @mcp.tool()
    def vera_guide(lang: str = "en", name: str = "") -> str:
        """Full onboarding explanation of Vera and how an agent should
        behave: what Vera is, how to call vera_session_start and
        vera_record, the agent behavior protocol, and available tools —
        in the requested language (code or name, e.g. "de", "German",
        "Deutsch", or a phrase like "ドイツ語"; unrecognized falls back to
        English). Call this once to learn how to use Vera; call
        vera_session_start at the beginning of every session instead —
        it's shorter and carries this store's actual current state.

        If this session is using a named memory (you passed `name` to
        vera_session_start earlier), pass that same `name` here too — the
        guide will remind you (and, if you say it out loud, the user) of
        the exact call to resume this memory from a different session or
        app: vera_session_start(name="...")."""
        text = render_guide(lang)
        resolved_name = (name or "").strip()
        if resolved_name:
            reconnect = f'\n\nThis session\'s memory is named "{resolved_name}". To resume it from any other session or app: vera_session_start(name="{resolved_name}") (CLI: `vera start --name {resolved_name}`).'
            text += reconnect
        return text

    @mcp.tool()
    def vera_session_start(lang: str = "en", name: str = "") -> str:
        """Call this BEFORE doing any work in a new session. Returns the
        latest compression digest (if one exists) plus everything
        recorded since it — or, if there's no digest yet, the most recent
        entries — each with a citation number, plus the agent behavior
        protocol, in the requested language. This is the hand-off point
        between agents/sessions: read it instead of asking the user to
        re-explain the project.

        Pass `name` to resume a specific NAMED memory (see
        vera_claim_name) instead of this connection's own default store
        — this is how two otherwise-unrelated sessions/apps end up
        sharing the same memory on purpose. If you omit `name` and this
        connection's own default store is completely empty and has never
        been named, the response asks you to get a name from the user
        instead of a normal (empty) memory block — ask, then call this
        again with that name to create it, or call vera_claim_name
        directly. Once a name is established, pass it on every
        vera_record / vera_lookup / vera_search / vera_compress /
        vera_stats call for the rest of this session — Vera does not
        remember it for you between calls."""
        target = _resolve(name)
        state = target.get_project_state()
        if not name and not state["name"] and state["size"]["uncompressed_entries"] == 0 and not state["digest"]:
            return (
                "NO MEMORY YET\n"
                "This looks like a brand-new, unnamed memory. Ask the user what "
                "they'd like to name it (e.g. \"project-vera\"), then call "
                "vera_session_start again with that as `name` — this creates it "
                "and means any other session or app can resume the exact same "
                "memory later by passing the same name, regardless of which "
                "store path or MCP registration it started with. If they'd "
                "rather not name it, proceeding without one is fine too — it "
                "just means this memory stays reachable only from this specific "
                "connection.\n\n" + render_project_state(state, lang)
            )
        return render_project_state(state, lang)

    @mcp.tool()
    def vera_claim_name(name: str, source_name: str = "") -> str:
        """Give a memory a name so any other session/app can resume it
        later by passing that same name to vera_session_start — instead
        of needing to know a filesystem path. Names must be 1-64 letters/
        digits/-/_, starting with a letter or digit.

        By default this claims the name for THIS connection's own default
        store (the one vera_session_start uses when you don't pass
        `name`). Pass `source_name` if you instead want to (re-)claim the
        name for a memory you're already addressing by another name.

        If the name is already used by a genuinely different memory, this
        refuses with an error and a hint to call
        vera_session_start(name="...") instead if you meant to resume
        that one — it never silently merges into a stranger's memory.
        Re-claiming a name this same memory already has (e.g. to push
        newly recorded entries up to the shared copy) is a safe, idempotent
        no-op success."""
        source = _resolve(source_name)
        result = claim_name(source, name)
        if "error" not in result:
            # Route this connection's future default-store calls to the
            # newly-named location too, so the rest of THIS session
            # doesn't need to keep passing `name` if it doesn't want to.
            _named_cache[result["name"]] = VeraStore(resolve_named_path(result["name"]))
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def vera_list_named_stores() -> str:
        """List every memory name currently claimed, in case you're not
        sure what a project's memory was named before."""
        return json.dumps(list_named_stores(), ensure_ascii=False)

    @mcp.tool()
    def vera_record(
        request: str,
        author: str = "claude",
        change: str = "",
        reason: str = "",
        files: str = "[]",
        result: str = "",
        interpretation: str = "",
        unresolved: str = "",
        lang: str = "en",
        model_timestamp: str = "",
        name: str = "",
    ) -> str:
        """Call this when the user says \"Vera\" mid-conversation. Distill
        the turn into REQUEST (what was asked), CHANGE (what you did, and
        `files` as a JSON array of paths touched), REASON (why you
        structured it that way), RESULT (what happened), interpretation
        (your own current understanding — also say it out loud to the
        user in your reply), and unresolved (anything left open). Vera
        does not interpret any of this; every non-empty field becomes its
        own permanent, numbered, append-only record for whichever agent
        reads it next.

        Pass `name` if this session is using a named memory (see
        vera_claim_name / vera_session_start's `name` parameter) — same
        name on every call for the rest of this session.

        Pass `model_timestamp` (ISO 8601, your own clock) if you have one
        — it sharpens duplicate detection across agents with different
        clocks; if omitted, Vera buckets its own receive time instead.
        Calling this again with the same author/request/result within a
        few seconds is recognized as the same save arriving twice and is
        NOT recorded again (response has `"duplicate_suppressed": true`,
        original turn_id returned) — safe to retry a call you're unsure
        went through."""
        try:
            files_list = json.loads(files) if files else []
        except (json.JSONDecodeError, TypeError) as exc:
            return json.dumps({"error": f"invalid JSON for files: {exc}"})
        result_dict = _resolve(name).record_turn(
            author=author, request=request, change=change, reason=reason,
            files=files_list, result=result, interpretation=interpretation,
            unresolved=unresolved, lang=resolve_lang(lang),
            model_timestamp=model_timestamp,
        )
        return json.dumps(result_dict, ensure_ascii=False)

    @mcp.tool()
    def vera_lookup(n: int, name: str = "") -> str:
        """Fetch one memory entry by its citation number — what a
        compression digest's "per #12" or a vera_search hit's "n" refers
        to. Pass `name` if this session is using a named memory."""
        entry = _resolve(name).lookup(n)
        if entry is None:
            return json.dumps({"error": f"no entry #{n}"})
        return json.dumps(entry, ensure_ascii=False)

    @mcp.tool()
    def vera_search(query: str, k: int = 10, name: str = "") -> str:
        """Text search over raw memory entries and compression digests,
        newest first. Every hit carries its citation number ("n") for
        vera_lookup. Pass `name` if this session is using a named
        memory."""
        return json.dumps(_resolve(name).search(query, k=k), ensure_ascii=False)

    @mcp.tool()
    def vera_compress(text: str, through_n: int = 0, author: str = "claude", lang: str = "en", name: str = "") -> str:
        """Store a compressed digest of the memory up to and including
        entry #through_n (0 or omitted = everything recorded so far).
        Vera never writes this itself — call vera_stats first; if
        `size.over_threshold` is true, the uncompressed tail is large
        enough that handing it to a fresh agent risks overflowing its
        context, and it's worth telling the user that before writing one.
        Read the raw entries (vera_search / vera_lookup), write a digest
        that cites specific numbers ("per #3, #7, #15: the project uses
        X..."), and pass that text here. Nothing gets deleted — the raw
        entries stay reachable via vera_lookup — but vera_session_start
        will show this digest plus only what's recorded after it, instead
        of the full history, until a newer digest supersedes it. Pass
        `name` if this session is using a named memory."""
        return json.dumps(
            _resolve(name).add_digest(text, through_n=through_n, author=author, lang=resolve_lang(lang)),
            ensure_ascii=False,
        )

    @mcp.tool()
    def vera_stats(name: str = "") -> str:
        """Everything about the store's current state: its name (if any),
        entry/author counts, the size estimate (and whether it's over the
        compression threshold — check this at session start), the last
        entry recorded, and the last control decision (currently:
        duplicate suppressed). Pass `name` if this session is using a
        named memory."""
        return json.dumps(_resolve(name).stats(), ensure_ascii=False)

    @mcp.tool()
    def vera_sync(remote_path: str, name: str = "") -> str:
        """Merge another Vera store (e.g. from a different machine that
        never shared this filesystem) into this one. Append-only and
        idempotent on both sides. Pass `name` to sync into a named memory
        instead of this connection's own default store."""
        return json.dumps(_resolve(name).sync(remote_path), ensure_ascii=False)

    mcp.run()
    return 0
