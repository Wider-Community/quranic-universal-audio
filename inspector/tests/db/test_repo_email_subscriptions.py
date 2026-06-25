"""``repo_email_subscriptions`` round-trip coverage.

Subscriptions are keyed by normalized email; the manage token + created_at are
stable across updates; unsubscribe turns every event opt-in off while keeping
the row + token (so the same link can re-manage). Writes go through a durable
transaction (the boundary the route uses) — never hand-INSERTed.
"""

from __future__ import annotations

from services.db import repo_email_subscriptions as repo_subs
from services.db import sync as _sync


def _prefs(**over):
    base = {
        "email": "Person@Example.com",
        "request_aligned": True,
        "recitation_published": "all",
        "timestamps_regenerated": "selected",
        "github_release": True,
        "riwayah_new_recitation": True,
        "riwayah_first_available": False,
        "reciters": ["abc"],
        "riwayahs": ["hafs"],
    }
    base.update(over)
    return base


def _upsert(email, *, hf_user_id=None, token="tok-1", **over):
    with _sync.durable_transaction():
        return repo_subs.upsert(
            email=email, hf_user_id=hf_user_id, prefs=_prefs(email=email, **over), new_token=token
        )


def test_upsert_creates_row_normalizes_email_and_injects_key():
    row = _upsert("Person@Example.com", token="tok-create")
    assert row["email"] == "person@example.com"  # normalized
    assert row["manage_token"] == "tok-create"
    # The stored prefs echo the email key, not whatever case was submitted.
    assert row["prefs"]["email"] == "person@example.com"
    assert row["prefs"]["recitation_published"] == "all"


def test_get_by_email_token_and_hf_user():
    _upsert("a@b.com", hf_user_id="u-1", token="tok-get")
    by_email = repo_subs.get_by_email("A@B.com")
    by_token = repo_subs.get_by_token("tok-get")
    by_hf_user = repo_subs.get_by_hf_user("u-1")
    assert by_email is not None
    assert by_token is not None
    assert by_hf_user is not None
    assert by_email["manage_token"] == "tok-get"
    assert by_token["email"] == "a@b.com"
    assert by_hf_user["email"] == "a@b.com"


def test_update_preserves_token_and_created_at():
    first = _upsert("c@d.com", token="tok-keep", recitation_published="all")
    # A second save with a DIFFERENT proposed token must keep the original.
    second = _upsert("c@d.com", token="tok-ignored", recitation_published="off")
    assert second["manage_token"] == "tok-keep"
    assert second["created_at"] == first["created_at"]
    assert second["prefs"]["recitation_published"] == "off"


def test_unsubscribe_turns_every_event_off_and_keeps_token():
    _upsert("e@f.com", token="tok-unsub")
    with _sync.durable_transaction():
        updated = repo_subs.unsubscribe_by_token("tok-unsub")
    assert updated is not None
    p = updated["prefs"]
    assert p["recitation_published"] == "off"
    assert p["timestamps_regenerated"] == "off"
    assert p["request_aligned"] is False
    assert p["github_release"] is False
    assert p["riwayah_new_recitation"] is False
    assert p["riwayah_first_available"] is False
    # Row + token survive so the same link re-manages.
    assert updated["manage_token"] == "tok-unsub"


def test_unsubscribe_unknown_token_is_none():
    with _sync.durable_transaction():
        assert repo_subs.unsubscribe_by_token("no-such-token") is None
