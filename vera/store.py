"""Vera — shared, append-only, citable memory for AI coding agents.

Vera does not interpret what it stores. There is no fact extraction, no
constraint tracking, no contradiction detection — that was tried and
deliberately removed: deciding what a piece of text "means" is exactly
the kind of judgment an LLM is good at and a fixed set of regex rules is
not. Vera's job is narrower and more reliable: record what happened,
in order, permanently, with a stable number on every entry so it can be
cited ("per #12, ..."), and hand that back to whichever agent asks next.
An agent is free to "cook" that raw material however it wants — compare
it against what it's about to do, summarize it, ignore parts of it — the
same way a person free-reads a log rather than being handed conclusions.

The one piece of judgment Vera does perform is deterministic and
structural, not semantic: estimating whether the *uncompressed* memory
tail has grown large enough that handing it to a fresh agent risks
overflowing its context window. That's a character count against a
threshold, not an opinion about content.

Author is always "claude", "local", or "vera". Sync between stores
merges by author, id-keyed, append-only on both sides.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
-- The one content table. Every "Vera turn" — triggered by the user
-- saying "Vera" — is distilled by the agent into REQUEST/CHANGE/REASON/
-- RESULT/STATE and recorded as separate rows sharing a turn_id, never
-- edited afterward (enforced by the triggers below). SQLite's own rowid
-- (implicit, since `id` is a TEXT primary key, not INTEGER) is the
-- stable per-store citation number every entry gets for free — "per #12"
-- refers to this table's rowid.
CREATE TABLE IF NOT EXISTS event_log (
    id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    author TEXT NOT NULL CHECK(author IN ('claude', 'local', 'vera')),
    type TEXT NOT NULL CHECK(type IN (
        'request', 'change', 'decision', 'result',
        'observation', 'assumption', 'unresolved', 'interpretation'
    )),
    content TEXT NOT NULL,
    files TEXT,             -- JSON array of file paths touched
    lang TEXT NOT NULL DEFAULT 'en',
    session_id TEXT,
    model_timestamp TEXT,
    received_at TEXT,
    committed_at TEXT,
    fingerprint TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS event_log_append_only_update
BEFORE UPDATE ON event_log
BEGIN
    SELECT RAISE(ABORT, 'event_log is append-only: UPDATE is not permitted');
END;

CREATE TRIGGER IF NOT EXISTS event_log_append_only_delete
BEFORE DELETE ON event_log
BEGIN
    SELECT RAISE(ABORT, 'event_log is append-only: DELETE is not permitted');
END;

-- What Vera decided NOT to save, and why (a duplicate, a skip while
-- paused, a pause/resume) — kept separate from event_log's content
-- stream so a gap is traceable without touching event_log's own
-- append-only guarantee or CHECK constraint.
CREATE TABLE IF NOT EXISTS control_log (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('duplicate_suppressed', 'paused_skip', 'pause', 'resume')),
    fingerprint TEXT,
    original_turn_id TEXT,
    session_id TEXT,
    author TEXT,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS control_log_append_only_update
BEFORE UPDATE ON control_log
BEGIN
    SELECT RAISE(ABORT, 'control_log is append-only: UPDATE is not permitted');
END;

CREATE TRIGGER IF NOT EXISTS control_log_append_only_delete
BEFORE DELETE ON control_log
BEGIN
    SELECT RAISE(ABORT, 'control_log is append-only: DELETE is not permitted');
END;

-- Single-row pause switch. Persisted (not in-memory): pausing is a
-- deliberate act ("Vera pause" during bulk agent work) that should
-- survive a process restart, not silently reset.
CREATE TABLE IF NOT EXISTS session_control (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    paused INTEGER NOT NULL DEFAULT 0,
    paused_at TEXT,
    paused_by TEXT,
    resumed_at TEXT,
    updated_at TEXT
);

-- AI-authored compressed digests. Vera never writes one of these itself
-- — an agent judges (via stats()'s size estimate) that the uncompressed
-- tail is getting large, writes a digest citing specific entry numbers
-- ("per #3, #7, #15: ..."), and Vera just stores it. get_project_state()
-- prefers the latest digest plus only what's been recorded since, so a
-- new session's starting context stays small — the full raw history
-- underneath is never deleted, and any cited number is still fetchable
-- via lookup().
CREATE TABLE IF NOT EXISTS digests (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    author TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'en',
    through_n INTEGER NOT NULL,
    text TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS digests_append_only_update
BEFORE UPDATE ON digests
BEGIN
    SELECT RAISE(ABORT, 'digests is append-only: UPDATE is not permitted');
END;

CREATE TRIGGER IF NOT EXISTS digests_append_only_delete
BEFORE DELETE ON digests
BEGIN
    SELECT RAISE(ABORT, 'digests is append-only: DELETE is not permitted');
END;

-- One row: this store's name, if it has been given one (see claim_name()
-- / vera_claim_name). A named store lives at a fixed, predictable path
-- (see resolve_named_path()) so any session/app — regardless of which
-- MCP registration or --store path it started with — can reconnect to
-- the exact same memory by passing the same name, instead of needing to
-- know a filesystem path.
CREATE TABLE IF NOT EXISTS store_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT,
    named_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_event_log_turn ON event_log(turn_id);
CREATE INDEX IF NOT EXISTS idx_event_log_type ON event_log(type);
CREATE INDEX IF NOT EXISTS idx_event_log_created ON event_log(created_at);
CREATE INDEX IF NOT EXISTS idx_event_log_content ON event_log(content);
CREATE INDEX IF NOT EXISTS idx_control_log_kind ON control_log(kind);
CREATE INDEX IF NOT EXISTS idx_digests_through ON digests(through_n);
"""

# Columns added to event_log after its original release, for stores that
# already exist on disk — CREATE TABLE IF NOT EXISTS only guards table
# creation, not columns on a table that's already there. Each is a plain
# nullable TEXT column, which SQLite's ALTER TABLE ADD COLUMN supports
# without a table rebuild.
_EVENT_LOG_MIGRATIONS = [
    ("session_id", "TEXT"),
    ("model_timestamp", "TEXT"),
    ("received_at", "TEXT"),
    ("committed_at", "TEXT"),
    ("fingerprint", "TEXT"),
]

DEFAULT_TOKEN_THRESHOLD = 50_000  # conservative "getting risky for a fresh context" mark
_CHARS_PER_TOKEN_ESTIMATE = 4     # rough, model-agnostic heuristic — not exact for any tokenizer

# Central location for NAMED stores — the actual mechanism behind
# "resume this memory from a different session/app": a name always
# resolves to the same fixed path here, regardless of which MCP
# registration or --store path any given connection started with. A
# store reached this way (not via an explicit --store path) is how two
# otherwise-unrelated registrations (say, Claude Desktop's default store
# and a project-scoped one) end up sharing one memory on purpose.
_NAMED_STORE_DIR = Path.home() / ".vera" / "stores"
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def sanitize_name(name: str) -> Optional[str]:
    """Validate a store name — filesystem-safe, short, no path traversal.
    Returns the (trimmed) name if valid, None if not."""
    name = (name or "").strip()
    if not name or not _NAME_RE.match(name):
        return None
    return name


def resolve_named_path(name: str) -> Path:
    """The fixed path a given name always resolves to."""
    _NAMED_STORE_DIR.mkdir(parents=True, exist_ok=True)
    return _NAMED_STORE_DIR / f"{name}.db"


def list_named_stores() -> List[str]:
    """Every name currently claimed, for a clear 'that name is taken'
    message and for discovery."""
    if not _NAMED_STORE_DIR.exists():
        return []
    return sorted(p.stem for p in _NAMED_STORE_DIR.glob("*.db"))


def claim_name(current: "VeraStore", name: str) -> Dict[str, Any]:
    """Give the CURRENT store a name so any other session/app can resume
    it later via that name alone (resolve_named_path()), instead of
    needing to know a filesystem path.

    If the name is already claimed by a *different* store, this refuses
    rather than silently merging into a stranger's memory — the exact
    "this name can't be used" case. Re-claiming the same name for the
    store that already owns it is a no-op success (idempotent). If the
    name is free, a fresh named store is created at its fixed path and
    everything from `current` is copied into it (via the existing,
    append-only-safe sync() merge) — current's own content is untouched,
    it simply also now lives at the named location."""
    clean = sanitize_name(name)
    if clean is None:
        return {"error": f"invalid name {name!r} — use 1-64 letters/digits/-/_, starting with a letter or digit"}

    target_path = resolve_named_path(clean)
    current_path = current.db_path.resolve()

    if target_path.resolve() == current_path:
        # Already living at its own named path (e.g. re-claiming the name
        # this exact store already has).
        current.set_name(clean)
        return {"name": clean, "path": str(target_path), "already_named": True}

    if target_path.exists():
        target = VeraStore(target_path)
        try:
            # Re-claiming a name `current` already pushed content into
            # before (e.g. to sync newer entries up to the shared copy)
            # must succeed, not read as a stranger's collision — checked
            # by whether ANY of current's own event ids are already
            # present in target, which only happens after a prior
            # successful claim_name/sync of this exact store. An empty,
            # never-claimed `current` has no ids to overlap, so it can
            # never slip through this check by accident.
            current_ids = [row[0] for row in current._conn.execute("SELECT id FROM event_log")]
            already_merged = False
            if current_ids:
                placeholders = ",".join("?" * len(current_ids))
                overlap = target._conn.execute(
                    f"SELECT COUNT(*) FROM event_log WHERE id IN ({placeholders})",
                    current_ids,
                ).fetchone()[0]
                already_merged = overlap > 0

            if not already_merged:
                return {
                    "error": f"the name {clean!r} is already in use by a different memory store",
                    "hint": f'to resume that one instead, call vera_session_start(name="{clean}")',
                }
            target.sync(current_path)
            target.set_name(clean)
        finally:
            target.close()
        return {"name": clean, "path": str(target_path), "already_named": True}

    target = init_store(target_path)
    try:
        target.sync(current_path)
        target.set_name(clean)
    finally:
        target.close()
    return {"name": clean, "path": str(target_path), "already_named": False}


def _time_bucket(iso_ts: str, seconds: int = 5) -> str:
    """Round an ISO timestamp down to a coarse window. Used as the time
    component of a dedup fingerprint when the caller doesn't supply its
    own model_timestamp: an agent that immediately re-sends an identical
    save (the actual failure mode this guards against) will land in the
    same bucket even though the wall-clock second differs slightly; two
    turns with identical text minutes apart will not."""
    epoch = datetime.fromisoformat(iso_ts).timestamp()
    return str(int(epoch // seconds) * seconds)


def _turn_fingerprint(author: str, session_id: str, time_key: str, request: str, result: str) -> str:
    """SHA256 over (author, session, time bucket/model-declared time,
    request, result) — deliberately request+result only, not every field,
    matching the property that actually indicates 'the same save happened
    twice': same ask, same outcome, same author, same session, close in
    time. change/reason/interpretation can legitimately vary in wording
    between an agent's retries without changing whether it's a duplicate."""
    raw = f"{author}|{session_id}|{time_key}|{request}|{result}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _locked(fn):
    """Serialize every public VeraStore method through self._lock.

    check_same_thread=False on the connection (see __init__) only turns
    off Python's OWN same-thread guard — it does not make sqlite3.Connection
    safe for genuinely concurrent use from multiple threads. An MCP server
    can dispatch two tool calls to different worker threads without one
    finishing first (a client that pipelines requests, or a model that
    issues parallel tool calls in one turn), and two threads calling
    .execute() on the same Connection at once corrupts it outright
    (sqlite3.InterfaceError: "bad parameter or other API misuse") rather
    than just racing logically. A single re-entrant lock — cheap for a
    tool used at conversational request rates, not a high-throughput
    database — makes every public method atomic with respect to every
    other one; RLock lets a locked method (e.g. record_turn) call another
    locked method on the same thread without deadlock."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    return wrapper


class VeraStore:
    """SQLite-backed, append-only, citable memory store."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        # Guards every public method (see _locked above) — set before
        # anything else touches the connection, including the migration
        # a few lines down.
        self._lock = threading.RLock()
        # check_same_thread=False: an MCP server dispatches each sync tool
        # call through anyio.to_thread.run_sync, which may pick a different
        # worker thread per call (mcp SDK v2's executor does; v1's didn't
        # always) — sqlite3's default same-thread check would then reject
        # the second call outright. The @_locked serialization above is
        # what actually makes concurrent use safe; this flag only lifts
        # Python's same-thread guard so different threads may take turns.
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._migrate_event_log_columns()
        self._conn.execute(
            "INSERT OR IGNORE INTO session_control (id, paused, updated_at) VALUES (1, 0, ?)",
            (datetime.now(timezone.utc).isoformat(),),
        )
        self._conn.execute("INSERT OR IGNORE INTO store_meta (id, name) VALUES (1, NULL)")
        self._conn.commit()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

        # This VeraStore instance's own "session" — one run of an MCP
        # server process, or one CLI invocation. Deduplication is scoped
        # to it deliberately: the failure mode this guards against is an
        # agent re-sending the same save within one live connection, not
        # two genuinely different sessions producing similar-looking text.
        #
        # Practical consequence: `vera record` run twice from a terminal
        # (two separate processes, two separate session_ids) will NOT
        # dedup against each other, even seconds apart — only repeat calls
        # within one running MCP server connection do. That's intentional:
        # the reported problem is an agent's tool-call retry inside one
        # live session, and a human/script re-running the CLI on purpose
        # shouldn't have a legitimate second run silently swallowed.
        self.session_id = str(uuid.uuid4())

    def _migrate_event_log_columns(self) -> None:
        # Not fully race-proof against a second PROCESS migrating the same
        # pre-existing store at (as near as makes no difference) the same
        # instant — self._lock only serializes threads within this one
        # process, and PRAGMA table_info() plus each ALTER aren't wrapped
        # in one atomic transaction. If another process's ALTER commits
        # between our read and ours, SQLite raises "duplicate column
        # name:" for the column that's now already there — caught and
        # treated as success (the outcome we wanted happened, just via a
        # different process) rather than crashing __init__; any other
        # OperationalError still propagates.
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(event_log)")}
        for name, coltype in _EVENT_LOG_MIGRATIONS:
            if name in existing:
                continue
            try:
                self._conn.execute(f"ALTER TABLE event_log ADD COLUMN {name} {coltype}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc):
                    raise
        self._conn.commit()

    # -- writing -------------------------------------------------------------

    def _append_event_log(
        self, turn_id: str, author: str, type_: str, content: str,
        files: List[str] | None = None, lang: str = "en",
        model_timestamp: str = "", received_at: str = "",
        committed_at: str = "", fingerprint: str = "",
    ) -> str:
        eid = str(uuid.uuid4())
        now = received_at or datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO event_log (id, turn_id, ts, author, type, content, files, lang,"
            " created_at, session_id, model_timestamp, received_at, committed_at, fingerprint)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, turn_id, now, author, type_, content,
             json.dumps(files or [], ensure_ascii=False), lang, now,
             self.session_id, model_timestamp, received_at, committed_at, fingerprint),
        )
        return eid

    def _log_control(
        self, kind: str, fingerprint: str = "", original_turn_id: str = "",
        author: str = "", note: str = "",
    ) -> str:
        cid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO control_log (id, ts, kind, fingerprint, original_turn_id,"
            " session_id, author, note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, now, kind, fingerprint, original_turn_id, self.session_id, author, note, now),
        )
        self._conn.commit()
        return cid

    @_locked
    def get_name(self) -> str:
        """This store's name, if it has one — see claim_name(). Empty
        string if unnamed."""
        row = self._conn.execute("SELECT name FROM store_meta WHERE id=1").fetchone()
        return (row[0] or "") if row else ""

    @_locked
    def set_name(self, name: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE store_meta SET name=?, named_at=? WHERE id=1", (name, now)
        )
        self._conn.commit()

    @_locked
    def is_paused(self) -> bool:
        row = self._conn.execute("SELECT paused FROM session_control WHERE id=1").fetchone()
        return bool(row and row[0])

    @_locked
    def pause(self, by: str = "local") -> Dict[str, Any]:
        """Stop record_turn() from saving content until resume() — the
        "Vera pause" / "before bulk agent work" case. Skipped attempts are
        still logged (control_log), so a gap is always traceable."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE session_control SET paused=1, paused_at=?, paused_by=?, updated_at=? WHERE id=1",
            (now, by, now),
        )
        self._conn.commit()
        self._log_control("pause", author=by)
        return {"paused": True, "paused_at": now, "paused_by": by}

    @_locked
    def resume(self, by: str = "local") -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE session_control SET paused=0, resumed_at=?, updated_at=? WHERE id=1",
            (now, now),
        )
        self._conn.commit()
        self._log_control("resume", author=by)
        return {"paused": False, "resumed_at": now}

    @_locked
    def record_turn(
        self,
        author: str,
        request: str,
        change: str = "",
        reason: str = "",
        files: List[str] | None = None,
        result: str = "",
        interpretation: str = "",
        unresolved: str = "",
        lang: str = "en",
        model_timestamp: str = "",
    ) -> Dict[str, Any]:
        """Append one structured 'Vera' turn. Returns {"turn_id", "event_ids"}
        normally; {"paused": True, "skipped": True} if recording is
        currently paused; {"duplicate_suppressed": True, "turn_id": <original>}
        if this exact (author, session, time-window, request, result) was
        already recorded — the original is left untouched, and this
        decision is itself logged to control_log, not silently dropped.

        REQUEST/CHANGE/REASON/RESULT/STATE(interpretation)/unresolved each
        become their own immutable, numbered event_log row under one
        turn_id — the request is always recorded even if every other field
        is empty. Vera does not interpret any of this; it's stored exactly
        as given, for whichever agent reads it next to make sense of."""
        if self.is_paused():
            self._log_control("paused_skip", author=author, note=request[:200])
            return {"paused": True, "skipped": True}

        received_at = datetime.now(timezone.utc).isoformat()
        time_key = model_timestamp or _time_bucket(received_at)
        fingerprint = _turn_fingerprint(author, self.session_id, time_key, request, result)

        existing = self._conn.execute(
            "SELECT turn_id FROM event_log WHERE fingerprint=? LIMIT 1", (fingerprint,)
        ).fetchone()
        if existing:
            self._log_control(
                "duplicate_suppressed", fingerprint=fingerprint,
                original_turn_id=existing[0], author=author,
            )
            return {"turn_id": existing[0], "event_ids": [], "duplicate_suppressed": True}

        turn_id = str(uuid.uuid4())
        # committed_at is set *before* the inserts below, not patched in
        # afterward — event_log's append-only triggers reject UPDATE
        # outright (on purpose), so there's no "insert, then stamp the
        # actual commit time" pass available. This is the timestamp taken
        # immediately before the one atomic commit() that persists every
        # row in this turn together, which is what "committed" means here
        # in practice for a synchronous, single-writer store.
        committed_at = datetime.now(timezone.utc).isoformat()
        kw = dict(model_timestamp=model_timestamp, received_at=received_at,
                  committed_at=committed_at, fingerprint=fingerprint)
        event_ids = [self._append_event_log(turn_id, author, "request", request, lang=lang, **kw)]
        if change:
            event_ids.append(self._append_event_log(turn_id, author, "change", change, files=files, lang=lang, **kw))
        if reason:
            event_ids.append(self._append_event_log(turn_id, author, "decision", reason, lang=lang, **kw))
        if result:
            event_ids.append(self._append_event_log(turn_id, author, "result", result, lang=lang, **kw))
        if interpretation:
            event_ids.append(self._append_event_log(turn_id, author, "interpretation", interpretation, lang=lang, **kw))
        if unresolved:
            event_ids.append(self._append_event_log(turn_id, author, "unresolved", unresolved, lang=lang, **kw))
        self._conn.commit()
        return {"turn_id": turn_id, "event_ids": event_ids}

    # -- reading ---------------------------------------------------------------

    @_locked
    def lookup(self, n: int) -> Optional[Dict[str, Any]]:
        """Fetch one entry by its citation number (rowid) — what a digest's
        "per #12" or a search hit's "n" refers to."""
        row = self._conn.execute(
            "SELECT rowid, turn_id, ts, author, type, content, files, lang"
            " FROM event_log WHERE rowid=?", (n,)
        ).fetchone()
        if not row:
            return None
        return {
            "n": row[0], "turn_id": row[1], "ts": row[2], "author": row[3],
            "type": row[4], "content": row[5],
            "files": json.loads(row[6]) if row[6] else [], "lang": row[7],
        }

    @_locked
    def search(self, query: str, k: int = 10) -> List[Dict[str, Any]]:
        """Text search over raw entries and any compression digests, newest
        first. Every hit carries its citation number (n)."""
        q = f"%{query}%"
        results: List[Dict[str, Any]] = []
        for row in self._conn.execute(
            "SELECT rowid, turn_id, ts, author, type, content"
            " FROM event_log WHERE content LIKE ? ORDER BY rowid DESC LIMIT ?", (q, k)
        ):
            results.append({
                "n": row[0], "turn_id": row[1], "ts": row[2], "author": row[3],
                "type": row[4], "text": row[5][:400],
            })
        for row in self._conn.execute(
            "SELECT id, created_at, author, through_n, text FROM digests"
            " WHERE text LIKE ? ORDER BY created_at DESC LIMIT ?", (q, k)
        ):
            results.append({
                "digest_id": row[0], "ts": row[1], "author": row[2],
                "through_n": row[3], "text": row[4][:400],
            })
        return results[:k]

    @_locked
    def get_project_state(self, recent_n: int = 20) -> Dict[str, Any]:
        """Everything a new session needs before starting work. If a
        compression digest exists, this is the digest plus only what's
        been recorded since it (bounded, small) — not the full raw
        history, which stays on disk and reachable via lookup()/search()
        but isn't pushed into every new session's starting context.
        Without a digest yet, it's simply the most recent entries."""
        digest_row = self._conn.execute(
            "SELECT id, created_at, author, lang, through_n, text FROM digests"
            " ORDER BY through_n DESC LIMIT 1"
        ).fetchone()
        since_n = digest_row[4] if digest_row else 0
        recent = self._conn.execute(
            "SELECT rowid, turn_id, ts, author, type, content, files"
            " FROM event_log WHERE rowid > ? ORDER BY rowid ASC LIMIT ?",
            (since_n, recent_n),
        ).fetchall()
        return {
            "name": self.get_name(),
            "digest": (
                {"id": digest_row[0], "ts": digest_row[1], "author": digest_row[2],
                 "lang": digest_row[3], "through_n": digest_row[4], "text": digest_row[5]}
                if digest_row else None
            ),
            "recent_entries": [
                {"n": r[0], "turn_id": r[1], "ts": r[2], "author": r[3], "type": r[4],
                 "content": r[5], "files": json.loads(r[6]) if r[6] else []}
                for r in recent
            ],
            "recording_paused": self.is_paused(),
            "size": self._size_estimate(),
        }

    def _size_estimate(self, threshold_tokens: int = DEFAULT_TOKEN_THRESHOLD) -> Dict[str, Any]:
        """How much *uncompressed* content a new session would have to
        load — the actual question for "would this overflow another
        agent's context." Only counts what's after the latest digest (or
        everything, if there's no digest yet). A character count against
        a threshold, not an opinion about what the content means."""
        since_n = self._conn.execute(
            "SELECT COALESCE(MAX(through_n), 0) FROM digests"
        ).fetchone()[0]
        n_entries, total_chars = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(content)), 0) FROM event_log WHERE rowid > ?",
            (since_n,),
        ).fetchone()
        est_tokens = total_chars // _CHARS_PER_TOKEN_ESTIMATE
        return {
            "uncompressed_entries": n_entries,
            "uncompressed_chars": total_chars,
            "estimated_tokens": est_tokens,
            "threshold_tokens": threshold_tokens,
            "over_threshold": est_tokens > threshold_tokens,
            "since_n": since_n,
        }

    # -- compression -------------------------------------------------------

    @_locked
    def add_digest(self, text: str, through_n: int = 0, author: str = "claude", lang: str = "en") -> Dict[str, Any]:
        """Store an AI-authored compressed digest of everything up to and
        including entry #through_n (0 or omitted = everything recorded so
        far). Vera does not write this itself — the agent judged (usually
        via stats()'s size estimate) that the uncompressed tail was
        getting large, read the raw entries, and wrote a digest that cites
        specific numbers ("per #3, #7: ..."). Nothing gets deleted; the
        raw entries stay reachable via lookup(). Future get_project_state()
        calls show this digest plus only what's been recorded since,
        instead of the full history."""
        if through_n <= 0:
            through_n = self._conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM event_log").fetchone()[0]
        did = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO digests (id, created_at, author, lang, through_n, text) VALUES (?,?,?,?,?,?)",
            (did, now, author, lang, through_n, text),
        )
        self._conn.commit()
        return {"digest_id": did, "through_n": through_n}

    # -- status --------------------------------------------------------------

    @_locked
    def stats(self) -> Dict[str, Any]:
        """Everything about the store's current state in one call: entry/
        author counts, the size estimate (and whether it's over the
        compression threshold), pause state, the last entry actually
        recorded, and the last control decision (duplicate suppressed /
        paused skip / pause / resume) — the "what's actually going on"
        view."""
        n_entries = self._conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0]
        authors = dict(self._conn.execute(
            "SELECT author, COUNT(*) FROM event_log GROUP BY author"
        ).fetchall())
        n_digests = self._conn.execute("SELECT COUNT(*) FROM digests").fetchone()[0]
        last_event = self._conn.execute(
            "SELECT rowid, turn_id, ts, author, type FROM event_log ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        last_control = self._conn.execute(
            "SELECT kind, ts, original_turn_id FROM control_log ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        n_suppressed = self._conn.execute(
            "SELECT COUNT(*) FROM control_log WHERE kind='duplicate_suppressed'"
        ).fetchone()[0]
        n_paused_skips = self._conn.execute(
            "SELECT COUNT(*) FROM control_log WHERE kind='paused_skip'"
        ).fetchone()[0]
        n_events_this_session = self._conn.execute(
            "SELECT COUNT(*) FROM event_log WHERE session_id=?", (self.session_id,)
        ).fetchone()[0]
        return {
            "session_id": self.session_id,
            "name": self.get_name(),
            "state": "PAUSED" if self.is_paused() else "READY",
            "entries": n_entries,
            "authors": authors,
            "digests": n_digests,
            "size": self._size_estimate(),
            "last_event": (
                {"n": last_event[0], "turn_id": last_event[1], "ts": last_event[2],
                 "author": last_event[3], "type": last_event[4]}
                if last_event else None
            ),
            "last_control": (
                {"kind": last_control[0], "ts": last_control[1], "original_turn_id": last_control[2]}
                if last_control else None
            ),
            "events_this_session": n_events_this_session,
            "duplicates_suppressed_total": n_suppressed,
            "paused_skips_total": n_paused_skips,
        }

    # -- sync ----------------------------------------------------------------

    @_locked
    def sync(self, other_path: str | Path) -> Dict[str, Any]:
        """Merge another VeraStore into this one — event_log, control_log,
        and digests, all id-keyed and append-only on both sides, for the
        case where two stores never shared a filesystem (a different
        machine) and need to reconcile after the fact. session_control
        (the pause switch) deliberately does not sync — pausing is a
        local, per-store decision."""
        other = VeraStore(other_path)
        merged: Dict[str, int] = {"inserted": 0, "conflicts": 0, "updated": 0}

        _EVENT_LOG_COLS = (
            "id, turn_id, ts, author, type, content, files, lang, created_at, "
            "session_id, model_timestamp, received_at, committed_at, fingerprint"
        )
        for row in other._conn.execute(f"SELECT {_EVENT_LOG_COLS} FROM event_log ORDER BY rowid").fetchall():
            eid = row[0]
            exists = self._conn.execute("SELECT COUNT(*) FROM event_log WHERE id=?", (eid,)).fetchone()[0]
            if exists:
                merged["conflicts"] += 1
                continue
            placeholders = ",".join("?" * len(row))
            self._conn.execute(
                f"INSERT OR IGNORE INTO event_log ({_EVENT_LOG_COLS}) VALUES ({placeholders})", row
            )
            merged["inserted"] += 1

        for row in other._conn.execute(
            "SELECT id, ts, kind, fingerprint, original_turn_id, session_id, author, note, created_at"
            " FROM control_log"
        ).fetchall():
            exists = self._conn.execute("SELECT COUNT(*) FROM control_log WHERE id=?", (row[0],)).fetchone()[0]
            if not exists:
                self._conn.execute(
                    "INSERT OR IGNORE INTO control_log"
                    " (id, ts, kind, fingerprint, original_turn_id, session_id, author, note, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)", row
                )
                merged["updated"] += 1

        for row in other._conn.execute(
            "SELECT id, created_at, author, lang, through_n, text FROM digests"
        ).fetchall():
            exists = self._conn.execute("SELECT COUNT(*) FROM digests WHERE id=?", (row[0],)).fetchone()[0]
            if not exists:
                self._conn.execute(
                    "INSERT OR IGNORE INTO digests (id, created_at, author, lang, through_n, text)"
                    " VALUES (?,?,?,?,?,?)", row
                )
                merged["updated"] += 1

        other.close()
        self._conn.commit()
        return merged

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "VeraStore":
        return self

    def __exit__(self, *args) -> None:
        self.close()


def init_store(path: str | Path) -> VeraStore:
    """Create or open a Vera store."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return VeraStore(p)
