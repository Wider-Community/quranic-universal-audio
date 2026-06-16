"""``/api/ts/<slug>/flags*`` route coverage.

The contract that matters: anyone (incl. anonymous, keyed by a client token)
can flag a verse with an optional comment; a verse holds one comment per
identity and accumulates many globally; re-flagging as the same identity
upserts in place; comment-author identity is disclosed only to callers holding
``timestamps.see_flagger_identity``; and a new comment notifies the owners.
"""

from __future__ import annotations

import json

from services.db import repo_notifications, repo_ts_flags

_ORIGIN = {"Origin": "http://localhost", "Content-Type": "application/json"}
_SLUG = "test-reciter"


def _post(client, slug, body):
    return client.post(f"/api/ts/{slug}/flags", data=json.dumps(body), headers=_ORIGIN)


def test_anonymous_flag_requires_token(flask_client):
    res = _post(flask_client, _SLUG, {"verse_key": "2:45", "comment": "off by a beat"})
    assert res.status_code == 400


def test_anonymous_flag_with_token_creates_row(flask_client):
    res = _post(
        flask_client,
        _SLUG,
        {"verse_key": "2:45", "comment": "starts late", "anon_token": "tok-abc"},
    )
    assert res.status_code == 201
    body = json.loads(res.data)
    assert body["comment"] == "starts late"
    assert body["mine"] is True
    rows = repo_ts_flags.list_for_verse(_SLUG, "2:45")
    assert len(rows) == 1
    assert rows[0]["anon_token"] == "tok-abc"


def test_invalid_verse_key_is_400(flask_client):
    res = _post(flask_client, _SLUG, {"verse_key": "nope", "anon_token": "t"})
    assert res.status_code == 400


def test_reciter_flags_lists_verse_with_count(flask_client):
    _post(flask_client, _SLUG, {"verse_key": "2:45", "anon_token": "a"})
    _post(flask_client, _SLUG, {"verse_key": "2:45", "anon_token": "b"})
    _post(flask_client, _SLUG, {"verse_key": "3:7", "anon_token": "a"})
    body = json.loads(flask_client.get(f"/api/ts/{_SLUG}/flags").data)
    counts = {f["verse_key"]: f["count"] for f in body["flags"]}
    assert counts == {"2:45": 2, "3:7": 1}


def test_resubmit_same_identity_upserts_not_duplicates(flask_client):
    first = _post(flask_client, _SLUG, {"verse_key": "2:45", "comment": "v1", "anon_token": "t"})
    assert first.status_code == 201
    second = _post(flask_client, _SLUG, {"verse_key": "2:45", "comment": "v2", "anon_token": "t"})
    assert second.status_code == 200  # update, not a new row
    rows = repo_ts_flags.list_for_verse(_SLUG, "2:45")
    assert len(rows) == 1
    assert rows[0]["comment"] == "v2"


def test_verse_flags_marks_own_comment_via_token(flask_client):
    _post(flask_client, _SLUG, {"verse_key": "2:45", "comment": "mine", "anon_token": "t"})
    _post(flask_client, _SLUG, {"verse_key": "2:45", "comment": "theirs", "anon_token": "other"})
    body = json.loads(flask_client.get(f"/api/ts/{_SLUG}/flags/2:45?anon_token=t").data)
    mine = [c for c in body["comments"] if c["mine"]]
    assert len(mine) == 1
    assert mine[0]["comment"] == "mine"


def test_author_hidden_from_non_identity_caller(flask_client):
    _post(flask_client, _SLUG, {"verse_key": "2:45", "comment": "x", "anon_token": "t"})
    body = json.loads(flask_client.get(f"/api/ts/{_SLUG}/flags/2:45").data)
    assert body["comments"][0]["author"] is None


def test_author_shown_to_owner(signed_in_client):
    client, _ = signed_in_client(hf_user_id="o-1", login="owner_alice", role="owner")
    client.post(
        f"/api/ts/{_SLUG}/flags",
        data=json.dumps({"verse_key": "2:45", "comment": "owner note"}),
        headers=_ORIGIN,
    )
    body = json.loads(client.get(f"/api/ts/{_SLUG}/flags/2:45").data)
    author = body["comments"][0]["author"]
    assert author is not None
    assert author["login"] == "owner_alice"


def test_signed_in_resubmit_upserts(signed_in_client):
    client, _ = signed_in_client(hf_user_id="c-9", login="carol", role="contributor")
    first = client.post(
        f"/api/ts/{_SLUG}/flags",
        data=json.dumps({"verse_key": "7:1", "comment": "v1"}),
        headers=_ORIGIN,
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/ts/{_SLUG}/flags",
        data=json.dumps({"verse_key": "7:1", "comment": "v2"}),
        headers=_ORIGIN,
    )
    assert second.status_code == 200  # update via the hf_user_id partial index
    rows = repo_ts_flags.list_for_verse(_SLUG, "7:1")
    assert len(rows) == 1
    assert rows[0]["comment"] == "v2"


def test_signed_in_can_delete_own(signed_in_client):
    client, _ = signed_in_client(hf_user_id="c-1", login="bob", role="contributor")
    client.post(
        f"/api/ts/{_SLUG}/flags",
        data=json.dumps({"verse_key": "2:45", "comment": "oops"}),
        headers=_ORIGIN,
    )
    res = client.delete(f"/api/ts/{_SLUG}/flags/2:45", headers={"Origin": "http://localhost"})
    assert res.status_code == 200
    assert json.loads(res.data)["ok"] is True
    assert repo_ts_flags.list_for_verse(_SLUG, "2:45") == []


def test_new_comment_notifies_owner(signed_in_client, flask_client):
    # An owner exists to receive the review alert...
    signed_in_client(hf_user_id="owner-1", login="owner", role="owner")
    # ...an anonymous visitor flags a verse.
    res = _post(
        flask_client, _SLUG, {"verse_key": "5:3", "comment": "misaligned", "anon_token": "z"}
    )
    assert res.status_code == 201
    notes = repo_notifications.list_active("owner-1")
    ts_notes = [n for n in notes if n["event"] == "ts_flag.created"]
    assert len(ts_notes) == 1
    assert ts_notes[0]["payload"]["verse_key"] == "5:3"
