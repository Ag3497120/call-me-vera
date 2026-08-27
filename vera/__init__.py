"""call-me-vera — shared, append-only project memory for AI coding agents.

Say "Vera" and it remembers: Claude, a local model, or any other
MCP-compatible agent can record what it did — and read what a different
agent did before it — through one shared, author-tagged, append-only
event log. Not a chat-history store: a continuity layer between agents
and sessions.

    from vera import VeraStore, init_store

    store = init_store(".vera_store.db")
    store.record_turn(
        author="claude",
        request="add OAuth support",
        change="added src/auth/oauth.py",
        result="OAuth flow working",
        interpretation="auth/ now owns all authentication",
    )
    print(store.get_project_state())
"""
from __future__ import annotations

from .store import (
    ContradictionRecord,
    ConstraintRecord,
    FactRecord,
    SessionEvent,
    SessionSummary,
    VeraStore,
    check_consistency,
    extract_summary,
    init_store,
)

__version__ = "0.1.0"

__all__ = [
    "VeraStore",
    "SessionEvent",
    "SessionSummary",
    "FactRecord",
    "ConstraintRecord",
    "ContradictionRecord",
    "init_store",
    "extract_summary",
    "check_consistency",
    "__version__",
]
