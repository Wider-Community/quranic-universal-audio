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


def test_owner_notified_on_new_report(flask_client, seed_role):
    seed_role("owner-1", login="owner", role="owner")
    assert _post(flask_client, _anon_other()).status_code == 201
    notes = repo_notifications.list_active("owner-1")
    assert [n["event"] for n in notes] == ["ts_report.created"]
    # The Dashboard rail deep-links to the verse from (slug, payload.verse_key) and
    # badges by payload.category — assert the whole contract, not just verse_key.
    note = notes[0]
    assert note["slug"] == _SLUG
    assert note["payload"]["verse_key"] == "2:45"
    assert note["payload"]["category"] == "other"


def test_non_owner_cannot_resolve(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    assert _post(client, _anon_other()).status_code == 201
    rid = client.get(f"/api/ts/{_SLUG}/reports/2:45").get_json()["reports"][0]["id"]
    resp = client.post(f"/api/ts/{_SLUG}/reports/{rid}/resolve", headers=_ORIGIN, json={})
    assert resp.status_code == 403


def test_owner_resolve_notifies_signed_in_reporter(signed_in_client):
    reporter, ruser = signed_in_client(role="contributor")
    body = {
        "verse_key": "2:45",
        "category": "audio",
        "comment": "noise",
        "target": {"kind": "verse"},
    }
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


# --- batch create + group resolve ------------------------------------------


def _timing_item(cell_index: int, *, word_index: int = 0, onset: str = "early") -> dict:
    return {
        "category": "timing",
        "onset": onset,
        "target": {"kind": "cell", "word_index": word_index, "cell_index": cell_index},
    }


def _tajweed_item(cell_index: int, *, word_index: int = 0) -> dict:
    return {
        "category": "tajweed",
        "subtype": "wrong_rule",
        "target": {"kind": "cell", "word_index": word_index, "cell_index": cell_index},
        "comment": "wrong rule",
        "selected_rule_tags": ["qalqala"],
    }


def _post_batch(client, items, *, verse_key="2:45", anon_token="anon-1"):
    body = {"verse_key": verse_key, "items": items, "anon_token": anon_token}
    return client.post(
        f"/api/ts/{_SLUG}/reports/batch",
        data=json.dumps(body),
        content_type="application/json",
        headers=_ORIGIN,
    )


def test_batch_requires_same_origin(flask_client):
    resp = flask_client.post(
        f"/api/ts/{_SLUG}/reports/batch",
        data=json.dumps({"verse_key": "2:45", "items": [_timing_item(0)], "anon_token": "a"}),
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_batch_anon_requires_token(flask_client):
    resp = _post_batch(flask_client, [_timing_item(0)], anon_token="")
    assert resp.status_code == 400


def test_batch_validation_error_bubbles(flask_client):
    bad = {"category": "timing", "target": {"kind": "cell", "word_index": 0, "cell_index": 0}}
    assert _post_batch(flask_client, [bad]).status_code == 400  # timing needs an onset/offset axis


def test_batch_creates_rows_and_echoes(flask_client):
    resp = _post_batch(flask_client, [_timing_item(0), _timing_item(1), _timing_item(2)])
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["created_count"] == 3
    assert len(body["reports"]) == 3


def test_batch_timing_word_fires_one_owner_notification(flask_client, seed_role):
    seed_role("owner-1", login="owner", role="owner")
    items = [_timing_item(i) for i in range(6)]  # 6 cells, same word
    assert _post_batch(flask_client, items).status_code == 201
    notes = [
        n for n in repo_notifications.list_active("owner-1") if n["event"] == "ts_report.created"
    ]
    assert len(notes) == 1


def test_batch_tajweed_fires_per_cell_notification(flask_client, seed_role):
    seed_role("owner-1", login="owner", role="owner")
    items = [_tajweed_item(i) for i in range(3)]
    assert _post_batch(flask_client, items).status_code == 201
    notes = [
        n for n in repo_notifications.list_active("owner-1") if n["event"] == "ts_report.created"
    ]
    assert len(notes) == 3


def test_batch_mixed_notification_counts(flask_client, seed_role):
    seed_role("owner-1", login="owner", role="owner")
    items = [_timing_item(0), _timing_item(1), _timing_item(2), _timing_item(3)]
    items += [_tajweed_item(0), _tajweed_item(1)]
    assert _post_batch(flask_client, items).status_code == 201
    notes = [
        n for n in repo_notifications.list_active("owner-1") if n["event"] == "ts_report.created"
    ]
    assert len(notes) == 3  # 1 timing word + 2 tajweed cells


def test_batch_tajweed_same_cell_both_subtypes_fire_two_notifications(flask_client, seed_role):
    seed_role("owner-1", login="owner", role="owner")
    cell = {"kind": "cell", "word_index": 0, "cell_index": 1}
    items = [
        {
            "category": "tajweed",
            "subtype": "wrong_rule",
            "target": cell,
            "comment": "wrong",
            "selected_rule_tags": ["qalqala"],
        },
        {"category": "tajweed", "subtype": "missing_rule", "target": cell, "comment": "missing"},
    ]
    assert _post_batch(flask_client, items).status_code == 201
    rows = flask_client.get(f"/api/ts/{_SLUG}/reports/2:45?anon_token=anon-1").get_json()["reports"]
    assert {r["subtype"] for r in rows} == {"wrong_rule", "missing_rule"}
    notes = [
        n for n in repo_notifications.list_active("owner-1") if n["event"] == "ts_report.created"
    ]
    assert len(notes) == 2


def test_batch_tajweed_selected_rule_tags_roundtrip(flask_client):
    assert _post_batch(flask_client, [_tajweed_item(0)]).status_code == 201
    rep = flask_client.get(f"/api/ts/{_SLUG}/reports/2:45?anon_token=anon-1").get_json()["reports"][
        0
    ]
    assert rep["selected_rule_tags"] == ["qalqala"]


def _phoneme_item(pfi: int, *, word_index: int = 0) -> dict:
    return {
        "category": "phonemes",
        "target": {"kind": "phoneme", "word_index": word_index, "phoneme_flat_index": pfi},
    }


def test_batch_phoneme_word_fires_one_owner_notification(flask_client, seed_role):
    seed_role("owner-1", login="owner", role="owner")
    items = [_phoneme_item(i) for i in range(4)]  # 4 phonemes, same word
    assert _post_batch(flask_client, items).status_code == 201
    notes = [
        n for n in repo_notifications.list_active("owner-1") if n["event"] == "ts_report.created"
    ]
    assert len(notes) == 1


def test_resolve_word_group_accepts_phonemes(signed_in_client):
    reporter, _ = signed_in_client(role="contributor")
    assert _post_batch(reporter, [_phoneme_item(0), _phoneme_item(1)]).status_code == 201
    owner, _ = signed_in_client(hf_user_id="owner-1", login="owner", role="owner")
    resp = owner.post(
        f"/api/ts/{_SLUG}/reports/2:45/word/0/phonemes/resolve", headers=_ORIGIN, json={}
    )
    assert resp.status_code == 200
    rows = resp.get_json()["reports"]
    assert len(rows) == 2 and all(r["status"] == "resolved" for r in rows)


def test_nonpublic_reports_hidden_from_other_anon_viewer(flask_client):
    items = [_timing_item(0), _tajweed_item(1), _phoneme_item(2)]
    assert _post_batch(flask_client, items).status_code == 201
    # A different anonymous viewer gets only the public timing report + count.
    other = flask_client.get(f"/api/ts/{_SLUG}/reports/2:45?anon_token=anon-2").get_json()[
        "reports"
    ]
    assert {r["category"] for r in other} == {"timing"}
    counts = flask_client.get(f"/api/ts/{_SLUG}/reports?anon_token=anon-2").get_json()["reports"]
    assert counts == [{"verse_key": "2:45", "open_count": 1, "resolved_count": 0}]
    # The reporter (their own token) gets all three.
    own = flask_client.get(f"/api/ts/{_SLUG}/reports/2:45?anon_token=anon-1").get_json()["reports"]
    assert {r["category"] for r in own} == {"timing", "tajweed", "phonemes"}


def test_nonpublic_reports_visible_to_capable_owner_only(signed_in_client):
    reporter, _ = signed_in_client(role="contributor")
    assert (
        _post_batch(reporter, [_timing_item(0), _tajweed_item(1), _phoneme_item(2)]).status_code
        == 201
    )
    # Owner holds timestamps.view_nonpublic_reports → sees every category.
    owner, _ = signed_in_client(hf_user_id="owner-1", login="owner", role="owner")
    seen = owner.get(f"/api/ts/{_SLUG}/reports/2:45").get_json()["reports"]
    assert {r["category"] for r in seen} == {"timing", "tajweed", "phonemes"}
    # A different contributor (no capability, not the reporter) sees only timing.
    other, _ = signed_in_client(hf_user_id="other-1", login="other", role="contributor")
    seen2 = other.get(f"/api/ts/{_SLUG}/reports/2:45").get_json()["reports"]
    assert {r["category"] for r in seen2} == {"timing"}


def test_resolve_word_group_rejects_non_timing(signed_in_client):
    owner, _ = signed_in_client(hf_user_id="owner-1", login="owner", role="owner")
    resp = owner.post(
        f"/api/ts/{_SLUG}/reports/2:45/word/0/tajweed/resolve", headers=_ORIGIN, json={}
    )
    assert resp.status_code == 400


def test_resolve_word_group_non_owner_forbidden(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    assert _post_batch(client, [_timing_item(0)], anon_token="").status_code == 201
    resp = client.post(
        f"/api/ts/{_SLUG}/reports/2:45/word/0/timing/resolve", headers=_ORIGIN, json={}
    )
    assert resp.status_code == 403


def test_resolve_word_group_resolves_and_notifies_reporter(signed_in_client):
    reporter, ruser = signed_in_client(role="contributor")
    assert (
        _post_batch(reporter, [_timing_item(0), _timing_item(1)], anon_token="").status_code == 201
    )

    owner, _ = signed_in_client(hf_user_id="owner-1", login="owner", role="owner")
    resp = owner.post(
        f"/api/ts/{_SLUG}/reports/2:45/word/0/timing/resolve",
        headers=_ORIGIN,
        json={"comment": "fixed"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["reports"]) == 2
    assert all(r["status"] == "resolved" for r in body["reports"])

    notes = [
        n
        for n in repo_notifications.list_active(ruser["hf_user_id"])
        if n["event"] == "ts_report.resolved"
    ]
    assert len(notes) == 1
