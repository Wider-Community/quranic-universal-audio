"""``repo_email_digest`` round-trip coverage.

Buffered rows group by (email, event_kind); ``due_groups`` returns a group only
once its EARLIEST row is at/under the cutoff (the tumbling-window edge);
``delete_ids`` removes exactly the flushed rows, leaving anything buffered after
the read intact. Writes go through a durable transaction — never hand-INSERTed.
"""

from __future__ import annotations

from datetime import timedelta

from services.db import _serde
from services.db import repo_email_digest as repo_digest
from services.db import sync as _sync


def _add(email, event_kind, reciter_id, reciter_name, *, at=None):
    with _sync.durable_transaction():
        repo_digest.add(
            email=email,
            manage_token=f"tok-{email}",
            event_kind=event_kind,
            reciter_id=reciter_id,
            reciter_name=reciter_name,
            at=at,
        )


def test_due_groups_uses_earliest_row_as_window_edge():
    now = _serde.now()
    # Earliest row is 90 min old; a later row joined the same window.
    _add("a@x.com", "recitation_published", "r1", "One", at=now - timedelta(minutes=90))
    _add("a@x.com", "recitation_published", "r2", "Two", at=now - timedelta(minutes=5))
    cutoff = now - timedelta(minutes=60)
    groups = repo_digest.due_groups(cutoff=cutoff)
    assert groups == [{"email": "a@x.com", "event_kind": "recitation_published"}]


def test_due_groups_excludes_a_fresh_window():
    now = _serde.now()
    _add("a@x.com", "timestamps_regenerated", "r1", "One", at=now - timedelta(minutes=5))
    assert repo_digest.due_groups(cutoff=now - timedelta(minutes=60)) == []


def test_items_for_returns_group_oldest_first():
    now = _serde.now()
    _add("a@x.com", "recitation_published", "r2", "Two", at=now - timedelta(minutes=10))
    _add("a@x.com", "recitation_published", "r1", "One", at=now - timedelta(minutes=20))
    items = repo_digest.items_for("a@x.com", "recitation_published")
    assert [i["reciter_name"] for i in items] == ["One", "Two"]


def test_delete_ids_scoped_keeps_rows_buffered_after_read():
    now = _serde.now()
    _add("a@x.com", "recitation_published", "r1", "One", at=now - timedelta(minutes=90))
    read = repo_digest.items_for("a@x.com", "recitation_published")
    # A new event arrives after the flush read.
    _add("a@x.com", "recitation_published", "r2", "Two", at=now)
    with _sync.durable_transaction():
        repo_digest.delete_ids([i["id"] for i in read])
    remaining = repo_digest.items_for("a@x.com", "recitation_published")
    assert [i["reciter_name"] for i in remaining] == ["Two"]
