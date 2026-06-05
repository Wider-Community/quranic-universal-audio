"""Tier-1 identity recency: login row + debounced page-entry touch.

Covers:
- ``repo_access.touch_last_login`` stamps ``last_login_at``.
- ``visitors.maybe_touch_entry`` writes once then debounces inside the window.
- ``GET /api/me`` stamps ``last_entry_at`` for a signed-in user and doesn't
  rewrite it on an immediate second call (debounce).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from config import ENTRY_DEBOUNCE_SECONDS
from services import db
from services.admin import visitors
from services.db import _serde, repo_access


def _last(hf_user_id: str, col: str):
    row = (
        db.get_conn()
        .execute(f"SELECT {col} FROM users WHERE hf_user_id = ?", (hf_user_id,))
        .fetchone()
    )
    return row[0] if row else None


def test_touch_last_login_sets_column():
    with db.transaction():
        repo_access.ensure_user("u1", login="alice")
        repo_access.touch_last_login("u1")
    assert _last("u1", "last_login_at") is not None


def test_maybe_touch_entry_writes_then_debounces():
    with db.transaction():
        repo_access.ensure_user("u2", login="bob")

    t0 = _serde.now()
    assert visitors.maybe_touch_entry("u2", now=t0) is True
    first = _last("u2", "last_entry_at")
    assert first is not None

    # within the debounce window → no write
    within = t0 + timedelta(seconds=ENTRY_DEBOUNCE_SECONDS - 1)
    assert visitors.maybe_touch_entry("u2", now=within) is False
    assert _last("u2", "last_entry_at") == first

    # past the window → writes again (newer timestamp)
    after = t0 + timedelta(seconds=ENTRY_DEBOUNCE_SECONDS + 1)
    assert visitors.maybe_touch_entry("u2", now=after) is True
    assert _last("u2", "last_entry_at") != first


def test_maybe_touch_entry_missing_row_does_not_raise():
    # No users row for this id → UPDATE affects 0 rows, no exception.
    assert visitors.maybe_touch_entry("ghost") is True
    assert _last("ghost", "last_entry_at") is None


@pytest.mark.usefixtures("flask_client")
def test_api_me_stamps_last_entry(signed_in_client):
    client, user = signed_in_client(hf_user_id="entry-user", login="entry", role="contributor")
    hf = user["hf_user_id"]
    assert _last(hf, "last_entry_at") is None

    r1 = client.get("/api/me")
    assert r1.status_code == 200
    stamped = _last(hf, "last_entry_at")
    assert stamped is not None

    # Immediate second call is inside the debounce window → unchanged.
    r2 = client.get("/api/me")
    assert r2.status_code == 200
    assert _last(hf, "last_entry_at") == stamped
