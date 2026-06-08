"""``repo_notifications`` retention + ordering coverage.

The emitter/route tests cover create/list/dismiss/restore behaviourally; this
pins the archive-retention prune (active rows are never pruned; dismissed rows
beyond the cap are) and newest-first ordering.
"""

from __future__ import annotations

from services.db import repo_notifications
from services.db import sync as _sync


def _create(uid, key, **kw):
    with _sync.durable_transaction():
        return repo_notifications.create(
            hf_user_id=uid,
            event="reciter.request_rejected_soft",
            slug="x",
            title="t",
            body=None,
            payload=None,
            source_key=key,
            **kw,
        )


def test_prune_keeps_active_rows_regardless_of_count():
    for i in range(5):
        _create("u-1", f"k{i}")
    with _sync.durable_transaction():
        repo_notifications.prune_for_user("u-1", keep=2)
    # Nothing dismissed → nothing pruned, even though 5 > keep=2.
    assert len(repo_notifications.list_active("u-1")) == 5


def test_prune_drops_oldest_dismissed_beyond_keep():
    for i in range(5):
        nid = _create("u-2", f"k{i}")
        with _sync.durable_transaction():
            repo_notifications.dismiss(nid, "u-2")
    with _sync.durable_transaction():
        deleted = repo_notifications.prune_for_user("u-2", keep=2)
    assert deleted == 3
    assert len(repo_notifications.list_archived("u-2")) == 2


def test_create_returns_none_on_duplicate_source_key():
    first = _create("u-3", "dup")
    second = _create("u-3", "dup")
    assert first is not None
    assert second is None
    assert len(repo_notifications.list_active("u-3")) == 1
