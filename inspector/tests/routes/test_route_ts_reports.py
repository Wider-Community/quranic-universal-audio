"""``/api/ts/<slug>/reports`` route coverage.

Public categorized reports: anonymous + signed-in create, capability + same-origin
gating, owner resolve → reporter notification, and identity redaction.
"""

from __future__ import annotations

import json

from services.db import repo_notifications

_ORIGIN = {"Origin": "http://localhost"}
_SLUG = "reciter-a"


def _post(client, body: dict):
    return client.post(
        f"/api/ts/{_SLUG}/reports",
        data=json.dumps(body),
        content_type="application/json",
        headers=_ORIGIN,
    )


def _anon_other(target=None):
    return {
        "verse_key": "2:45",
        "category": "other",
        "comment": "something off",
        "target": target or {"kind": "verse"},
        "anon_token": "anon-1",
    }


def test_create_requires_same_origin(flask_client):
    resp = flask_client.post(
        f"/api/ts/{_SLUG}/reports", data=json.dumps(_anon_other()), content_type="application/json"
    )
    assert resp.status_code == 403


def test_anon_create_requires_token(flask_client):
    body = _anon_other()
    del body["anon_token"]
    assert _post(flask_client, body).status_code == 400


def test_anon_create_then_get_verse(flask_client):
    assert _post(flask_client, _anon_other()).status_code == 201
    resp = flask_client.get(f"/api/ts/{_SLUG}/reports/2:45?anon_token=anon-1")
    payload = resp.get_json()
    assert resp.status_code == 200
    assert len(payload["reports"]) == 1
    rep = payload["reports"][0]
    assert rep["category"] == "other"
    assert rep["mine"] is True
    assert rep["author"] is None  # anon caller can't see identity
    # reciter-level counts pill
    counts = flask_client.get(f"/api/ts/{_SLUG}/reports").get_json()
    assert counts["reports"] == [{"verse_key": "2:45", "open_count": 1, "resolved_count": 0}]


def test_create_validation_error_mapping_without_comment(flask_client):
    body = {
        "verse_key": "2:45",
        "category": "mapping",
        "target": {"kind": "column", "word_index": 0, "source_letter_index": 1},
        "anon_token": "anon-1",
    }
    assert _post(flask_client, body).status_code == 400


def test_owner_notified_on_new_report(flask_client, seed_role):
    seed_role("owner-1", login="owner", role="owner")
    assert _post(flask_client, _anon_other()).status_code == 201
    notes = repo_notifications.list_active("owner-1")
    assert [n["event"] for n in notes] == ["ts_report.created"]
    assert notes[0]["payload"]["verse_key"] == "2:45"


def test_non_owner_cannot_resolve(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    assert _post(client, _anon_other()).status_code == 201
    rid = client.get(f"/api/ts/{_SLUG}/reports/2:45").get_json()["reports"][0]["id"]
    resp = client.post(f"/api/ts/{_SLUG}/reports/{rid}/resolve", headers=_ORIGIN, json={})
    assert resp.status_code == 403


def test_owner_resolve_notifies_signed_in_reporter(signed_in_client):
    reporter, ruser = signed_in_client(role="contributor")
    body = {"verse_key": "2:45", "category": "audio", "comment": "noise", "target": {"kind": "verse"}}
    assert _post(reporter, body).status_code == 201
    rid = reporter.get(f"/api/ts/{_SLUG}/reports/2:45").get_json()["reports"][0]["id"]

    owner, _ = signed_in_client(hf_user_id="owner-1", login="owner", role="owner")
    resp = owner.post(
        f"/api/ts/{_SLUG}/reports/{rid}/resolve", headers=_ORIGIN, json={"comment": "fixed"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "resolved"

    notes = repo_notifications.list_active(ruser["hf_user_id"])
    assert any(n["event"] == "ts_report.resolved" for n in notes)


def test_identity_redaction_owner_sees_author(signed_in_client):
    reporter, ruser = signed_in_client(role="contributor")
    body = {"verse_key": "2:45", "category": "audio", "comment": "x", "target": {"kind": "verse"}}
    assert _post(reporter, body).status_code == 201

    owner, _ = signed_in_client(hf_user_id="owner-1", login="owner", role="owner")
    rep = owner.get(f"/api/ts/{_SLUG}/reports/2:45").get_json()["reports"][0]
    assert rep["author"]["login"] == ruser["login"]
