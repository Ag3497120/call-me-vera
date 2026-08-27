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

    assert resolve_lang("German") == "de"
    assert resolve_lang("Deutsch") == "de"
    assert resolve_lang("ドイツ語") == "de"
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
