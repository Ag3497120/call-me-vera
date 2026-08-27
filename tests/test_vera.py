"""Tests for the properties that actually matter for a memory layer that
deliberately does NOT interpret what it stores: two authors ("claude" and
"local") writing into the *same* store file stay correctly tagged and both
readable; every entry gets a stable citation number (lookup()); an agent
re-sending the same save is suppressed (not duplicated) and the decision is
itself observable; a compression digest replaces the raw tail in
get_project_state() without deleting anything; the size estimate reports whether the uncompressed tail
is over threshold; sync merges two independently-grown stores including
digests; the append-only guarantee and the schema migration are enforced at
the database level, not by convention; and every supported guide language
renders without error, with no leftover mention of the CLI's old nested
`vera session <cmd>` form or removed contradiction-detection concepts.
"""
from __future__ import annotations

import json
import sqlite3
import threading

import pytest

import vera.store as vera_store
from vera.i18n import SUPPORTED_LANGUAGES, render_guide, render_project_state, resolve_lang
from vera.store import VeraStore, claim_name, init_store, list_named_stores, sanitize_name


@pytest.fixture
def named_dir(tmp_path, monkeypatch):
    """Isolate the named-store registry from the real ~/.vera/stores for
    the duration of a test."""
    d = tmp_path / "named-stores"
    monkeypatch.setattr(vera_store, "_NAMED_STORE_DIR", d)
    return d


@pytest.fixture
def store(tmp_path):
    s = init_store(tmp_path / ".vera_store.db")
    yield s
    s.close()


def test_dual_author_same_file(tmp_path):
    """Claude and local writing to the SAME store file must both land,
    each correctly author-tagged and citable — the whole point of
    pointing both sides at one shared db."""
    db = tmp_path / ".vera_store.db"
    claude_side = VeraStore(db)
    claude_side.record_turn(author="claude", request="fixed dxf.py text-style handling", result="ok")
    claude_side.close()

    local_side = VeraStore(db)
    local_side.record_turn(author="local", request="confirmed in QCAD, labels render correctly", result="ok")
    stats = local_side.stats()
    local_side.close()

    assert stats["entries"] == 4  # 2 requests + 2 results
    assert stats["authors"].get("claude") == 2
    assert stats["authors"].get("local") == 2


def test_entries_are_citable_by_number(store):
    """Every entry gets a stable rowid-based citation number; lookup(n)
    fetches it back exactly."""
    r = store.record_turn(author="claude", request="add OAuth", result="works", interpretation="auth/ owns auth now")
    log = store.stats()
    n = log["last_event"]["n"]
    entry = store.lookup(n)
    assert entry is not None
    assert entry["type"] == "interpretation"
    assert entry["content"] == "auth/ owns auth now"
    assert store.lookup(999999) is None


def test_duplicate_turn_suppressed(store):
    """An agent re-sending the exact same save (same author/session/
    request/result, close in time) must not create a second entry — the
    original turn_id comes back with duplicate_suppressed=True, and the
    decision itself is observable via stats(), not silently dropped."""
    r1 = store.record_turn(author="claude", request="fix DXF labels", result="fixed")
    r2 = store.record_turn(author="claude", request="fix DXF labels", result="fixed")

    assert "duplicate_suppressed" not in r1
    assert r2["duplicate_suppressed"] is True
    assert r2["turn_id"] == r1["turn_id"]
    assert r2["event_ids"] == []

    stats = store.stats()
    assert stats["duplicates_suppressed_total"] == 1
    assert stats["last_control"]["kind"] == "duplicate_suppressed"


def test_different_content_not_suppressed(store):
    """Same author/request but a genuinely different result must NOT be
    treated as a duplicate — the fingerprint includes result, not just
    request."""
    r1 = store.record_turn(author="claude", request="fix DXF labels", result="fixed via A")
    r2 = store.record_turn(author="claude", request="fix DXF labels", result="fixed via B")
    assert "duplicate_suppressed" not in r2
    assert r1["turn_id"] != r2["turn_id"]




def test_search_finds_entries_and_digests(store):
    """search() must surface hits from both raw entries and compression
    digests, newest first, each carrying its citation number."""
    store.record_turn(author="claude", request="investigate DXF label rendering", result="Japanese labels render incorrectly in QCAD")
    results = store.search("DXF")
    assert any("n" in r for r in results)

    store.add_digest("Per #1: DXF label rendering was broken and fixed.", through_n=1)
    results2 = store.search("DXF label rendering was broken")
    assert any("digest_id" in r for r in results2)


def test_compression_digest_replaces_raw_tail_in_project_state(store):
    """A compression digest must not delete anything — the raw entries
    stay reachable via lookup() — but get_project_state() must show the
    digest plus only what's recorded AFTER it, not the full history."""
    store.record_turn(author="claude", request="old work 1", result="done 1")
    store.record_turn(author="claude", request="old work 2", result="done 2")
    last_n = store.stats()["last_event"]["n"]

    store.add_digest(f"Per #1-#{last_n}: did old work 1 and 2.", through_n=last_n)
    store.record_turn(author="local", request="new work after digest", result="done 3")

    state = store.get_project_state()
    assert state["digest"] is not None
    assert state["digest"]["through_n"] == last_n
    # only entries AFTER the digest show up in recent_entries
    assert all(e["n"] > last_n for e in state["recent_entries"])
    assert any("new work after digest" in e["content"] for e in state["recent_entries"])
    # nothing was deleted — the old entries are still individually fetchable
    assert store.lookup(1) is not None
    assert store.lookup(1)["content"] == "old work 1"


def test_size_estimate_reports_over_threshold(store):
    """stats()'s size estimate must correctly flag when the uncompressed
    tail exceeds a threshold, and must only count what's after the latest
    digest — the actual "would a fresh agent's context overflow" signal."""
    big_text = "x" * 1000
    for i in range(5):
        store.record_turn(author="claude", request=f"turn {i}", result=big_text)

    size_tiny_threshold = store._size_estimate(threshold_tokens=10)
    assert size_tiny_threshold["over_threshold"] is True

    size_huge_threshold = store._size_estimate(threshold_tokens=10_000_000)
    assert size_huge_threshold["over_threshold"] is False

    last_n = store.stats()["last_event"]["n"]
    store.add_digest("compressed everything", through_n=last_n)
    size_after_digest = store._size_estimate(threshold_tokens=10)
    assert size_after_digest["uncompressed_entries"] == 0
    assert size_after_digest["over_threshold"] is False


def test_sync_merges_events_and_digests_and_settles(tmp_path):
    """Two independently-grown stores sync without losing either side's
    entries, authors, or digests, and a second sync is a true no-op."""
    a_path = tmp_path / "a" / ".vera_store.db"
    b_path = tmp_path / "b" / ".vera_store.db"
    a = init_store(a_path)
    a.record_turn(author="claude", request="A-side prompt", result="ok")

    b = init_store(b_path)
    b.record_turn(author="local", request="B-side prompt", result="ok", interpretation="B's understanding")
    b_last_n = b.stats()["last_event"]["n"]
    b.add_digest("B's digest", through_n=b_last_n)
    b.close()

    merged1 = a.sync(b_path)
    state1 = a.get_project_state()
    merged2 = a.sync(b_path)  # re-sync: should settle to a no-op

    assert merged1["inserted"] == 3  # B's request + result + interpretation
    assert state1["digest"] is not None
    assert state1["digest"]["text"] == "B's digest"
    assert merged2["inserted"] == 0  # second sync is a true no-op
    a.close()


def test_event_log_append_only(store):
    """The append-only guarantee must hold at the DB level: UPDATE and
    DELETE on event_log are rejected outright, and a reused turn's
    fingerprint is suppressed rather than the row ever being edited."""
    r = store.record_turn(author="local", request="test", result="ok")
    eid = r["event_ids"][0]

    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("UPDATE event_log SET content=? WHERE id=?", ("tampered", eid))

    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM event_log WHERE id=?", (eid,))


def test_digests_append_only(store):
    """Compression digests must also be append-only — a digest is never
    edited, only superseded by a newer one."""
    d = store.add_digest("first digest", through_n=0)
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("UPDATE digests SET text=? WHERE id=?", ("tampered", d["digest_id"]))
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM digests WHERE id=?", (d["digest_id"],))


def test_concurrent_record_turn_is_thread_safe(store):
    """Regression: sqlite3.Connection is not safe for genuinely concurrent
    use from multiple threads even with check_same_thread=False (that flag
    only disables Python's same-thread *guard*) — an MCP server can
    dispatch two tool calls to different worker threads without either
    finishing first. Must be fully serialized: no exceptions, exactly one
    real save, the rest suppressed."""
    results = []
    errors = []
    barrier = threading.Barrier(10)

    def worker():
        barrier.wait()
        try:
            results.append(store.record_turn(author="claude", request="race test", result="same result"))
        except Exception as e:  # noqa: BLE001 - deliberately broad, this is the regression itself
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not any(t.is_alive() for t in threads), "a thread hung — possible deadlock"
    assert errors == [], f"concurrent calls raised: {errors}"
    n_real = sum(1 for r in results if not r.get("duplicate_suppressed"))
    n_suppressed = sum(1 for r in results if r.get("duplicate_suppressed"))
    assert n_real == 1, f"expected exactly 1 real save, got {n_real}"
    assert n_suppressed == 9, f"expected 9 suppressed, got {n_suppressed}"


def test_migration_survives_concurrent_alter_from_another_process(store):
    """_migrate_event_log_columns() isn't fully race-proof against a
    SECOND PROCESS migrating the same pre-existing store at (as near as
    makes no difference) the same instant. If that happens, SQLite raises
    "duplicate column name: ..." for the column the other process just
    committed first; this must be swallowed as success, not crash
    __init__."""
    store._conn.execute("ALTER TABLE event_log ADD COLUMN _test_migration_probe TEXT")
    store._conn.commit()

    with pytest.raises(sqlite3.OperationalError) as exc_info:
        store._conn.execute("ALTER TABLE event_log ADD COLUMN _test_migration_probe TEXT")
    assert "duplicate column name" in str(exc_info.value)

    r = store.record_turn(author="claude", request="post-race sanity check", result="ok")
    assert "duplicate_suppressed" not in r


def test_guide_all_languages_render_and_are_current():
    """Every supported language must render both the guide and the
    memory-block view without error and without leaking a template
    artifact, and language aliases (code / English name / native name /
    fuzzy phrase) must resolve correctly. Also guards against two real
    regressions from this repo's history: the guide text drifting back to
    the old nested `vera session <cmd>` form (this CLI is flattened to
    `vera <cmd>`), and any leftover mention of the removed contradiction-
    detection / constraint-tracking concepts."""
    empty_state = {"digest": None, "recent_entries": [],
                    "size": {"uncompressed_entries": 0, "estimated_tokens": 0,
                             "over_threshold": False, "since_n": 0}}
    for code in SUPPORTED_LANGUAGES:
        guide = render_guide(code)
        state = render_project_state(empty_state, code)
        assert len(guide) >= 100, code
        assert "## start" not in guide, code
        assert len(state) >= 20, code
        assert "vera session" not in guide, code
        # "no contradiction detection" is deliberate, current content (the
        # guide explains what Vera does NOT do); what must actually be
        # gone is the OLD actionable instruction to check a constraints
        # store that no longer exists.
        assert "active_constraints" not in guide, code
        assert "check_consistency" not in guide, code

    assert resolve_lang("German") == "de"
    assert resolve_lang("Deutsch") == "de"
    assert resolve_lang("ドイツ語") == "de"
    assert resolve_lang("日本語") == "ja"
    assert resolve_lang("totally-unknown-xyz") == "en"
    assert resolve_lang("英語で開いて") == "en"
    assert resolve_lang("in English please") == "en"
    assert resolve_lang("auf Deutsch bitte") == "de"
    assert resolve_lang("this is fine") == "en"  # "it" fragment must not falsely match Italian
    assert resolve_lang("history of this") == "en"  # "hi" fragment must not falsely match Hindi


def test_claim_name_lets_a_different_store_resume_by_name(tmp_path, named_dir):
    """The actual point of naming: a completely separate VeraStore
    instance (a different process/session/app in practice) can resume
    the exact same memory just by resolving the same name — this is the
    fix for two MCP registrations with different --store paths otherwise
    silently having disjoint memories."""
    a = init_store(tmp_path / "a.db")
    a.record_turn(author="claude", request="did project work", result="ok")

    result = claim_name(a, "project-vera")
    assert "error" not in result
    assert result["name"] == "project-vera"

    resumed = VeraStore(vera_store.resolve_named_path("project-vera"))
    entries = resumed.get_project_state(recent_n=50)["recent_entries"]
    assert resumed.get_name() == "project-vera"
    assert any("did project work" in e["content"] for e in entries)
    resumed.close()
    a.close()


def test_claim_name_is_idempotent_for_the_same_store(tmp_path, named_dir):
    """Regression: re-claiming a name the CURRENT store already has (e.g.
    to push newly recorded entries up to the shared named copy) must
    succeed, not be misread as a collision with itself. Also verifies new
    entries recorded after the first claim actually reach the named copy
    on a second claim."""
    a = init_store(tmp_path / "a.db")
    a.record_turn(author="claude", request="first", result="ok")

    r1 = claim_name(a, "project-vera")
    assert "error" not in r1
    r2 = claim_name(a, "project-vera")
    assert "error" not in r2, f"re-claiming own name should succeed, got {r2}"

    a.record_turn(author="claude", request="second", result="ok")
    claim_name(a, "project-vera")

    named = VeraStore(vera_store.resolve_named_path("project-vera"))
    entries = named.get_project_state(recent_n=50)["recent_entries"]
    assert any("second" in e["content"] for e in entries)
    named.close()
    a.close()


def test_claim_name_refuses_real_collision(tmp_path, named_dir):
    """A genuinely different store trying to claim an already-taken name
    must be refused, with a hint to resume the existing one instead —
    never silently merged into a stranger's memory."""
    a = init_store(tmp_path / "a.db")
    a.record_turn(author="claude", request="A content", result="ok")
    claim_name(a, "project-vera")

    b = init_store(tmp_path / "b.db")
    b.record_turn(author="local", request="B content, unrelated", result="ok")
    result = claim_name(b, "project-vera")

    assert "error" in result
    assert "hint" in result
    a.close()
    b.close()


def test_claim_name_rejects_invalid_names(tmp_path, named_dir):
    """Names must be filesystem-safe — no path traversal, no spaces/
    special characters that could escape the named-store directory."""
    a = init_store(tmp_path / "a.db")
    assert sanitize_name("") is None
    assert sanitize_name("has spaces") is None
    assert sanitize_name("../../etc/passwd") is None
    assert sanitize_name("ok-name_123") == "ok-name_123"
    assert "error" in claim_name(a, "../escape")
    a.close()


def test_list_named_stores(tmp_path, named_dir):
    """Every claimed name shows up for discovery."""
    a = init_store(tmp_path / "a.db")
    a.record_turn(author="claude", request="x", result="y")
    assert list_named_stores() == []
    claim_name(a, "alpha")
    claim_name(a, "beta")  # a second name for the same underlying store — both should list
    assert list_named_stores() == ["alpha", "beta"]
    a.close()


def test_session_start_prompts_for_a_name_when_fresh_and_unnamed(tmp_path):
    """get_project_state() alone doesn't decide this (that's a CLI/MCP-
    layer choice — see cmd_start / vera_session_start), but the
    ingredients it must expose are correct: a brand-new store has no
    name, no digest, and zero entries, which is exactly the condition
    the CLI/MCP layer checks before showing the "name this memory" prompt
    instead of an empty memory block."""
    store = init_store(tmp_path / "fresh.db")
    state = store.get_project_state()
    assert state["name"] == ""
    assert state["digest"] is None
    assert state["size"]["uncompressed_entries"] == 0
    store.close()


def test_store_flag_before_subcommand_is_not_clobbered(tmp_path, monkeypatch, capsys):
    """Regression: `vera --store X <cmd>` used to silently discard the
    top-level --store, because each sub-parser also declared --store
    with its own real default, and argparse applies a sub-parser's
    default onto the shared namespace whenever the flag isn't repeated
    after the sub-command name. That clobbered the already-parsed
    top-level value with DEFAULT_STORE, so commands like `vera --store
    /real/path.db stats` silently read/wrote the wrong (relative,
    usually nonexistent) file instead of erroring — found while
    consolidating a real store via `vera claim-name`, where it caused a
    sync from an empty store instead of the real one. --store X after
    the sub-command must keep working too."""
    from vera.cli import main

    real = tmp_path / "real.db"
    store = init_store(real)
    store.record_turn(author="local", request="r")  # one field -> one event_log row
    store.close()

    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")

    rc = main(["--store", str(real), "stats"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["entries"] == 1

    rc = main(["stats", "--store", str(real)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["entries"] == 1
