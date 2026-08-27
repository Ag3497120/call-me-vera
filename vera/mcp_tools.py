"""Vera MCP tools — session capture & persistent memory for AI coding agents.

Exposes Vera as MCP tools so Claude Code (or any agent) can record sessions,
search history, check consistency against constraints, and sync stores.

Usage from Claude: call `vera_save_session` / `vera_summarize` / etc.
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
    def vera_save_session(
        user_prompt: str,
        tool_calls: str = "[]",
        tool_results: str = "[]",
        git_diff: str = "",
        actions: str = "[]",
        observations: str = "[]",
        author: str = "claude",
        working_directory: str = "",
    ) -> str:
        """Capture a session event. Records the user prompt, tool calls,
        results, git diff, actions taken, and observations made — all
        tagged with an author (\"claude\" or \"local\"). A summary with
        extracted facts/decisions/constraints is auto-generated."""
        try:
            tc = json.loads(tool_calls) if tool_calls else []
            tr = json.loads(tool_results) if tool_results else []
            ac = json.loads(actions) if actions else []
            ob = json.loads(observations) if observations else []
        except (json.JSONDecodeError, TypeError) as exc:
            return json.dumps({"error": f"invalid JSON: {exc}"})

        sid = store.save_session(
            author=author,
            user_prompt=user_prompt,
            tool_calls=tc,
            tool_results=tr,
            git_diff=git_diff,
            actions=ac,
            observations=ob,
            working_directory=working_directory or "",
        )
        return json.dumps({"session_id": sid, "saved": True}, ensure_ascii=False)

    @mcp.tool()
    def vera_summarize(session_id: str) -> str:
        """Generate a summary for a session: facts, decisions, constraints,
        todos, unresolved items. Returns JSON."""
        s = store.summarize(session_id)
        if not s:
            return json.dumps({"error": "session not found"})
        return json.dumps({
            "session_id": s.session_id,
            "facts": s.facts,
            "decisions": s.decisions,
            "constraints": s.constraints,
            "todos": s.todos,
            "unresolved": s.unresolved,
        }, ensure_ascii=False)

    @mcp.tool()
    def vera_search(query: str, k: int = 10) -> str:
        """Search across all Vera records (events, facts, constraints, summaries)."""
        results = store.search(query, k=k)
        return json.dumps(results, ensure_ascii=False)

    @mcp.tool()
    def vera_check_consistency(
        current_action: str,
        current_proposal: str = "",
    ) -> str:
        """Check active constraints against the current action/proposal.
        Returns status (\"OK\" or \"CONTRADICTION\") with details."""
        return json.dumps(store.check_consistency(current_action, current_proposal), ensure_ascii=False)

    @mcp.tool()
    def vera_list_facts(category: str = "") -> str:
        """List all stored facts. Optionally filter by category."""
        return json.dumps(store.list_facts(category=category), ensure_ascii=False)

    @mcp.tool()
    def vera_add_constraint(text: str) -> str:
        """Add a project constraint to Vera's memory."""
        cid = store.add_constraint(text)
        return json.dumps({"constraint_id": cid, "text": text}, ensure_ascii=False)

    @mcp.tool()
    def vera_get_constraints() -> str:
        """List all active constraints."""
        return json.dumps(store.get_constraints(), ensure_ascii=False)

    @mcp.tool()
    def vera_list_contradictions(resolved_only: bool = False) -> str:
        """List contradictions between actions and constraints."""
        return json.dumps(store.list_contradictions(resolved_only=resolved_only), ensure_ascii=False)

    @mcp.tool()
    def vera_get_session(session_id: str) -> str:
        """Get a single session event with full details."""
        ev = store.get_session(session_id)
        if not ev:
            return json.dumps({"error": "session not found"})
        return json.dumps(ev, ensure_ascii=False, indent=2)

    @mcp.tool()
    def vera_sync(local_path: str, remote_path: str) -> str:
        """Merge two Vera stores. local_path is this store; remote_path is the other."""
        merged = store.sync(remote_path)
        return json.dumps({"synced": True, "merged": merged}, ensure_ascii=False)

    @mcp.tool()
    def vera_stats() -> str:
        """Vera store statistics (events, facts, constraints, contradictions)."""
        return json.dumps(store.report(), ensure_ascii=False)

    @mcp.tool()
    def vera_guide(lang: str = "en") -> str:
        """Full onboarding explanation of Vera and how an agent should
        behave in this session: what Vera is, how to call vera_session_start
        and vera_record, the agent behavior protocol, and available
        commands — in the requested language (code or name, e.g. "de",
        "German", "Deutsch", or a phrase like "ドイツ語"; unrecognized falls
        back to English). Call this once to learn how to use Vera; call
        vera_session_start at the beginning of every session instead — it's
        shorter and carries this project's actual current state."""
        return render_guide(lang)

    @mcp.tool()
    def vera_session_start(lang: str = "en") -> str:
        """Call this BEFORE doing any work in a new session. Returns the
        project's current state — latest codebase interpretation, active
        constraints, open contradictions, recent decisions/changes/
        unresolved items/results — plus the agent behavior protocol, in the
        requested language. This is the hand-off point between agents/
        sessions: read it instead of asking the user to re-explain the
        project."""
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
    ) -> str:
        """Call this when the user says \"Vera\" mid-conversation. Distill
        the turn into REQUEST (what was asked), CHANGE (what you did, and
        `files` as a JSON array of paths touched), REASON (why you
        structured it that way), RESULT (what happened), interpretation
        (your current understanding of the codebase — also say this part
        out loud to the user in your reply), and unresolved (anything left
        open). Every non-empty field becomes its own permanent, append-only
        record — Vera never overwrites a past event."""
        try:
            files_list = json.loads(files) if files else []
        except (json.JSONDecodeError, TypeError) as exc:
            return json.dumps({"error": f"invalid JSON for files: {exc}"})
        result_dict = store.record_turn(
            author=author, request=request, change=change, reason=reason,
            files=files_list, result=result, interpretation=interpretation,
            unresolved=unresolved, lang=resolve_lang(lang),
        )
        return json.dumps(result_dict, ensure_ascii=False)

    @mcp.tool()
    def vera_add_interpretation(text: str, author: str = "vera", lang: str = "en") -> str:
        """Record a standalone snapshot of how the codebase is currently
        understood, independent of any specific turn — comparable later via
        vera_get_interpretation() to see how understanding has shifted."""
        eid = store.add_interpretation(text, author=author, lang=resolve_lang(lang))
        return json.dumps({"event_id": eid}, ensure_ascii=False)

    @mcp.tool()
    def vera_get_interpretation(n: int = 2) -> str:
        """Most recent codebase-interpretation snapshots, newest first —
        compare index 0 (current) against index 1 (previous) to see how the
        understanding of the codebase has changed."""
        return json.dumps(store.get_latest_interpretation(n=n), ensure_ascii=False)

    @mcp.tool()
    def vera_get_event_log(turn_id: str = "", type: str = "", k: int = 50) -> str:
        """Raw append-only event_log rows, optionally filtered by turn_id
        or type (request|change|decision|result|observation|assumption|
        unresolved|interpretation), newest first."""
        return json.dumps(store.get_event_log(turn_id=turn_id, type_=type, k=k), ensure_ascii=False)

    mcp.run()
    return 0
