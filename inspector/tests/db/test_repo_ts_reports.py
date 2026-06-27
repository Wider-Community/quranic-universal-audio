"""repo_ts_reports: create/multiplicity/counts/resolve/staleness/delete."""

from __future__ import annotations

from services import db
from services.db import repo_ts_reports as repo


def _target(kind: str = "verse", **kw) -> dict:
    base = {
        "kind": kind,
        "word_index": None,
        "source_letter_index": None,
        "cell_index": None,
        "phoneme_flat_index": None,
        "share_group": None,
    }
    base.update(kw)
    return base


def _create(**kw):
    defaults = dict(
        slug="reciter-a",
        verse_key="2:45",
        category="other",
        subtype=None,
        target=_target(),
        snapshot=None,
        comment="hi",
        hf_user_id=None,
        anon_token="anon-1",
        login_at_time=None,
        role_at_time=None,
    )
    defaults.update(kw)
    with db.transaction():
        return repo.create(**defaults)


def test_create_anon_then_verse_counts(fresh_db):
    row, created = _create()
    assert created is True
    assert row["chapter"] == 2
    assert row["status"] == "open"
    counts = repo.verse_counts("reciter-a")
    assert counts == [{"verse_key": "2:45", "open_count": 1, "resolved_count": 0}]


def test_distinct_category_or_target_are_separate_rows(fresh_db):
    _create(category="other", target=_target("verse"))
    _create(category="audio", target=_target("verse"), comment="audio bad")
    _create(category="tajweed", subtype="wrong_rule", target=_target("cell", word_index=0, cell_index=1))
    rows = repo.list_for_verse("reciter-a", "2:45")
    assert len(rows) == 3
    assert {r["category"] for r in rows} == {"other", "audio", "tajweed"}


def test_same_category_and_target_upserts_in_place(fresh_db):
    _create(category="other", target=_target("verse"), comment="first")
    row, created = _create(category="other", target=_target("verse"), comment="second")
    assert created is False
    assert row["comment"] == "second"
    assert len(repo.list_for_verse("reciter-a", "2:45")) == 1


def test_target_key_distinguishes_word_indices(fresh_db):
    assert repo.target_key(_target("word", word_index=0)) != repo.target_key(
        _target("word", word_index=1)
    )


def test_resolve_marks_resolved_and_returns_reporter(fresh_db):
    row, _ = _create(hf_user_id="u-reporter", anon_token=None, login_at_time="reporter")
    with db.transaction():
        resolved = repo.resolve(
            report_id=row["id"],
            resolver_hf_user_id="u-owner",
            resolver_login="owner",
            resolver_comment="fixed it",
        )
    assert resolved is not None
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None
    assert resolved["resolver_comment"] == "fixed it"
    assert resolved["hf_user_id"] == "u-reporter"
    counts = repo.verse_counts("reciter-a")
    assert counts == [{"verse_key": "2:45", "open_count": 0, "resolved_count": 1}]


def test_resolve_already_resolved_returns_none(fresh_db):
    row, _ = _create()
    with db.transaction():
        repo.resolve(
            report_id=row["id"],
            resolver_hf_user_id="u-owner",
            resolver_login="owner",
            resolver_comment=None,
        )
    with db.transaction():
        again = repo.resolve(
            report_id=row["id"],
            resolver_hf_user_id="u-owner",
            resolver_login="owner",
            resolver_comment=None,
        )
    assert again is None


def test_mark_stale_excludes_from_recheck(fresh_db):
    row, _ = _create()
    assert [r["id"] for r in repo.list_open_for_recheck("reciter-a", chapters=[2])] == [row["id"]]
    with db.transaction():
        changed = repo.mark_stale([row["id"]])
    assert changed == 1
    assert repo.get(row["id"])["stale"] is True
    assert repo.list_open_for_recheck("reciter-a", chapters=[2]) == []


def test_recheck_scope_other_chapter_misses(fresh_db):
    _create(verse_key="2:45")
    assert repo.list_open_for_recheck("reciter-a", chapters=[3]) == []


def test_delete_own_report(fresh_db):
    row, _ = _create(anon_token="anon-x")
    with db.transaction():
        removed = repo.delete(report_id=row["id"], hf_user_id=None, anon_token="anon-x")
    assert removed is True
    assert repo.list_for_verse("reciter-a", "2:45") == []


def test_delete_other_identity_is_noop(fresh_db):
    row, _ = _create(anon_token="anon-x")
    with db.transaction():
        removed = repo.delete(report_id=row["id"], hf_user_id=None, anon_token="anon-other")
    assert removed is False
    assert len(repo.list_for_verse("reciter-a", "2:45")) == 1
