"""Vera — external memory & verification layer for AI coding agents.

Vera captures "externally observable facts" (user prompts, tool calls,
results, git diffs) as persistent session records. It does NOT hack Claude's
internal session files. Instead it offers:

  * raw event store     — deterministic recording
  * fact extraction     — rule-based from actions/observations
  * constraint tracking — constraints extracted or manually added
  * contradiction engine — compare current action vs historical constraints
  * retrieval (search)  — across all recorded layers

Author is always "claude" or "local". Sync between stores merges by author.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SessionEvent:
    session_id: str
    timestamp: str
    author: str  # "claude" | "local"
    user_prompt: str
    tool_calls: List[str] = field(default_factory=list)
    tool_results: List[str] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    observations: List[str] = field(default_factory=list)
    git_diff: str = ""
    working_directory: str = ""


@dataclass
class SessionSummary:
    session_id: str
    facts: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    todos: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)


@dataclass
class FactRecord:
    id: str
    text: str
    source_session: str
    certainty: str  # "high" | "medium" | "low"
    category: str = ""
    created_at: str = ""


@dataclass
class ConstraintRecord:
    id: str
    text: str
    source_session: str
    active: bool = True
    created_at: str = ""


@dataclass
class ContradictionRecord:
    id: str
    constraint_text: str
    violating_action: str
    detected_ts: str
    sessions: List[str] = field(default_factory=list)
    resolved: bool = False


# ---------------------------------------------------------------------------
# Deterministic extraction heuristics
# ---------------------------------------------------------------------------

_FACT_PATTERNS = [
    # "X is Y" / "X uses Y" / "X has Y"
    re.compile(r"(?:^|\n)\s*(\w[\w\s\-]+)\s+(?:is|uses|has|relies on|stores|holds|contains)\s+([\w\s\-]+)", re.IGNORECASE),
    # explicit fact markers
    re.compile(r"FACT[:\s]+(.+)", re.IGNORECASE),
    # "X: Y" at start of line in observations
    re.compile(r"(?:^|\n)\s*[-•]\s+(\w[\w\s\-]+):\s+(.+)", re.IGNORECASE),
]

_CONSTRAINT_PATTERNS = [
    re.compile(
        r"(?:no|not any|never|must not|should not|cannot|avoid|exclude|"
        r"stdlib only|no external(?:al)? dependency)"
        r"\b",
        re.IGNORECASE,
    ),
]

_DECISION_PATTERNS = [
    re.compile(
        r"(?:decided|chose|selected|picked|opted for|went with|"
        r"settled on|determined)\s+(?:to\s+)?(.+?)[.]",
        re.IGNORECASE,
    ),
]

_TODO_PATTERNS = [
    re.compile(r"(TODO|FIXME|HACK):(.+?)(?:\n|$)", re.IGNORECASE),
]


def _extract_facts(actions: List[str], observations: List[str]) -> List[str]:
    facts: List[str] = []
    for block in actions + observations:
        # Explicit "FACT: ..." markers first (pattern index 1) — handled here
        # directly so the prefix is stripped; skipped below to avoid a second,
        # differently-formatted copy of the same fact.
        for m in re.finditer(r"FACT[:\s]+(.+)", block, re.IGNORECASE):
            f = m.group(1).strip()
            if f and f not in facts:
                facts.append(f)
        # Remaining heuristic patterns ("X uses/has/is Y", "- label: value")
        for pat in (_FACT_PATTERNS[0], _FACT_PATTERNS[2]):
            for m in pat.finditer(block):
                full = m.group(0).strip()
                if len(full) > 5 and full not in facts:
                    facts.append(full)
    return facts


def _extract_decisions(actions: List[str]) -> List[str]:
    decisions: List[str] = []
    for block in actions:
        for m in _DECISION_PATTERNS[0].finditer(block):
            d = m.group(1).strip()
            if len(d) > 3 and d not in decisions:
                decisions.append(d)
    return decisions


def _extract_constraints(actions: List[str], observations: List[str]) -> List[str]:
    constraints: List[str] = []
    for block in actions + observations:
        # Explicit constraint markers
        for m in re.finditer(r"(?:CONSTRAINT|RULE|POLICY)[:\s]+(.+)", block, re.IGNORECASE):
            c = m.group(1).strip()
            if c and c not in constraints:
                constraints.append(c)
        # Pattern-based (only check heuristics if no explicit rules found yet)
        if not any(re.search(p, block) for p in _CONSTRAINT_PATTERNS):
            continue
        # Extract the relevant sentence around the constraint keyword
        sentences = re.split(r"[.!?]\s+", block)
        for s in sentences:
            if any(re.search(p, s) for p in _CONSTRAINT_PATTERNS):
                s = s.strip()
                if len(s) > 5 and s not in constraints:
                    constraints.append(s)
    return constraints


def _extract_todos(actions: List[str], observations: List[str]) -> List[str]:
    todos: List[str] = []
    for block in actions + observations:
        for m in _TODO_PATTERNS[0].finditer(block):
            t = (m.group(1) + ": " + m.group(2).strip())
            if t not in todos:
                todos.append(t)
    return todos


def _extract_unresolved(actions: List[str], observations: List[str]) -> List[str]:
    unresolved: List[str] = []
    for block in actions + observations:
        # Detect incomplete work patterns
        incomplete_phrases = [
            r"(?:still|yet|pending|remaining)\s+(needs?|requires?|wants?|has)",
            r"(?:problem|issue|bug|wrong|incorrect|broken)[:\s]+(.+)",
            r"(?:TODO|FIXME):\s*(.+)",
        ]
        for pat_str in incomplete_phrases:
            for m in re.finditer(pat_str, block, re.IGNORECASE):
                t = m.group(0).strip() if m.lastindex is None else m.group(m.lastindex).strip()
                if len(t) > 3 and t not in unresolved:
                    unresolved.append(t)
    return unresolved


def _stable_id(kind: str, session_id: str, text: str) -> str:
    """Deterministic short id for a (kind, session, text) triple — same
    inputs always hash to the same id, so re-extracting the same content
    is a no-op against INSERT OR IGNORE instead of an accumulating dup."""
    h = hashlib.sha1(f"{kind}:{session_id}:{text}".encode("utf-8")).hexdigest()
    return h[:12]


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


def extract_summary(event: SessionEvent) -> SessionSummary:
    """Deterministic summarization from raw event data."""
    actions = event.actions or []
    observations = event.observations or []
    tool_calls = event.tool_calls or []
    all_blocks = actions + observations + tool_calls
    return SessionSummary(
        session_id=event.session_id,
        facts=_extract_facts(actions, observations),
        decisions=_extract_decisions(actions),
        constraints=_extract_constraints(actions, observations),
        todos=_extract_todos(all_blocks, all_blocks),
        unresolved=_extract_unresolved(all_blocks, all_blocks),
    )


# ---------------------------------------------------------------------------
# Contradiction engine
# ---------------------------------------------------------------------------

def check_consistency(
    constraints: List[Tuple[str, str, str]],  # (id, text, source_session)
    current_action: str,
    current_proposal: str = "",
) -> Optional[ContradictionRecord]:
    """Check current action/proposal against all active constraints."""
    proposal_text = f"{current_proposal}\n{current_action}" if current_proposal else current_action

    # Constraint → violation keyword mapping
    constraint_rules = {
        "stdlib": [
            (re.compile(r"pip\s+install", re.IGNORECASE), "package installation"),
            (re.compile(r"import\s+\w+(?:\.\w+)*", re.IGNORECASE), "module import"),
            (re.compile(r"from\s+\w+", re.IGNORECASE), "module import"),
            (re.compile(r"requirement|dependency|external.*lib", re.IGNORECASE), "external dependency"),
        ],
        "no.?external": [
            (re.compile(r"pip\s+install", re.IGNORECASE), "package installation"),
            (re.compile(r"add.*(?:package|dependency|module)\s+", re.IGNORECASE), "adding dependency"),
            (re.compile(r"requirement", re.IGNORECASE), "requirement declaration"),
        ],
        "local.?first": [
            (re.compile(r"(?:upload|push|send|sync|fetch|pull|remote)", re.IGNORECASE), "external I/O"),
            (re.compile(r"external\s+(?:api|service|server)", re.IGNORECASE), "external service call"),
        ],
        "deterministic": [
            (re.compile(r"random", re.IGNORECASE), "non-determinism"),
            (re.compile(r"llm|ai.*generation|neural", re.IGNORECASE), "AI generation"),
        ],
    }

    for cid, ctext, _src in constraints:
        if not ctext:
            continue
        ctext_lower = ctext.lower()
        for keyword, patterns in constraint_rules.items():
            if keyword not in ctext_lower:
                continue
            for pat, desc in patterns:
                if pat.search(proposal_text):
                    return ContradictionRecord(
                        id=str(uuid.uuid4())[:8],
                        constraint_text=ctext,
                        violating_action=current_action,
                        detected_ts=datetime.now(timezone.utc).isoformat(),
                        sessions=[],
                        resolved=False,
                    )

    return None


# ---------------------------------------------------------------------------
# VeraStore — SQLite-backed persistent store
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    session_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    author TEXT NOT NULL CHECK(author IN ('claude', 'local')),
    user_prompt TEXT,
    tool_calls TEXT,       -- JSON array of strings
    tool_results TEXT,     -- JSON array of strings
    actions TEXT,          -- JSON array of strings
    observations TEXT,     -- JSON array of strings
    git_diff TEXT,
    working_directory TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS summaries (
    session_id TEXT PRIMARY KEY,
    summary_text TEXT,
    facts TEXT,           -- JSON array
    decisions TEXT,       -- JSON array
    constraints TEXT,     -- JSON array
    todos TEXT,           -- JSON array
    unresolved TEXT,      -- JSON array
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES events(session_id)
);

CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    source_session TEXT,
    certainty TEXT CHECK(certainty IN ('high','medium','low')),
    category TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS constraints (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    source_session TEXT,
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contradictions (
    id TEXT PRIMARY KEY,
    constraint_text TEXT NOT NULL,
    violating_action TEXT NOT NULL,
    detected_ts TEXT NOT NULL,
    sessions TEXT,        -- JSON array of session_ids
    resolved INTEGER DEFAULT 0,
    FOREIGN KEY(id) REFERENCES events(session_id)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    author TEXT NOT NULL,
    session_id TEXT,
    direction TEXT,       -- 'push' | 'pull' | 'merge'
    summary TEXT
);

-- Fine-grained, append-only structured log: one "Vera" turn (a request from
-- the user, distilled and recorded) becomes several rows sharing a turn_id
-- — request / change / decision / result / observation / assumption /
-- unresolved / interpretation. Enforced append-only at the DB level (below)
-- rather than by convention: a past event must never be edited, only
-- superseded by a later one.
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

-- Bookkeeping for the dedup/pause machinery below — a *separate* table
-- from event_log on purpose: it records what Vera *decided not* to save
-- (a duplicate, or a skip while paused) so that's still observable
-- ("why isn't there an event here?") without touching event_log's own
-- append-only content stream or its CHECK constraint (SQLite can't ALTER
-- a CHECK constraint on an existing table, so new content *types* belong
-- in a new table, not a widened constraint on this one).
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

-- Single-row pause switch. Persisted (not in-memory) on purpose: pausing
-- is a deliberate act ("Vera pause" during bulk agent work) that should
-- survive an MCP server/process restart, not silently reset.
CREATE TABLE IF NOT EXISTS session_control (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    paused INTEGER NOT NULL DEFAULT 0,
    paused_at TEXT,
    paused_by TEXT,
    resumed_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_prompt ON events(user_prompt);
CREATE INDEX IF NOT EXISTS idx_events_author ON events(author);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_facts_text ON facts(text);
CREATE INDEX IF NOT EXISTS idx_constraints_active ON constraints(active);
CREATE INDEX IF NOT EXISTS idx_event_log_turn ON event_log(turn_id);
CREATE INDEX IF NOT EXISTS idx_event_log_type ON event_log(type);
CREATE INDEX IF NOT EXISTS idx_event_log_created ON event_log(created_at);
CREATE INDEX IF NOT EXISTS idx_control_log_kind ON control_log(kind);
"""

# Columns added to event_log after its original release. New tables handle
# schema growth via CREATE TABLE IF NOT EXISTS above, but a table that
# already exists on disk (any store created before this version) needs an
# explicit ALTER — "IF NOT EXISTS" only guards table creation, not columns
# on a table that's already there. Each is a plain nullable TEXT column,
# which SQLite's ALTER TABLE ADD COLUMN supports without a table rebuild.
_EVENT_LOG_MIGRATIONS = [
    ("session_id", "TEXT"),
    ("model_timestamp", "TEXT"),
    ("received_at", "TEXT"),
    ("committed_at", "TEXT"),
    ("fingerprint", "TEXT"),
]


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
    locked method (e.g. save_session) on the same thread without deadlock."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    return wrapper


class VeraStore:
    """SQLite-backed persistent session store with extraction + consistency."""

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
        # the second call outright. Calls are still effectively sequential
        # (each is awaited before the next starts), so this doesn't need
        # its own locking on top.
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._migrate_event_log_columns()
        self._conn.execute(
            "INSERT OR IGNORE INTO session_control (id, paused, updated_at) VALUES (1, 0, ?)",
            (datetime.now(timezone.utc).isoformat(),),
        )
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
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(event_log)")}
        for name, coltype in _EVENT_LOG_MIGRATIONS:
            if name not in existing:
                self._conn.execute(f"ALTER TABLE event_log ADD COLUMN {name} {coltype}")
        self._conn.commit()

    # -- public API --------------------------------------------------------

    @_locked
    def add_event(
        self,
        event: SessionEvent,
    ) -> str:
        """Record a raw session event. Returns session_id.

        Events are append-only: a session_id that already exists is a bug
        (Vera memory must never be silently overwritten), not something to
        replace — it raises ValueError instead."""
        ev = asdict(event)
        for k in ("tool_calls", "tool_results", "actions", "observations"):
            if isinstance(ev.get(k), list):
                ev[k] = json.dumps(ev[k], ensure_ascii=False) or ""

        def _to_str(v):
            return v if v else ""

        try:
            self._conn.execute(
                """INSERT INTO events
                   (session_id, timestamp, author, user_prompt, tool_calls,
                    tool_results, actions, observations, git_diff, working_directory, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ev["session_id"],
                    event.timestamp,
                    event.author,
                    _to_str(event.user_prompt),
                    _to_str(ev["tool_calls"]),
                    _to_str(ev["tool_results"]),
                    _to_str(ev["actions"]),
                    _to_str(ev["observations"]),
                    _to_str(event.git_diff),
                    _to_str(event.working_directory),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"event {event.session_id!r} already recorded — Vera events "
                f"are append-only; save a new event instead of overwriting"
            ) from exc
        self._conn.commit()

        # Auto-extract summary
        self.summarize(event.session_id)
        return event.session_id

    @_locked
    def save_session(
        self,
        author: str,
        user_prompt: str,
        tool_calls: List[str] | None = None,
        tool_results: List[str] | None = None,
        git_diff: str = "",
        actions: List[str] | None = None,
        observations: List[str] | None = None,
        working_directory: str = "",
    ) -> str:
        """Convenience: create event + persist in one call."""
        sid = str(uuid.uuid4())
        self.add_event(SessionEvent(
            session_id=sid,
            timestamp=datetime.now(timezone.utc).isoformat(),
            author=author,
            user_prompt=user_prompt,
            tool_calls=list(tool_calls or []),
            tool_results=list(tool_results or []),
            actions=list(actions or []),
            observations=list(observations or []),
            git_diff=git_diff,
            working_directory=working_directory,
        ))
        return sid

    @_locked
    def summarize(self, session_id: str) -> SessionSummary | None:
        """Extract summary from raw event. Returns None if no event found."""
        row = self._conn.execute(
            "SELECT session_id, author, user_prompt, tool_calls, tool_results,"
            " actions, observations, git_diff, working_directory"
            " FROM events WHERE session_id=?", (session_id,)
        ).fetchone()
        if not row:
            return None
        cols = ["session_id", "author", "user_prompt", "tool_calls", "tool_results",
                "actions", "observations", "git_diff", "working_directory"]
        ev_dict = dict(zip(cols, row))

        actions_str = json.loads(ev_dict["actions"]) if ev_dict.get("actions") else []
        observations_str = json.loads(ev_dict["observations"]) if ev_dict.get("observations") else []
        tool_calls_str = json.loads(ev_dict["tool_calls"]) if ev_dict.get("tool_calls") else []
        ev = SessionEvent(
            session_id=session_id,
            timestamp="", author=ev_dict["author"],
            user_prompt=ev_dict["user_prompt"],
            tool_calls=tool_calls_str, tool_results=[],
            actions=actions_str, observations=observations_str,
            git_diff=ev_dict["git_diff"],
            working_directory=ev_dict["working_directory"],
        )

        summary = extract_summary(ev)
        self._conn.execute(
            """INSERT OR REPLACE INTO summaries
               (session_id, summary_text, facts, decisions, constraints, todos, unresolved, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                session_id,
                ev.user_prompt,
                json.dumps(summary.facts, ensure_ascii=False),
                json.dumps(summary.decisions, ensure_ascii=False),
                json.dumps(summary.constraints, ensure_ascii=False),
                json.dumps(summary.todos, ensure_ascii=False),
                json.dumps(summary.unresolved, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        # Persist extracted facts & constraints to dedicated tables. IDs are
        # deterministic (hash of session_id + text), not random — summarize()
        # can be called again on the same session (add_event() always does,
        # and callers may re-summarize explicitly) and must stay idempotent:
        # INSERT OR IGNORE then no-ops on a fact/constraint already recorded
        # for this session instead of piling up duplicate rows with fresh
        # random ids every time.
        for f_text in summary.facts:
            fid = _stable_id("fact", session_id, f_text)
            self._conn.execute(
                "INSERT OR IGNORE INTO facts VALUES (?,?,?,?,?,?)",
                (fid, f_text, session_id, "medium", "", datetime.now(timezone.utc).isoformat()),
            )
        for c_text in summary.constraints:
            cid = _stable_id("constraint", session_id, c_text)
            self._conn.execute(
                "INSERT OR IGNORE INTO constraints VALUES (?,?,?,?,?)",
                (cid, c_text, session_id, 1, datetime.now(timezone.utc).isoformat()),
            )

        self._conn.commit()
        return summary

    @_locked
    def search(self, query: str, k: int = 10) -> List[Dict[str, Any]]:
        """Text search across events + summaries + facts."""
        results: List[Dict[str, Any]] = []
        q = f"%{query}%"

        # Search events (user_prompt + actions + observations)
        for row in self._conn.execute(
            "SELECT session_id, timestamp, author, user_prompt FROM events "
            "WHERE user_prompt LIKE ? LIMIT ?", (q, k)
        ):
            results.append({
                "type": "event",
                "session_id": row[0],
                "timestamp": row[1],
                "author": row[2],
                "text": row[3][:200],
            })

        # Search facts
        for row in self._conn.execute(
            "SELECT id, text, source_session FROM facts WHERE text LIKE ? LIMIT ?", (q, k)
        ):
            results.append({
                "type": "fact",
                "id": row[0],
                "text": row[1][:200],
                "source_session": row[2],
            })

        # Search constraints
        for row in self._conn.execute(
            "SELECT id, text, active FROM constraints WHERE text LIKE ? LIMIT ?", (q, k)
        ):
            results.append({
                "type": "constraint",
                "id": row[0],
                "text": row[1][:200],
                "active": bool(row[2]),
            })

        # Search summaries for unresolved/todos
        for row in self._conn.execute(
            "SELECT session_id, todos, unresolved FROM summaries "
            "WHERE (todos LIKE ? OR unresolved LIKE ?) LIMIT ?", (q, q, k)
        ):
            todos = json.loads(row[1]) if row[1] else []
            unresolved = json.loads(row[2]) if row[2] else []
            results.append({
                "type": "summary",
                "session_id": row[0],
                "todos": todos,
                "unresolved": unresolved,
            })

        return results[:k]

    @_locked
    def check_consistency(
        self, current_action: str, current_proposal: str = ""
    ) -> Dict[str, Any]:
        """Check all active constraints against current action/proposal."""
        rows = self._conn.execute(
            "SELECT id, text FROM constraints WHERE active=1"
        ).fetchall()
        # Add empty source_session placeholder for module-level check_consistency
        constraints = [(r[0], r[1], "") for r in rows]

        contradiction = check_consistency(constraints, current_action, current_proposal)
        if contradiction:
            # Record the contradiction
            self._conn.execute(
                "INSERT OR REPLACE INTO contradictions "
                "(id, constraint_text, violating_action, detected_ts, sessions, resolved) VALUES (?,?,?,?,?,?)",
                (contradiction.id, contradiction.constraint_text, contradiction.violating_action,
                 contradiction.detected_ts, json.dumps([]), 0),
            )
            self._conn.commit()
            return {
                "status": "CONTRADICTION",
                "constraint": contradiction.constraint_text,
                "action": contradiction.violating_action,
                "session_id": contradiction.id,
            }
        return {"status": "OK", "constraints_checked": len(constraints)}

    @_locked
    def list_facts(self, category: str = "") -> List[Dict[str, Any]]:
        """List all stored facts."""
        if category:
            rows = self._conn.execute(
                "SELECT id, text, certainty, source_session FROM facts WHERE category=?", (category,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, text, certainty, source_session FROM facts ORDER BY created_at DESC"
            ).fetchall()
        return [{"id": r[0], "text": r[1], "certainty": r[2], "source": r[3]} for r in rows]

    @_locked
    def add_constraint(self, text: str, source_session: str = "") -> str:
        """Add a constraint. Returns constraint ID."""
        cid = str(uuid.uuid4())[:8]
        self._conn.execute(
            "INSERT INTO constraints VALUES (?,?,?,?,?)",
            (cid, text, source_session, 1, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()
        return cid

    @_locked
    def get_constraints(self) -> List[Dict[str, Any]]:
        """List all active constraints."""
        rows = self._conn.execute(
            "SELECT id, text, source_session, active FROM constraints ORDER BY created_at DESC"
        ).fetchall()
        return [
            {"id": r[0], "text": r[1], "source": r[2], "active": bool(r[3])}
            for r in rows
        ]

    @_locked
    def list_contradictions(self, resolved_only: bool = False) -> List[Dict[str, Any]]:
        """List all contradictions."""
        where = "WHERE resolved=0" if not resolved_only else ""
        rows = self._conn.execute(
            f"SELECT id, constraint_text, violating_action, detected_ts, resolved FROM contradictions {where}"
        ).fetchall()
        return [
            {"id": r[0], "constraint": r[1], "action": r[2], "detected": r[3], "resolved": bool(r[4])}
            for r in rows
        ]

    @_locked
    def get_session(self, session_id: str) -> Dict[str, Any] | None:
        """Get a single session event."""
        row = self._conn.execute(
            "SELECT session_id, timestamp, author, user_prompt, tool_calls,"
            " tool_results, actions, observations, git_diff, working_directory"
            " FROM events WHERE session_id=?", (session_id,)
        ).fetchone()
        if not row:
            return None
        cols = ["session_id", "timestamp", "author", "user_prompt", "tool_calls",
                "tool_results", "actions", "observations", "git_diff", "working_directory"]
        d = dict(zip(cols, row))
        for k in ("tool_calls", "tool_results", "actions", "observations"):
            if isinstance(d[k], str):
                d[k] = json.loads(d[k])
        return d

    # -- structured, append-only event log ----------------------------------
    # A "Vera turn" — triggered by the user saying "Vera" — is distilled by
    # the agent into REQUEST/CHANGE/REASON/RESULT/STATE and recorded as
    # several event_log rows sharing one turn_id, never edited afterward
    # (enforced by the append_only triggers in the schema). record_turn()
    # also feeds the same data through save_session() so the existing
    # facts/constraints/contradiction/search pipeline keeps working on top.
    #
    # Every row also carries three timestamps and a fingerprint:
    #   model_timestamp — what the calling agent says "now" is, if it says
    #                      anything (optional; different agents/clocks may
    #                      disagree, so this is informational, not the
    #                      dedup key by itself)
    #   received_at     — when this store actually processed the call
    #                      (server clock, authoritative, always present)
    #   committed_at     — when the SQLite commit for this turn completed
    #   fingerprint      — sha256(author, session, time bucket, request,
    #                      result) — see _turn_fingerprint(); a repeat of
    #                      that exact fingerprint is treated as the same
    #                      save arriving twice, not a new event.

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
    def is_paused(self) -> bool:
        row = self._conn.execute("SELECT paused FROM session_control WHERE id=1").fetchone()
        return bool(row and row[0])

    @_locked
    def pause(self, by: str = "local") -> Dict[str, Any]:
        """Stop record_turn() from saving content until resume() — the
        "Vera pause" / "before bulk agent work" case. The attempt itself is
        still logged (as control_log, not silently dropped) once resumed
        recording actually skips something, so a gap is always traceable."""
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
        become their own immutable event_log row under one turn_id — the
        request is always recorded even if every other field is empty."""
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

        turn_id = self.save_session(
            author=author,
            user_prompt=request,
            actions=[change] if change else [],
            observations=[result] if result else [],
        )
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

    @_locked
    def add_interpretation(self, text: str, author: str = "vera", lang: str = "en") -> str:
        """Record a standalone snapshot of how the codebase is currently
        understood, not tied to a specific turn — comparable over time via
        get_latest_interpretation() to see how understanding has shifted."""
        turn_id = str(uuid.uuid4())
        eid = self._append_event_log(turn_id, author, "interpretation", text, lang=lang)
        self._conn.commit()
        return eid

    @_locked
    def get_latest_interpretation(self, n: int = 2) -> List[Dict[str, Any]]:
        """Most recent interpretation snapshots, newest first — compare [0]
        (current) against [1] (previous) to see codebase-understanding drift."""
        rows = self._conn.execute(
            "SELECT id, turn_id, ts, author, content, lang FROM event_log"
            " WHERE type='interpretation' ORDER BY created_at DESC LIMIT ?", (n,)
        ).fetchall()
        return [
            {"id": r[0], "turn_id": r[1], "ts": r[2], "author": r[3], "content": r[4], "lang": r[5]}
            for r in rows
        ]

    @_locked
    def get_event_log(self, turn_id: str = "", type_: str = "", k: int = 50) -> List[Dict[str, Any]]:
        """Raw event_log rows, optionally filtered by turn or type, newest first."""
        where, params = [], []
        if turn_id:
            where.append("turn_id=?")
            params.append(turn_id)
        if type_:
            where.append("type=?")
            params.append(type_)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self._conn.execute(
            f"SELECT id, turn_id, ts, author, type, content, files, lang FROM event_log"
            f" {clause} ORDER BY created_at DESC LIMIT ?", (*params, k)
        ).fetchall()
        return [
            {"id": r[0], "turn_id": r[1], "ts": r[2], "author": r[3], "type": r[4],
             "content": r[5], "files": json.loads(r[6]) if r[6] else [], "lang": r[7]}
            for r in rows
        ]

    @_locked
    def get_project_state(self, recent_n: int = 8) -> Dict[str, Any]:
        """Everything a new session needs before starting work: the latest
        codebase interpretation, active constraints, open contradictions,
        and recent decisions/changes/unresolved-items/results across both
        authors. Bounded on purpose — meant to be shown every session
        start, not a full history dump; use search()/get_event_log() for
        the rest on demand."""
        interp = self.get_latest_interpretation(n=1)
        return {
            "interpretation": interp[0] if interp else None,
            "active_constraints": self.get_constraints(),
            "open_contradictions": self.list_contradictions(resolved_only=False),
            "recent_decisions": self.get_event_log(type_="decision", k=recent_n),
            "recent_changes": self.get_event_log(type_="change", k=recent_n),
            "recent_unresolved": self.get_event_log(type_="unresolved", k=recent_n),
            "recent_results": self.get_event_log(type_="result", k=recent_n),
            "recording_paused": self.is_paused(),
        }

    @_locked
    def sync(self, other_path: str | Path) -> Dict[str, Any]:
        """Merge another VeraStore into this one. Author-tagged merge."""
        other = VeraStore(other_path)
        merged: Dict[str, int] = {"inserted": 0, "conflicts": 0, "updated": 0}
        newly_inserted: List[str] = []

        for row in other._conn.execute(
            "SELECT session_id, timestamp, author, user_prompt, tool_calls,"
            " tool_results, actions, observations, git_diff, working_directory"
            " FROM events ORDER BY created_at"
        ).fetchall():
            cols = ["session_id", "timestamp", "author", "user_prompt", "tool_calls",
                    "tool_results", "actions", "observations", "git_diff", "working_directory"]
            ev_dict = dict(zip(cols, row))
            # Use event's original timestamp as created_at if available
            ev_dict["created_at"] = ev_dict.get("timestamp") or datetime.now(timezone.utc).isoformat()
            exists = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE session_id=?", (ev_dict["session_id"],)
            ).fetchone()[0]
            if exists:
                # Same session exists — compare content; newer author wins on diffs
                merged["conflicts"] += 1
                continue
            for k in ("tool_calls", "tool_results", "actions", "observations"):
                if isinstance(ev_dict.get(k), list):
                    ev_dict[k] = json.dumps(ev_dict[k], ensure_ascii=False)
            self._conn.execute(
                """INSERT INTO events
                   (session_id, timestamp, author, user_prompt, tool_calls,
                    tool_results, actions, observations, git_diff, working_directory, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(ev_dict[c] for c in cols) + (ev_dict["created_at"],),
            )
            merged["inserted"] += 1
            newly_inserted.append(ev_dict["session_id"])

        self._conn.commit()

        # Re-derive summaries/facts/constraints for every merged event through
        # the normal deterministic pipeline (idempotent — see summarize()),
        # rather than copying the other store's rows verbatim: the two
        # stores may have extracted the same text under different (older)
        # id schemes, and re-deriving locally keeps one consistent id space.
        for sid in newly_inserted:
            self.summarize(sid)

        # Facts/constraints not tied to a merged event (e.g. manually added
        # via add_constraint()) aren't reachable through summarize() above —
        # copy those across, deduped by (source_session, text) rather than
        # by id, since id schemes may differ between stores.
        for row in other._conn.execute(
            "SELECT id, text, source_session, certainty, category, created_at FROM facts"
        ).fetchall():
            fid, txt, src, certainty, category, created_at = row
            exists_f = self._conn.execute(
                "SELECT COUNT(*) FROM facts WHERE text=? AND source_session=?", (txt, src)
            ).fetchone()[0]
            if not exists_f:
                self._conn.execute(
                    "INSERT OR IGNORE INTO facts VALUES (?,?,?,?,?,?)",
                    (fid, txt, src, certainty, category, created_at),
                )
                merged["updated"] += 1

        for row in other._conn.execute(
            "SELECT id, text, source_session, active, created_at FROM constraints"
        ).fetchall():
            cid, txt, src, active, created_at = row
            exists_c = self._conn.execute(
                "SELECT COUNT(*) FROM constraints WHERE text=? AND source_session=?", (txt, src)
            ).fetchone()[0]
            if not exists_c:
                self._conn.execute(
                    "INSERT OR IGNORE INTO constraints VALUES (?,?,?,?,?)",
                    (cid, txt, src, active, created_at),
                )
                merged["updated"] += 1

        # event_log rows have a globally-unique id and are append-only on
        # both sides, so merging is a plain id-keyed copy — no re-derivation
        # needed the way events/facts/constraints get above. Columns are
        # named explicitly (not SELECT * / bare VALUES) so this keeps
        # working if the schema grows again — a bare positional INSERT
        # breaks the moment the table has more columns than the tuple.
        _EVENT_LOG_COLS = (
            "id, turn_id, ts, author, type, content, files, lang, created_at, "
            "session_id, model_timestamp, received_at, committed_at, fingerprint"
        )
        for row in other._conn.execute(f"SELECT {_EVENT_LOG_COLS} FROM event_log").fetchall():
            eid = row[0]
            exists_e = self._conn.execute(
                "SELECT COUNT(*) FROM event_log WHERE id=?", (eid,)
            ).fetchone()[0]
            if not exists_e:
                placeholders = ",".join("?" * len(row))
                self._conn.execute(
                    f"INSERT OR IGNORE INTO event_log ({_EVENT_LOG_COLS}) VALUES ({placeholders})", row
                )
                merged["updated"] += 1

        # control_log likewise: globally-unique id, append-only, plain
        # id-keyed copy. session_control (the pause switch) deliberately
        # does NOT sync — pause/resume is a local operational decision for
        # this store, not something a merge should import from elsewhere.
        for row in other._conn.execute(
            "SELECT id, ts, kind, fingerprint, original_turn_id, session_id, author, note, created_at"
            " FROM control_log"
        ).fetchall():
            cid = row[0]
            exists_c = self._conn.execute(
                "SELECT COUNT(*) FROM control_log WHERE id=?", (cid,)
            ).fetchone()[0]
            if not exists_c:
                self._conn.execute(
                    "INSERT OR IGNORE INTO control_log"
                    " (id, ts, kind, fingerprint, original_turn_id, session_id, author, note, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)", row
                )
                merged["updated"] += 1

        self._conn.commit()
        return merged

    @_locked
    def report(self) -> Dict[str, Any]:
        """Store statistics."""
        n_events = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        n_summaries = self._conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
        n_facts = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        n_constraints = self._conn.execute("SELECT COUNT(*) FROM constraints WHERE active=1").fetchone()[0]
        n_contradictions = self._conn.execute("SELECT COUNT(*) FROM contradictions WHERE resolved=0").fetchone()[0]
        authors = dict(self._conn.execute(
            "SELECT author, COUNT(*) FROM events GROUP BY author"
        ).fetchall())
        return {
            "events": n_events,
            "summaries": n_summaries,
            "facts": n_facts,
            "constraints": n_constraints,
            "contradictions": n_contradictions,
            "authors": authors,
        }

    @_locked
    def status(self) -> Dict[str, Any]:
        """Live session status: pause state, the last event actually
        recorded, the last control decision (a duplicate suppressed, a
        paused save skipped, a pause/resume), and running counts — the
        "why isn't there an event here" view, distinct from report()'s
        aggregate counts."""
        paused = self.is_paused()
        last_event = self._conn.execute(
            "SELECT turn_id, ts, author, type FROM event_log ORDER BY created_at DESC LIMIT 1"
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
            "state": "PAUSED" if paused else "READY",
            "last_event": (
                {"turn_id": last_event[0], "ts": last_event[1], "author": last_event[2], "type": last_event[3]}
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

    def close(self) -> None:
        self._conn.close()

    # context manager ------------------------------------------------------
    def __enter__(self) -> VeraStore:
        return self

    def __exit__(self, *args) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def init_store(path: str | Path) -> VeraStore:
    """Create or open a Vera store."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return VeraStore(p)
