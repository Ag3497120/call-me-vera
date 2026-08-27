"""call-me-vera — shared, append-only, citable memory for AI coding agents.

Say "Vera" and it remembers: Claude, a local model, or any other
MCP-compatible agent can record what it did — and read what a different
agent did before it — through one shared, author-tagged, append-only,
numbered memory log. Vera does not interpret what it stores; every entry
gets a stable citation number, and it's up to whichever agent reads the
log to make sense of it.

    from vera import VeraStore, init_store

    store = init_store(".vera_store.db")
    r = store.record_turn(
        author="claude",
        request="add OAuth support",
        change="added src/auth/oauth.py",
        result="OAuth flow working",
        interpretation="auth/ now owns all authentication",
    )
    print(store.get_project_state())      # what a new session reads first
    print(store.lookup(1))                # fetch entry #1 by its citation number
"""
from __future__ import annotations

from .store import VeraStore, init_store

__version__ = "0.2.0"

__all__ = [
    "VeraStore",
    "init_store",
    "__version__",
]
