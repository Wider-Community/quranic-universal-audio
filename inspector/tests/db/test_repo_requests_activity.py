"""repo_requests (payload adapters, pending→archive) + repo_activity sidecars."""

from __future__ import annotations

import sqlite3

import pytest

from qua_shared.schemas import Actor, ProposedEdits, Role

from services import db
from services.db import repo_requests, repo_activity
from ._helpers import seed_user, seed_delivery


def _actor(hf="u1", login="alice", role=Role.CONTRIBUTOR) -> Actor:
    return Actor(hf_user_id=hf, login_at_time=login, role=role)


def test_submit_get_pending_roundtrip(fresh_db):
    seed_delivery("d1")
    with db.transaction():
        repo_requests.submit(
            slug="d1",
            requester=_actor(),
            proposed_edits=ProposedEdits(riwayah="warsh", recording_year=1990),
            comments="please align",
            auto_claim=True,
        )
    pr = repo_requests.get_pending("d1")
    assert pr is not None
    assert pr.requester.hf_user_id == "u1"
    assert pr.requester.login_at_time == "alice"   # snapshot preserved
    assert pr.proposed_edits.riwayah == "warsh"
    assert pr.proposed_edits.recording_year == 1990
    assert pr.proposed_edits.has_any() is True
    assert pr.comments == "please align"
    assert pr.auto_claim is True
    assert repo_requests.has_pending("d1") is True


def test_one_pending_per_slug(fresh_db):
    seed_delivery("d1")
    with db.transaction():
        repo_requests.submit(slug="d1", requester=_actor())
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction():
            repo_requests.submit(slug="d1", requester=_actor("u2", "bob"))


def test_slugless_new_reciter_requests_allowed(fresh_db):
    with db.transaction():
        repo_requests.submit(slug=None, requester=_actor(), kind="new_reciter",
                             extra_payload={"new_reciter": {"name_en": "X"}})
        repo_requests.submit(slug=None, requester=_actor("u2", "bob"), kind="new_reciter")
    # both slugless requests exist...
    assert repo_requests.count_pending() == 2
    # ...but the legacy slug-keyed view excludes them (they aren't PendingRequests)
    assert repo_requests.all_pending() == []
    assert repo_requests.count_pending(include_slugless=False) == 0


def test_resolve_to_archive_and_get_for_slug(fresh_db):
    seed_delivery("d1")
    with db.transaction():
        repo_requests.submit(
            slug="d1", requester=_actor(),
            proposed_edits=ProposedEdits(style="murattal"),
        )
    # accept (→ 'completed' archive)
    with db.transaction():
        ok = repo_requests.resolve(
            slug="d1", status="accepted",
            transitioned_by=_actor("admin", "adm", Role.OWNER),
        )
    assert ok is True
    assert repo_requests.has_pending("d1") is False
    archived = repo_requests.get_for_slug("completed", "d1")
    assert len(archived) == 1
    assert archived[0].proposed_edits.style == "murattal"
    assert archived[0].transitioned_by.hf_user_id == "admin"

    # a slug can cycle: re-request → return; both archives keep order
    with db.transaction():
        repo_requests.submit(slug="d1", requester=_actor())
    with db.transaction():
        repo_requests.resolve(
            slug="d1", status="returned",
            transitioned_by=_actor("admin", "adm", Role.OWNER),
            reason="needs better source",
        )
    returned = repo_requests.get_for_slug("returned", "d1")
    assert len(returned) == 1
    assert returned[0].reason == "needs better source"


def test_activity_tombstone(fresh_db):
    """Per-user dismissals were dropped with the admin notifications rail
    (migration 0006). Only the global tombstone path remains."""
    seed_user("u1", "alice")
    ch = "abc123def4567890"

    with db.transaction():
        repo_activity.delete(ch, deleted_by="u1", reason="spam")
    assert repo_activity.is_deleted(ch) is True
    assert repo_activity.deleted_set() == {ch}
    # idempotent re-delete (upsert)
    with db.transaction():
        repo_activity.delete(ch, deleted_by="u1", reason="still spam")
    assert repo_activity.deleted_set() == {ch}
    with db.transaction():
        repo_activity.undelete(ch)
    assert repo_activity.is_deleted(ch) is False
