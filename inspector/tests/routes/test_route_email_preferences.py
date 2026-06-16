"""``/api/me/email-preferences`` + ``/api/email-unsubscribe`` route coverage.

The contract that matters: subscriptions are keyed by email (so anonymous works
— never 401), the manage token is minted on first save + echoed, GET resolves by
HF cookie when signed in / by ``?token=`` otherwise, a bad email is rejected, and
the unsubscribe link turns every event off for that address.
"""

from __future__ import annotations

import json

from services.db import repo_email_subscriptions as repo_subs

_ORIGIN = {"Origin": "http://localhost"}


def _post(client, body):
    return client.post(
        "/api/me/email-preferences",
        data=json.dumps(body),
        headers={**_ORIGIN, "Content-Type": "application/json"},
    )


def test_get_anonymous_returns_defaults_not_401(flask_client):
    res = flask_client.get("/api/me/email-preferences")
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["email"] == ""
    assert body["recitation_published"] == "off"
    assert "manage_token" not in body  # no row yet


def test_post_anonymous_creates_row_and_echoes_token(flask_client):
    res = _post(flask_client, {"email": "anon@example.com", "recitation_published": "all"})
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["email"] == "anon@example.com"
    assert body["recitation_published"] == "all"
    token = body["manage_token"]
    assert token
    # Persisted + retrievable by the echoed token.
    assert repo_subs.get_by_token(token)["prefs"]["recitation_published"] == "all"


def test_get_by_token_returns_saved_prefs(flask_client):
    token = json.loads(
        _post(flask_client, {"email": "tok@example.com", "github_release": True}).data
    )["manage_token"]
    body = json.loads(flask_client.get(f"/api/me/email-preferences?token={token}").data)
    assert body["email"] == "tok@example.com"
    assert body["github_release"] is True
    assert body["manage_token"] == token


def test_post_invalid_email_is_400(flask_client):
    assert _post(flask_client, {"email": "not-an-email", "github_release": True}).status_code == 400


def test_post_rejects_unknown_field(flask_client):
    assert _post(flask_client, {"email": "x@y.com", "bogus": 1}).status_code == 400


def test_signed_in_post_associates_user_and_get_resolves_by_cookie(signed_in_client):
    client, _ = signed_in_client(hf_user_id="e-1", login="alice")
    _post(client, {"email": "alice@example.com", "request_aligned": True})
    # A fresh GET (no token) resolves the row by the HF cookie.
    body = json.loads(client.get("/api/me/email-preferences").data)
    assert body["email"] == "alice@example.com"
    assert body["request_aligned"] is True
    assert repo_subs.get_by_hf_user("e-1")["email"] == "alice@example.com"


def test_unsubscribe_turns_events_off(flask_client):
    token = json.loads(
        _post(flask_client, {"email": "bye@example.com", "recitation_published": "all"}).data
    )["manage_token"]
    res = flask_client.get(f"/api/email-unsubscribe?token={token}")
    assert res.status_code == 200
    assert b"unsubscribed" in res.data.lower()
    assert repo_subs.get_by_token(token)["prefs"]["recitation_published"] == "off"
