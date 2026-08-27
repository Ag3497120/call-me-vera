"""Vera MCP tools — shared, append-only, citable memory for AI coding agents.

Deliberately small: vera_guide explains everything else, so the tool
surface itself stays close to just "read the memory" / "write to it" /
"compress it when it's getting large" / "pause/resume" / "sync".

MCP server name: "vera"
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .i18n import render_guide, render_project_state, resolve_lang
from .store import VeraStore, init_store


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

    mcp = FastMCP("vera")

    @mcp.tool()
    def vera_guide(lang: str = "en") -> str:
        """Full onboarding explanation of Vera and how an agent should
        behave: what Vera is, how to call vera_session_start and
        vera_record, the agent behavior protocol, and available tools —
        in the requested language (code or name, e.g. "de", "German",
        "Deutsch", or a phrase like "ドイツ語"; unrecognized falls back to
        English). Call this once to learn how to use Vera; call
        vera_session_start at the beginning of every session instead —
        it's shorter and carries this store's actual current state."""
        return render_guide(lang)

    @mcp.tool()
    def vera_session_start(lang: str = "en") -> str:
        """Call this BEFORE doing any work in a new session. Returns the
        latest compression digest (if one exists) plus everything
        recorded since it — or, if there's no digest yet, the most recent
        entries — each with a citation number, plus the agent behavior
        protocol, in the requested language. This is the hand-off point
        between agents/sessions: read it instead of asking the user to
        re-explain the project."""
        state = store.get_project_state()
        return render_project_state(state, lang)

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

        Pass `model_timestamp` (ISO 8601, your own clock) if you have one
        — it sharpens duplicate detection across agents with different
        clocks; if omitted, Vera buckets its own receive time instead.
        Calling this again with the same author/request/result within a
        few seconds is recognized as the same save arriving twice and is
        NOT recorded again (response has `"duplicate_suppressed": true`,
        original turn_id returned) — safe to retry a call you're unsure
        went through. If recording is currently paused (`vera_pause`),
        this returns `{"paused": true, "skipped": true}` and records
        nothing; call `vera_resume` first."""
        try:
            files_list = json.loads(files) if files else []
        except (json.JSONDecodeError, TypeError) as exc:
            return json.dumps({"error": f"invalid JSON for files: {exc}"})
        result_dict = store.record_turn(
            author=author, request=request, change=change, reason=reason,
            files=files_list, result=result, interpretation=interpretation,
            unresolved=unresolved, lang=resolve_lang(lang),
            model_timestamp=model_timestamp,
        )
        return json.dumps(result_dict, ensure_ascii=False)

    @mcp.tool()
    def vera_lookup(n: int) -> str:
        """Fetch one memory entry by its citation number — what a
        compression digest's "per #12" or a vera_search hit's "n" refers
        to."""
        entry = store.lookup(n)
        if entry is None:
            return json.dumps({"error": f"no entry #{n}"})
        return json.dumps(entry, ensure_ascii=False)

    @mcp.tool()
    def vera_search(query: str, k: int = 10) -> str:
        """Text search over raw memory entries and compression digests,
        newest first. Every hit carries its citation number ("n") for
        vera_lookup."""
        return json.dumps(store.search(query, k=k), ensure_ascii=False)

    @mcp.tool()
    def vera_compress(text: str, through_n: int = 0, author: str = "claude", lang: str = "en") -> str:
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
        of the full history, until a newer digest supersedes it."""
        return json.dumps(store.add_digest(text, through_n=through_n, author=author, lang=resolve_lang(lang)), ensure_ascii=False)

    @mcp.tool()
    def vera_pause(by: str = "local") -> str:
        """Stop vera_record from saving content until vera_resume is
        called — use this before a burst of agent activity you don't want
        recorded turn-by-turn (e.g. bulk automated processing), then call
        vera_resume and vera_record once at the end for the result that
        matters. Skipped attempts while paused are still logged (see
        vera_stats) so a gap is traceable, not silently missing. Persists
        across a server restart until explicitly resumed."""
        return json.dumps(store.pause(by=by), ensure_ascii=False)

    @mcp.tool()
    def vera_resume(by: str = "local") -> str:
        """Undo vera_pause — vera_record saves normally again."""
        return json.dumps(store.resume(by=by), ensure_ascii=False)

    @mcp.tool()
    def vera_stats() -> str:
        """Everything about the store's current state: entry/author
        counts, the size estimate (and whether it's over the compression
        threshold — check this at session start), paused or not, the last
        entry recorded, and the last control decision (duplicate
        suppressed / paused skip / pause / resume)."""
        return json.dumps(store.stats(), ensure_ascii=False)

    @mcp.tool()
    def vera_sync(remote_path: str) -> str:
        """Merge another Vera store (e.g. from a different machine that
        never shared this filesystem) into this one. Append-only and
        idempotent on both sides."""
        return json.dumps(store.sync(remote_path), ensure_ascii=False)

    mcp.run()
    return 0
