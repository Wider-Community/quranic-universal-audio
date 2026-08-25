"""Native report route validation, visibility, notifications, and resolution."""

from __future__ import annotations

import pytest

from services.db import repo_notifications
from services.ts_reports import ts_target_snapshot

_ORIGIN = {"Origin": "http://localhost"}
_SLUG = "reciter-a"


def _target(kind: str = "verse", target_id: str = "2:45", reading_id: str = "r1") -> dict:
    return {"reading_id": reading_id, "kind": kind, "target_id": target_id}


@pytest.fixture(autouse=True)
def native_snapshots(monkeypatch):
    def build(_slug: str, _verse: str, target: dict) -> dict:
        native: dict[str, object] = {"id": target["target_id"]}
        if target["kind"] != "verse":
            native.update({"word_id": 1, "word_ref": "2:45:1"})
        return {
            "native_schema_version": 2,
            "shard_schema_version": 12,
            "native": native,
            "timing": {"start_ms": 10, "end_ms": 20},
        }

    monkeypatch.setattr(ts_target_snapshot, "build_snapshot", build)


def _post(client, body: dict):
    return client.post(f"/api/ts/{_SLUG}/reports", json=body, headers=_ORIGIN)


def _anon_other() -> dict:
    return {
        "verse_key": "2:45",
        "category": "other",
        "comment": "something off",
        "target": _target(),
        "anon_token": "anon-1",
    }


def _timing(target_id: str, reading_id: str = "r1") -> dict:
    return {
        "category": "timing",
        "onset": "early",
        "target": _target("column", target_id, reading_id),
    }


def _batch(client, items: list[dict], anon_token: str = "anon-1"):
    return client.post(
        f"/api/ts/{_SLUG}/reports/batch",
        json={"verse_key": "2:45", "items": items, "anon_token": anon_token},
        headers=_ORIGIN,
    )


def test_create_requires_same_origin_and_anonymous_token(flask_client):
    assert flask_client.post(f"/api/ts/{_SLUG}/reports", json=_anon_other()).status_code == 403
    body = _anon_other()
    body.pop("anon_token")
    assert _post(flask_client, body).status_code == 400


def test_create_roundtrips_native_target_and_snapshot(flask_client):
    response = _post(flask_client, _anon_other())
    assert response.status_code == 201
    created = response.get_json()
    assert created["target"] == _target()
    assert created["snapshot"]["shard_schema_version"] == 12
    listed = flask_client.get(f"/api/ts/{_SLUG}/reports/2:45?anon_token=anon-1")
    assert listed.status_code == 200
    assert listed.get_json()["reports"][0]["mine"] is True


def test_unresolved_target_blocks_create(flask_client, monkeypatch):
    monkeypatch.setattr(ts_target_snapshot, "build_snapshot", lambda *_: None)
    assert _post(flask_client, _anon_other()).status_code == 409


def test_owner_is_notified_only_for_a_new_report(flask_client, seed_role):
    seed_role("owner-1", login="owner", role="owner")
    assert _post(flask_client, _anon_other()).status_code == 201
    assert _post(flask_client, _anon_other()).status_code == 200
    notes = repo_notifications.list_active("owner-1")
    assert [note["event"] for note in notes] == ["ts_report.created"]


def test_owner_resolves_and_reporter_is_notified(signed_in_client):
    reporter, user = signed_in_client(role="contributor")
    body = {
        "verse_key": "2:45",
        "category": "audio",
        "comment": "noise",
        "target": _target(),
    }
    created = _post(reporter, body)
    assert created.status_code == 201
    owner, _ = signed_in_client(hf_user_id="owner-1", login="owner", role="owner")
    resolved = owner.post(
        f"/api/ts/{_SLUG}/reports/{created.get_json()['id']}/resolve",
        json={"comment": "fixed"},
        headers=_ORIGIN,
    )
    assert resolved.status_code == 200
    assert resolved.get_json()["status"] == "resolved"
    assert any(
        note["event"] == "ts_report.resolved"
        for note in repo_notifications.list_active(user["hf_user_id"])
    )


def test_batch_coalesces_word_notifications_by_reading(flask_client, seed_role):
    seed_role("owner-1", login="owner", role="owner")
    response = _batch(flask_client, [_timing("10"), _timing("11"), _timing("10", "r2")])
    assert response.status_code == 201
    assert response.get_json()["created_count"] == 3
    notes = [
        note
        for note in repo_notifications.list_active("owner-1")
        if note["event"] == "ts_report.created"
    ]
    assert len(notes) == 2


def test_nonpublic_native_flags_are_visible_only_to_reporter_or_owner(
    flask_client, signed_in_client
):
    tajweed = {
        "verse_key": "2:45",
        "category": "tajweed",
        "subtype": "wrong_rule",
        "comment": "wrong",
        "selected_rule_tags": ["qalqala_sughra"],
        "target": _target("column", "10"),
        "anon_token": "anon-1",
    }
    assert _post(flask_client, tajweed).status_code == 201
    assert (
        flask_client.get(f"/api/ts/{_SLUG}/reports/2:45?anon_token=anon-2").get_json()["reports"]
        == []
    )
    assert (
        len(
            flask_client.get(f"/api/ts/{_SLUG}/reports/2:45?anon_token=anon-1").get_json()[
                "reports"
            ]
        )
        == 1
    )
    owner, _ = signed_in_client(hf_user_id="owner-1", login="owner", role="owner")
    assert len(owner.get(f"/api/ts/{_SLUG}/reports/2:45").get_json()["reports"]) == 1


def test_group_resolution_uses_reading_and_native_word_id(signed_in_client):
    reporter, _ = signed_in_client(role="contributor")
    assert _batch(reporter, [_timing("10"), _timing("11")], anon_token="").status_code == 201
    owner, _ = signed_in_client(hf_user_id="owner-1", login="owner", role="owner")
    response = owner.post(
        f"/api/ts/{_SLUG}/reports/2:45/reading/r1/word/1/timing/resolve",
        json={"comment": "fixed"},
        headers=_ORIGIN,
    )
    assert response.status_code == 200
    assert len(response.get_json()["reports"]) == 2


def test_batch_rejects_legacy_positional_targets(flask_client):
    item = {
        "category": "timing",
        "onset": "early",
        "target": {"kind": "cell", "word_index": 0, "cell_index": 1},
    }
    assert _batch(flask_client, [item]).status_code == 400
