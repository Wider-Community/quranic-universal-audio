"""``repo_announcements`` coverage.

Announcements are a single global row each (no per-user fan-out). The contract:
``create`` returns a rowid and the row shows in ``list_active``; ``revoke``
stamps ``revoked_at`` so it drops from ``list_active`` but stays in ``list_all``;
revoking an unknown/already-revoked id is a no-op (False).

Rows are written inside a durable transaction (the boundary the service uses) —
never hand-INSERTed.
"""

from __future__ import annotations

from services.db import repo_announcements
from services.db import sync as _sync


def _seed(title="Heads up", body=None, author="owner-1", login="owner") -> int:
    with _sync.durable_transaction():
        return repo_announcements.create(
            title=title, body=body, author_hf_user_id=author, author_login=login
        )


def _revoke(announcement_id: int) -> bool:
    with _sync.durable_transaction():
        return repo_announcements.revoke(announcement_id)


def test_create_shows_in_active_with_fields():
    new_id = _seed(title="Maintenance tonight", body="Back at 9pm", login="alice")
    active = repo_announcements.list_active()
    assert len(active) == 1
    row = active[0]
    assert row["id"] == new_id
    assert row["title"] == "Maintenance tonight"
    assert row["body"] == "Back at 9pm"
    assert row["author_login"] == "alice"
    assert row["revoked_at"] is None


def test_active_is_newest_first():
    first = _seed(title="first")
    second = _seed(title="second")
    ids = [r["id"] for r in repo_announcements.list_active()]
    assert ids == [second, first]


def test_revoke_drops_from_active_but_stays_in_all():
    keep = _seed(title="keep")
    gone = _seed(title="gone")

    assert _revoke(gone) is True

    active_ids = [r["id"] for r in repo_announcements.list_active()]
    all_ids = [r["id"] for r in repo_announcements.list_all()]
    assert active_ids == [keep]
    assert set(all_ids) == {keep, gone}
    revoked = next(r for r in repo_announcements.list_all() if r["id"] == gone)
    assert revoked["revoked_at"] is not None


def test_revoke_twice_is_noop():
    aid = _seed()
    assert _revoke(aid) is True
    assert _revoke(aid) is False


def test_revoke_unknown_id_is_false():
    assert _revoke(424242) is False
