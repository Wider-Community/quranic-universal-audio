"""Native-target report repository behavior."""

from __future__ import annotations

from typing import Any

from services import db
from services.db import repo_ts_reports as repo


def _target(kind: str = "verse", target_id: str = "2:45", reading_id: str = "r1") -> dict:
    return {"reading_id": reading_id, "kind": kind, "target_id": target_id}


def _snapshot(*, word_id: int | None = None, token: str = "a") -> dict:
    native: dict[str, object] = {"token": token}
    if word_id is not None:
        native["word_id"] = word_id
        native["word_ref"] = f"2:45:{word_id}"
    return {
        "native_schema_version": 2,
        "shard_schema_version": 12,
        "native": native,
        "timing": {"start_ms": 10, "end_ms": 20},
    }


def _create(**over):
    values: dict[str, Any] = {
        "slug": "reciter-a",
        "verse_key": "2:45",
        "category": "other",
        "subtype": None,
        "target": _target(),
        "snapshot": _snapshot(),
        "comment": "detail",
        "hf_user_id": None,
        "anon_token": "anon-1",
        "login_at_time": None,
        "role_at_time": None,
    }
    values.update(over)
    with db.transaction():
        return repo.create(**values)


def test_create_counts_and_native_roundtrip(fresh_db):
    row, created = _create()
    assert created
    assert row["target"] == _target()
    assert row["snapshot"] == _snapshot()
    assert repo.verse_counts("reciter-a") == [
        {"verse_key": "2:45", "open_count": 1, "resolved_count": 0}
    ]


def test_native_identity_controls_upsert_and_multiplicity(fresh_db):
    _create(comment="first")
    row, created = _create(comment="second")
    assert not created and row["comment"] == "second"
    _create(target=_target("word", "1"))
    _create(target=_target("word", "1", "r2"))
    assert len(repo.list_for_verse("reciter-a", "2:45")) == 3
    assert repo.target_key(_target("word", "1")) != repo.target_key(_target("word", "2"))


def test_tajweed_subtypes_are_distinct_for_the_same_native_target(fresh_db):
    target = _target("column", "10")
    _create(category="tajweed", subtype="wrong_rule", target=target)
    _create(category="tajweed", subtype="missing_rule", target=target)
    rows = repo.list_for_verse("reciter-a", "2:45")
    assert {row["subtype"] for row in rows} == {"wrong_rule", "missing_rule"}


def test_batch_and_group_resolution_are_scoped_by_reading_and_word(fresh_db):
    items = [
        {
            "category": "timing",
            "target": _target("column", str(column), "r1"),
            "snapshot": _snapshot(word_id=1),
            "onset": "early",
        }
        for column in (10, 11)
    ]
    items.append(
        {
            "category": "timing",
            "target": _target("column", "10", "r2"),
            "snapshot": _snapshot(word_id=1),
            "onset": "early",
        }
    )
    with db.transaction():
        results = repo.create_many(
            slug="reciter-a",
            verse_key="2:45",
            items=items,
            hf_user_id=None,
            anon_token="anon-1",
            login_at_time=None,
            role_at_time=None,
        )
    assert all(created for _, created in results)
    with db.transaction():
        resolved = repo.resolve_group(
            slug="reciter-a",
            verse_key="2:45",
            reading_id="r1",
            word_id="1",
            category="timing",
            resolver_hf_user_id="owner",
            resolver_login="owner",
            resolver_comment="fixed",
        )
    assert len(resolved) == 2
    remaining = [row for row in repo.list_for_verse("reciter-a", "2:45") if row["status"] == "open"]
    assert len(remaining) == 1 and remaining[0]["target"]["reading_id"] == "r2"


def test_nonpublic_visibility_and_public_boundary_reports(fresh_db):
    _create(category="tajweed", subtype="wrong_rule", target=_target("column", "10"))
    _create(
        category="silence",
        subtype="pause_missed",
        target=_target("boundary", "5"),
        comment=None,
    )
    other = repo.list_for_verse("reciter-a", "2:45", anon_token="anon-2", can_view_nonpublic=False)
    assert [row["category"] for row in other] == ["silence"]
    mine = repo.list_for_verse("reciter-a", "2:45", anon_token="anon-1", can_view_nonpublic=False)
    assert {row["category"] for row in mine} == {"tajweed", "silence"}


def test_resolve_stale_and_soft_delete_lifecycle(fresh_db):
    row, _ = _create(hf_user_id="reporter", anon_token=None)
    with db.transaction():
        assert repo.mark_stale([row["id"]]) == 1
        resolved = repo.resolve(
            report_id=row["id"],
            resolver_hf_user_id="owner",
            resolver_login="owner",
            resolver_comment="fixed",
        )
    assert resolved and resolved["stale"] and resolved["status"] == "resolved"
    with db.transaction():
        assert repo.delete(report_id=row["id"], hf_user_id="reporter", anon_token=None)
    assert repo.get(row["id"]) is None


def test_word_group_notification_key_includes_reading():
    a = repo.word_group_key("r", "2:45", "r1", "1", "timing")
    b = repo.word_group_key("r", "2:45", "r2", "1", "timing")
    assert a != b
