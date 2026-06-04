"""repo_activity tombstone path — global deletion + idempotent re-delete + undelete."""

from __future__ import annotations

from services import db
from services.db import repo_activity
from ._helpers import seed_user


def test_activity_tombstone(fresh_db):
    """Only the global tombstone path remains: delete sets the tombstone,
    re-delete is idempotent, undelete clears it."""
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
