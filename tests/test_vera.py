"""Tests for the properties that actually matter for a memory layer:

Two authors ("claude" and "local") writing into the *same* store file
stay correctly tagged and both readable; the contradiction engine catches
a proposal that violates a recorded constraint (the canonical stdlib-only
vs. "add ezdxf" scenario); summarizing a session is idempotent —
re-running it must never pile up duplicate fact/constraint rows; syncing
two independently-grown stores merges without dropping data, without id
collisions, and settles to a no-op on a second sync; the structured,
append-only event log (record_turn/get_project_state/interpretation) is
actually enforced append-only at the database level, not just by
convention; and every supported guide language renders without error or
template artifacts, with language aliases resolving correctly.
"""
from __future__ import annotations

import sqlite3

import pytest

from vera.i18n import SUPPORTED_LANGUAGES, render_guide, render_project_state, resolve_lang
from vera.store import SessionEvent, VeraStore, extract_summary, init_store


@pytest.fixture
def store(tmp_path):
    s = init_store(tmp_path / ".vera_store.db")
    yield s
    s.close()


def test_contradiction_detected(store):
    """A recorded 'stdlib-only / no external dependency' constraint must
    trip when a later proposal wants to add a pip package — the canonical
    scenario this whole feature exists to catch."""
    store.add_constraint("photoloset must be stdlib-only, no external dependency")

    ok_result = store.check_consistency(current_action="refactor dxf.py text-style handling")
    bad_result = store.check_consistency(
        current_action="install ezdxf via pip",
        current_proposal="Claude: add ezdxf as a dependency to fix DXF text rendering",
    )

    assert ok_result["status"] == "OK"
    assert bad_result["status"] == "CONTRADICTION"
    assert "stdlib-only" in bad_result["constraint"]


def test_dual_author_same_file(tmp_path):
    """Claude (via the MCP tool path) and local (via the CLI path) writing
    to the SAME store file must both land, each correctly author-tagged —
    this is the whole point of pointing both sides at one shared db
    instead of needing an explicit sync for the common case."""
    db = tmp_path / ".vera_store.db"
    claude_side = VeraStore(db)
    claude_side.save_session(author="claude", user_prompt="fixed dxf.py text-style handling")
    claude_side.close()

    local_side = VeraStore(db)
    local_side.save_session(author="local", user_prompt="confirmed in QCAD, labels render correctly")
    report = local_side.report()
    local_side.close()

    assert report["events"] == 2
    assert report["authors"].get("claude") == 1
    assert report["authors"].get("local") == 1


def test_summarize_idempotent(store):
    """Regression: summarize() used to mint a fresh random id per call, so
    re-summarizing the same session (which add_event() already does once,
    and which callers may trigger again) piled up duplicate fact rows
    forever. Stable content-hashed ids must make repeat calls a no-op."""
    sid = store.save_session(
        author="local", user_prompt="test",
        observations=["FACT: dup check works this way"],
    )
    n_after_first = len(store.list_facts())
    store.summarize(sid)
    store.summarize(sid)
    store.summarize(sid)
    n_after_repeat = len(store.list_facts())

    assert n_after_first == 1
    assert n_after_repeat == 1


def test_fact_marker_not_duplicated():
    """Regression: extracting a single 'FACT: X' observation used to also
    match it a second time as a generic pattern, producing two rows for
    one fact ('X' and 'FACT: X'). One marker -> exactly one fact."""
    ev = SessionEvent(
        session_id="s1", timestamp="", author="local", user_prompt="",
        observations=["FACT: only one fact here"],
    )
    summary = extract_summary(ev)
    assert summary.facts == ["only one fact here"]


def test_sync_merges_and_settles(tmp_path):
    """Two independently-grown stores (e.g. Claude's machine and a local
    machine that were never on the same filesystem) sync without losing
    either side's events/authors/facts, and a second sync is a true no-op
    (nothing double-counted) — the cross-machine handoff path."""
    a_path = tmp_path / "a" / ".vera_store.db"
    b_path = tmp_path / "b" / ".vera_store.db"
    a = init_store(a_path)
    a.add_constraint("no external dependency")
    a.save_session(author="claude", user_prompt="A-side prompt")

    b = init_store(b_path)
    b.save_session(author="local", user_prompt="B-side prompt", observations=["FACT: B found something"])
    b.close()

    merged1 = a.sync(b_path)
    report1 = a.report()
    facts1 = a.list_facts()
    merged2 = a.sync(b_path)  # re-sync: should settle to a no-op
    report2 = a.report()
    a.close()

    assert merged1["inserted"] == 1
    assert report1["events"] == 2
    assert report1["authors"].get("claude") == 1
    assert report1["authors"].get("local") == 1
    assert any(f["text"] == "B found something" for f in facts1)  # B's fact re-derived on merge
    assert merged2["inserted"] == 0  # second sync is a true no-op
    assert report2["events"] == 2  # unchanged on re-sync


def test_search_finds_across_layers(store):
    """search() must surface hits from events, facts, and constraints —
    not just raw event text — since retrieval across all layers is the
    point of the store, not just a prompt log."""
    store.add_constraint("DXF text style must stay stdlib-only")
    store.save_session(
        author="claude",
        user_prompt="investigate DXF label rendering",
        observations=["FACT: Japanese labels render incorrectly in QCAD"],
    )
    results = store.search("DXF")

    types_found = {r["type"] for r in results}
    assert {"event", "constraint"}.issubset(types_found)


def test_event_log_append_only(store):
    """The append-only guarantee for event_log must hold at the DB level,
    not just by convention: UPDATE and DELETE are rejected outright, and a
    reused events.session_id raises instead of silently overwriting."""
    r = store.record_turn(author="local", request="test", change="did a thing")
    eid = r["event_ids"][0]

    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("UPDATE event_log SET content=? WHERE id=?", ("tampered", eid))

    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM event_log WHERE id=?", (eid,))

    with pytest.raises(ValueError):
        store.add_event(SessionEvent(
            session_id=r["turn_id"], timestamp="", author="local",
            user_prompt="overwrite attempt",
        ))


def test_record_turn_populates_project_state(store):
    """record_turn() must show up in get_project_state() immediately — the
    actual "session hand-off" path: a new session calls vera_session_start
    and must see what the previous one just did, not just a raw event log."""
    store.record_turn(
        author="claude",
        request="switch to OAuth",
        change="added src/auth/oauth.py",
        reason="isolate OAuth in one middleware layer",
        files=["src/auth/oauth.py"],
        result="OAuth flow working",
        interpretation="auth/ now owns all OAuth authentication",
        unresolved="no tests yet",
    )
    state = store.get_project_state()

    assert state["interpretation"] is not None
    assert "OAuth" in state["interpretation"]["content"]
    assert any("OAuth" in d["content"] for d in state["recent_decisions"])
    assert any("oauth.py" in c["content"] for c in state["recent_changes"])
    assert any(f == "src/auth/oauth.py" for c in state["recent_changes"] for f in c["files"])
    assert any("no tests" in u["content"] for u in state["recent_unresolved"])


def test_guide_all_languages_render():
    """Every supported language must render both the guide and the
    project-state view without error and without leaking a template
    artifact (e.g. a stray '## start' from a formatting bug), and language
    aliases (code / English name / native name) must resolve correctly —
    the exact "start Vera guide in German" / "ドイツ語でVera guideを起動して"
    scenario this was built for."""
    empty_state = {
        "interpretation": None, "active_constraints": [], "open_contradictions": [],
        "recent_decisions": [], "recent_changes": [], "recent_unresolved": [], "recent_results": [],
    }
    for code in SUPPORTED_LANGUAGES:
        guide = render_guide(code)
        state = render_project_state(empty_state, code)
        assert len(guide) >= 100, code
        assert "## start" not in guide, code
        assert len(state) >= 20, code
        # Regression: this repo's CLI is flattened (`vera start`, `vera
        # record`, ...) — the guide text was copy-pasted from the parent
        # repo's `vera session <cmd>` phrasing during extraction and still
        # told users to run commands that don't exist here, including two
        # occurrences split across adjacent string literals that a naive
        # single-line sed pass missed.
        assert "vera session" not in guide, code

    assert resolve_lang("German") == "de"
    assert resolve_lang("Deutsch") == "de"
    assert resolve_lang("ドイツ語") == "de"
    # Fallback substring matching: a whole phrase containing a language
    # name/native word, not just a clean code, must still resolve —
    # without the bare 2-letter codes falsely matching inside unrelated text.
    assert resolve_lang("英語で開いて") == "en"
    assert resolve_lang("in English please") == "en"
    assert resolve_lang("auf Deutsch bitte") == "de"
    assert resolve_lang("this is fine") == "en"  # contains "it"/"hi"-like fragments but no real match
    assert resolve_lang("history of this") == "en"  # "hi" substring must NOT falsely match Hindi
    assert resolve_lang("日本語") == "ja"
    assert resolve_lang("totally-unknown-xyz") == "en"  # unknown falls back, never errors


def test_sync_carries_event_log(tmp_path):
    """The structured event_log — not just the legacy events table — must
    also cross a sync between two independently-grown stores."""
    a_path = tmp_path / "a" / ".vera_store.db"
    b_path = tmp_path / "b" / ".vera_store.db"
    a = init_store(a_path)
    b = init_store(b_path)
    b.record_turn(author="local", request="B did something", interpretation="B's understanding")
    b.close()

    a.sync(b_path)
    state = a.get_project_state()
    a.close()

    assert state["interpretation"] is not None
    assert state["interpretation"]["content"] == "B's understanding"


def test_duplicate_turn_suppressed(store):
    """An agent re-sending the exact same save (same author/session/
    request/result, close in time) must not create a second event — the
    original turn_id comes back with duplicate_suppressed=True, and the
    decision itself is logged (not silently dropped)."""
    r1 = store.record_turn(author="claude", request="fix DXF labels", result="fixed")
    assert "duplicate_suppressed" not in r1

    r2 = store.record_turn(author="claude", request="fix DXF labels", result="fixed")
    assert r2["duplicate_suppressed"] is True
    assert r2["turn_id"] == r1["turn_id"]
    assert r2["event_ids"] == []

    status = store.status()
    assert status["duplicates_suppressed_total"] == 1
    assert status["last_control"]["kind"] == "duplicate_suppressed"


def test_different_content_not_suppressed(store):
    """Same author/request but a genuinely different result must NOT be
    treated as a duplicate — the fingerprint includes result, not just
    request, so two distinct outcomes both get recorded."""
    r1 = store.record_turn(author="claude", request="fix DXF labels", result="fixed via A")
    r2 = store.record_turn(author="claude", request="fix DXF labels", result="fixed via B")
    assert "duplicate_suppressed" not in r2
    assert r1["turn_id"] != r2["turn_id"]


def test_pause_blocks_recording_and_resume_restores_it(store):
    """pause() must stop record_turn() from saving content (returning a
    clear skipped marker, not silently succeeding), get_project_state()
    must surface the paused state, and resume() must restore normal
    recording — the "Vera pause" / bulk-agent-work scenario."""
    assert store.get_project_state()["recording_paused"] is False

    store.pause(by="local")
    assert store.is_paused() is True
    assert store.get_project_state()["recording_paused"] is True

    result = store.record_turn(author="claude", request="should be skipped", result="n/a")
    assert result == {"paused": True, "skipped": True}
    assert store.status()["paused_skips_total"] == 1

    store.resume(by="local")
    assert store.is_paused() is False
    assert store.get_project_state()["recording_paused"] is False

    result2 = store.record_turn(author="claude", request="recorded after resume", result="done")
    assert "paused" not in result2
    assert "duplicate_suppressed" not in result2


def test_event_log_schema_migration_from_pre_dedup_store(tmp_path):
    """Opening a store created before the dedup/pause columns existed must
    add them via ALTER TABLE (not require recreating the store), without
    losing any pre-existing rows — the real upgrade path for every store
    created before this feature landed."""
    db_path = tmp_path / ".vera_store.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE events (
            session_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
            author TEXT NOT NULL CHECK(author IN ('claude','local')),
            user_prompt TEXT, tool_calls TEXT, tool_results TEXT,
            actions TEXT, observations TEXT, git_diff TEXT,
            working_directory TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE event_log (
            id TEXT PRIMARY KEY, turn_id TEXT NOT NULL, ts TEXT NOT NULL,
            author TEXT NOT NULL CHECK(author IN ('claude','local','vera')),
            type TEXT NOT NULL, content TEXT NOT NULL, files TEXT,
            lang TEXT NOT NULL DEFAULT 'en', created_at TEXT NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO event_log (id, turn_id, ts, author, type, content, files, lang, created_at)"
        " VALUES ('e1','t1','2020-01-01T00:00:00Z','local','request','pre-existing row','[]','en','2020-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    store = VeraStore(db_path)
    try:
        cols = {row[1] for row in store._conn.execute("PRAGMA table_info(event_log)")}
        assert {"session_id", "model_timestamp", "received_at", "committed_at", "fingerprint"} <= cols
        # pre-existing row survived the migration untouched
        row = store._conn.execute("SELECT content FROM event_log WHERE id='e1'").fetchone()
        assert row[0] == "pre-existing row"
        # and the store is fully functional afterward
        r = store.record_turn(author="claude", request="after migration", result="ok")
        assert "duplicate_suppressed" not in r
        assert store.status()["events_this_session"] >= 1
    finally:
        store.close()


def test_sync_carries_control_log_and_new_event_log_columns(tmp_path):
    """Regression: sync()'s event_log merge used a bare 9-placeholder
    INSERT that would crash once the table grew the 5 dedup/timestamp
    columns (mismatched column count). Must merge cleanly with named
    columns, and control_log entries must cross too — pause state itself
    (session_control) deliberately does not."""
    a_path = tmp_path / "a" / ".vera_store.db"
    b_path = tmp_path / "b" / ".vera_store.db"
    a = init_store(a_path)
    b = init_store(b_path)

    b.record_turn(author="local", request="dup test", result="same")
    b.record_turn(author="local", request="dup test", result="same")  # suppressed on B's side
    assert b.status()["duplicates_suppressed_total"] == 1
    b.close()

    merged = a.sync(b_path)
    a_status = a.status()
    a.close()

    assert merged["inserted"] == 1  # only the one real event, not the suppressed duplicate
    assert a_status["duplicates_suppressed_total"] == 1  # control_log entry carried over
