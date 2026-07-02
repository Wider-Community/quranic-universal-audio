"""repo_ts_reports: create/multiplicity/counts/resolve/staleness/delete."""

from __future__ import annotations

from typing import Any

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
    defaults: dict[str, Any] = dict(
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
    _create(
        category="tajweed", subtype="wrong_rule", target=_target("cell", word_index=0, cell_index=1)
    )
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


def test_silence_gap_is_one_stance_per_gap_subtype_free(fresh_db):
    """A gap's target_key is subtype-free, so re-filing the same gap with a different
    silence subtype upserts (one pause stance per gap per identity, last wins)."""
    g = _target("gap", word_index=0)
    _create(category="silence", subtype="pause_missed", target=g, comment=None)
    row, created = _create(category="silence", subtype="pause_wasl", target=g, comment=None)
    assert created is False
    assert row["subtype"] == "pause_wasl"
    assert len(repo.list_for_verse("reciter-a", "2:45")) == 1


def test_silence_report_is_public_to_other_viewers(fresh_db):
    """Silence flags are public — a different viewer without the nonpublic cap sees them
    (unlike tajweed/phonemes)."""
    _create(
        category="silence",
        subtype="pause_missed",
        target=_target("gap", word_index=0),
        comment=None,
    )
    rows = repo.list_for_verse("reciter-a", "2:45", anon_token="anon-2", can_view_nonpublic=False)
    assert len(rows) == 1 and rows[0]["category"] == "silence"


def test_resolve_auto_closes_with_reason_and_no_human_resolver(fresh_db):
    row, _ = _create(
        category="silence",
        subtype="pause_missed",
        target=_target("gap", word_index=0),
        comment=None,
        hf_user_id="u-reporter",
        anon_token=None,
        login_at_time="reporter",
    )
    with db.transaction():
        resolved = repo.resolve_auto(report_id=row["id"], reason="A pause now appears here.")
    assert resolved is not None
    assert resolved["status"] == "resolved"
    assert resolved["resolver_comment"] == "A pause now appears here."
    assert resolved["resolved_by_hf_user_id"] is None
    assert resolved["hf_user_id"] == "u-reporter"  # reporter preserved → notifiable


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
    got = repo.get(row["id"])
    assert got is not None and got["stale"] is True
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


def test_soft_deleted_report_drops_from_counts(fresh_db):
    row, _ = _create(anon_token="anon-x")
    with db.transaction():
        repo.delete(report_id=row["id"], hf_user_id=None, anon_token="anon-x")
    assert repo.verse_counts("reciter-a") == []
    assert repo.list_for_verse("reciter-a", "2:45") == []
    # Retained internally: the row still exists, just hidden.
    raw = db.get_conn().execute("SELECT hidden_at FROM ts_reports WHERE id = ?", (row["id"],))
    assert raw.fetchone()["hidden_at"] is not None


def test_refiling_a_hidden_target_unhides_and_counts_as_new(fresh_db):
    row, _ = _create(anon_token="anon-x", comment="first")
    with db.transaction():
        repo.delete(report_id=row["id"], hf_user_id=None, anon_token="anon-x")
    again, created = _create(anon_token="anon-x", comment="second")
    assert created is True  # re-surfacing a hidden report notifies as new
    assert again["id"] == row["id"]  # same slot un-hidden, not a duplicate
    assert again["comment"] == "second"
    assert repo.verse_counts("reciter-a") == [
        {"verse_key": "2:45", "open_count": 1, "resolved_count": 0}
    ]


def test_redelete_already_hidden_is_noop(fresh_db):
    row, _ = _create(anon_token="anon-x")
    with db.transaction():
        first = repo.delete(report_id=row["id"], hf_user_id=None, anon_token="anon-x")
        second = repo.delete(report_id=row["id"], hf_user_id=None, anon_token="anon-x")
    assert first is True
    assert second is False


def test_tajweed_same_cell_different_subtypes_are_separate_rows(fresh_db):
    cell = _target("cell", word_index=0, cell_index=1)
    _create(category="tajweed", subtype="wrong_rule", target=cell, comment="wrong")
    _create(category="tajweed", subtype="missing_rule", target=cell, comment="missing")
    rows = repo.list_for_verse("reciter-a", "2:45")
    assert len(rows) == 2
    assert {r["subtype"] for r in rows} == {"wrong_rule", "missing_rule"}


def test_tajweed_same_cell_same_subtype_upserts_in_place(fresh_db):
    cell = _target("cell", word_index=0, cell_index=1)
    _create(category="tajweed", subtype="wrong_rule", target=cell, comment="first")
    row, created = _create(category="tajweed", subtype="wrong_rule", target=cell, comment="second")
    assert created is False
    assert row["comment"] == "second"
    assert len(repo.list_for_verse("reciter-a", "2:45")) == 1


def test_selected_rule_tags_roundtrip(fresh_db):
    row, _ = _create(
        category="tajweed",
        subtype="wrong_rule",
        target=_target("cell", word_index=0, cell_index=1),
        comment="wrong rule here",
        selected_rule_tags=["noon_ghunnah", "ikhfaa_noon"],
    )
    assert row["selected_rule_tags"] == ["noon_ghunnah", "ikhfaa_noon"]
    fetched = repo.list_for_verse("reciter-a", "2:45")[0]
    assert fetched["selected_rule_tags"] == ["noon_ghunnah", "ikhfaa_noon"]


def _timing_item(cell_index: int, *, word_index: int = 0, onset: str = "early") -> dict:
    return {
        "category": "timing",
        "onset": onset,
        "target": _target("cell", word_index=word_index, cell_index=cell_index),
        "snapshot": None,
        "comment": None,
        "selected_rule_tags": None,
    }


def _batch(items, *, anon_token="anon-1", verse_key="2:45"):
    with db.transaction():
        return repo.create_many(
            slug="reciter-a",
            verse_key=verse_key,
            items=items,
            hf_user_id=None,
            anon_token=anon_token,
            login_at_time=None,
            role_at_time=None,
        )


def test_create_many_groups_timing_cells_under_one_word(fresh_db):
    results = _batch([_timing_item(0), _timing_item(1), _timing_item(2)])
    assert [created for _, created in results] == [True, True, True]
    rows = repo.list_for_verse("reciter-a", "2:45")
    assert len(rows) == 3
    assert {r["target"]["word_index"] for r in rows} == {0}


def test_timing_axes_round_trip(fresh_db):
    _batch([_timing_item(0, onset="late")])
    row = repo.list_for_verse("reciter-a", "2:45")[0]
    assert row["onset"] == "late"
    assert row["offset"] is None
    assert row["subtype"] is None


def test_create_many_mixed_categories_are_separate_rows(fresh_db):
    results = _batch(
        [
            _timing_item(0),
            {
                "category": "tajweed",
                "subtype": "wrong_rule",
                "target": _target("cell", word_index=0, cell_index=0),
                "snapshot": None,
                "comment": "x",
                "selected_rule_tags": ["qalqala"],
            },
        ]
    )
    assert len(results) == 2
    rows = repo.list_for_verse("reciter-a", "2:45")
    assert {r["category"] for r in rows} == {"timing", "tajweed"}


def test_create_many_resubmit_marks_not_created(fresh_db):
    _batch([_timing_item(0), _timing_item(1)])
    again = _batch([_timing_item(0), _timing_item(1)])
    assert [created for _, created in again] == [False, False]
    assert len(repo.list_for_verse("reciter-a", "2:45")) == 2


def test_resolve_group_resolves_all_open_timing_rows(fresh_db):
    _batch([_timing_item(0), _timing_item(1), _timing_item(2)])
    with db.transaction():
        rows = repo.resolve_group(
            slug="reciter-a",
            verse_key="2:45",
            word_index=0,
            category="timing",
            resolver_hf_user_id="owner-1",
            resolver_login="owner",
            resolver_comment="fixed",
        )
    assert len(rows) == 3
    assert all(r["status"] == "resolved" for r in rows)
    assert repo.verse_counts("reciter-a") == [
        {"verse_key": "2:45", "open_count": 0, "resolved_count": 3}
    ]


def test_resolve_group_empty_when_none_open(fresh_db):
    _batch([_timing_item(0)])
    with db.transaction():
        repo.resolve_group(
            slug="reciter-a",
            verse_key="2:45",
            word_index=0,
            category="timing",
            resolver_hf_user_id="owner-1",
            resolver_login="owner",
            resolver_comment=None,
        )
    with db.transaction():
        again = repo.resolve_group(
            slug="reciter-a",
            verse_key="2:45",
            word_index=0,
            category="timing",
            resolver_hf_user_id="owner-1",
            resolver_login="owner",
            resolver_comment=None,
        )
    assert again == []


def test_resolve_group_spans_two_identities(fresh_db):
    _batch([_timing_item(0)], anon_token="anon-1")
    _batch([_timing_item(1)], anon_token="anon-2")
    with db.transaction():
        rows = repo.resolve_group(
            slug="reciter-a",
            verse_key="2:45",
            word_index=0,
            category="timing",
            resolver_hf_user_id="owner-1",
            resolver_login="owner",
            resolver_comment=None,
        )
    assert {r["anon_token"] for r in rows} == {"anon-1", "anon-2"}


def _phoneme_item(pfi: int, *, word_index: int = 0) -> dict:
    return {
        "category": "phonemes",
        "target": _target("phoneme", word_index=word_index, phoneme_flat_index=pfi),
        "snapshot": None,
        "comment": None,
        "selected_rule_tags": None,
    }


def test_phonemes_group_resolves_as_word_unit(fresh_db):
    _batch([_phoneme_item(0), _phoneme_item(1), _phoneme_item(0, word_index=1)])
    with db.transaction():
        rows = repo.resolve_group(
            slug="reciter-a",
            verse_key="2:45",
            word_index=0,
            category="phonemes",
            resolver_hf_user_id="owner-1",
            resolver_login="owner",
            resolver_comment=None,
        )
    assert len(rows) == 2  # both word-0 phonemes resolve as a unit
    assert all(r["status"] == "resolved" for r in rows)
    assert repo.verse_counts("reciter-a") == [
        {"verse_key": "2:45", "open_count": 1, "resolved_count": 2}
    ]


def test_bridge_phoneme_is_a_distinct_target(fresh_db):
    # A normal phoneme and a bridge (phoneme_flat_index=-1) in the same word are
    # separate rows; bridges before different words are separate too.
    _batch([_phoneme_item(0), _phoneme_item(-1), _phoneme_item(-1, word_index=2)])
    rows = repo.list_for_verse("reciter-a", "2:45")
    assert len(rows) == 3
    assert len({repo.target_key(r["target"]) for r in rows}) == 3


def _seed_public_and_nonpublic(token: str = "anon-1") -> None:
    """A timing (public) + tajweed + phonemes (both non-public) report, one identity."""
    _batch(
        [
            _timing_item(0),
            {
                "category": "tajweed",
                "subtype": "wrong_rule",
                "target": _target("cell", word_index=0, cell_index=5),
                "snapshot": None,
                "comment": "x",
                "selected_rule_tags": None,
            },
            _phoneme_item(3),
        ],
        anon_token=token,
    )


def test_list_for_verse_hides_nonpublic_from_other_viewer(fresh_db):
    _seed_public_and_nonpublic("anon-1")
    # A different anonymous viewer without the capability sees only the public timing report.
    other = repo.list_for_verse("reciter-a", "2:45", anon_token="anon-2", can_view_nonpublic=False)
    assert {r["category"] for r in other} == {"timing"}
    # The reporter (same token) sees their own tajweed + phonemes too.
    mine = repo.list_for_verse("reciter-a", "2:45", anon_token="anon-1", can_view_nonpublic=False)
    assert {r["category"] for r in mine} == {"timing", "tajweed", "phonemes"}
    # A capability holder sees everything regardless of identity.
    cap = repo.list_for_verse("reciter-a", "2:45", anon_token="anon-2", can_view_nonpublic=True)
    assert {r["category"] for r in cap} == {"timing", "tajweed", "phonemes"}


def test_verse_counts_hides_nonpublic_from_other_viewer(fresh_db):
    _seed_public_and_nonpublic("anon-1")
    other = repo.verse_counts("reciter-a", anon_token="anon-2", can_view_nonpublic=False)
    assert other == [{"verse_key": "2:45", "open_count": 1, "resolved_count": 0}]
    reporter = repo.verse_counts("reciter-a", anon_token="anon-1", can_view_nonpublic=False)
    assert reporter == [{"verse_key": "2:45", "open_count": 3, "resolved_count": 0}]


def test_resolve_group_ignores_other_word_and_tajweed(fresh_db):
    _batch(
        [
            _timing_item(0, word_index=0),
            _timing_item(0, word_index=1),
            {
                "category": "tajweed",
                "subtype": "wrong_rule",
                "target": _target("cell", word_index=0, cell_index=9),
                "snapshot": None,
                "comment": "x",
                "selected_rule_tags": None,
            },
        ]
    )
    with db.transaction():
        rows = repo.resolve_group(
            slug="reciter-a",
            verse_key="2:45",
            word_index=0,
            category="timing",
            resolver_hf_user_id="owner-1",
            resolver_login="owner",
            resolver_comment=None,
        )
    assert len(rows) == 1  # only word-0 timing
    assert repo.verse_counts("reciter-a") == [
        {"verse_key": "2:45", "open_count": 2, "resolved_count": 1}
    ]
