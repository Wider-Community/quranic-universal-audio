"""``POST /api/guides/viewed`` + ``/api/me`` guides_read coverage.

The route records per-user "read" marks for the validation-accordion guides.
The set drives the FE unread border + first-edit onboarding gate, so the
contract that matters here is: signed-in only, allowlist-validated, alias-
collapsed, idempotent, and reflected back through ``/api/me``.
"""

from __future__ import annotations

import json

_ORIGIN = {"Origin": "http://localhost"}


def _post_viewed(client, category):
    return client.post(
        "/api/guides/viewed",
        data=json.dumps({"category": category}),
        content_type="application/json",
        headers=_ORIGIN,
    )


def test_viewed_requires_sign_in(flask_client):
    """Anonymous callers get 401 — there is no per-user row to write."""
    resp = _post_viewed(flask_client, "failed")
    assert resp.status_code == 401


def test_viewed_rejects_unknown_category(signed_in_client):
    """An out-of-allowlist category is a 400 so the table never accrues junk."""
    client, _ = signed_in_client(hf_user_id="g-1", login="alice")
    assert _post_viewed(client, "not_a_guide").status_code == 400


def test_viewed_records_and_me_reflects_it(signed_in_client):
    """A valid view returns 204 and shows up in the next /api/me guides_read."""
    client, _ = signed_in_client(hf_user_id="g-2", login="bob")
    assert _post_viewed(client, "failed").status_code == 204

    body = json.loads(client.get("/api/me").data)
    assert body["guides_read"] == ["failed"]


def test_viewed_collapses_low_confidence_alias(signed_in_client):
    """low_confidence_v2 is stored as low_confidence (one required reading)."""
    client, _ = signed_in_client(hf_user_id="g-3", login="carol")
    assert _post_viewed(client, "low_confidence_v2").status_code == 204

    body = json.loads(client.get("/api/me").data)
    assert body["guides_read"] == ["low_confidence"]


def test_viewed_is_idempotent(signed_in_client):
    """Re-posting the same (or aliased) guide never duplicates the row."""
    client, _ = signed_in_client(hf_user_id="g-4", login="dave")
    _post_viewed(client, "low_confidence")
    _post_viewed(client, "low_confidence")
    _post_viewed(client, "low_confidence_v2")  # collapses to the same key

    body = json.loads(client.get("/api/me").data)
    assert body["guides_read"] == ["low_confidence"]


def test_me_signed_in_includes_guides_read_empty_by_default(signed_in_client):
    """Before reading anything, a fresh user reports an empty guides_read."""
    client, _ = signed_in_client(hf_user_id="g-5", login="erin")
    body = json.loads(client.get("/api/me").data)
    assert body["guides_read"] == []
