"""Route tests for POST /api/admin/intake/<rid>/ingest.

Dual auth: bearer HF token (server-to-server, no same-origin) OR owner cookie.
Covers 200 (owner cookie + bearer owner), 401 (no creds, bad token), 403
(non-owner cookie, non-owner token), and the 409 slug-collision mapping.
"""

from __future__ import annotations

import json
from datetime import UTC

import pytest

from qua_shared.schemas import (
    Actor,
    Channel,
    ReciterEntry,
    Riwayah,
    Role,
    Source,
    Style,
    Vocab,
)

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}


@pytest.fixture(autouse=True)
def _isolated_backend(tmp_path, monkeypatch):
    from services import db
    from services import hf_bucket as _hf_bucket
    from services.db import repo_catalog

    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)

    vocab = Vocab(
        riwayat=[Riwayah(slug="hafs", short="H", name="Hafs")],
        styles=[Style(slug="murattal", short="M", name="Murattal")],
        sources=[Source(slug="src1", name="Source One")],
        channels=[Channel(slug="ch1", short="c1", name="Channel One")],
    )
    with db.transaction():
        repo_catalog.load_vocab(vocab)
        repo_catalog.insert_reciter(ReciterEntry(reciter_id="rec_x", name_en="Reciter X"))

    yield backend
    _hf_bucket.reset_backend()


def _seed_accepted_intake() -> str:
    from services import db
    from services.db import repo_requests

    requester = Actor(hf_user_id="u-1", login_at_time="alice", role=Role.CONTRIBUTOR)
    owner = Actor(hf_user_id="u-O", login_at_time="owner", role=Role.OWNER)
    with db.transaction():
        rid = repo_requests.submit(
            slug=None,
            requester=requester,
            kind="existing_reciter_new_combo",
            extra_payload={"reciter_id": "rec_x", "source": {"method": "links", "links": []}},
        )
        repo_requests.resolve_by_id(
            request_id=rid,
            status="accepted",
            transitioned_by=owner,
        )
    return rid


def _seed_pending_intake() -> str:
    """A fresh submission, never separately accepted (no accept step exists)."""
    from services import db
    from services.db import repo_requests

    requester = Actor(hf_user_id="u-1", login_at_time="alice", role=Role.CONTRIBUTOR)
    with db.transaction():
        rid = repo_requests.submit(
            slug=None,
            requester=requester,
            kind="existing_reciter_new_combo",
            extra_payload={"reciter_id": "rec_x", "source": {"method": "links", "links": []}},
        )
    return rid


def _body(slug="rec_x_hafs_ch1"):
    return {
        "reciter": None,
        "delivery": {
            "slug": slug,
            "reciter_id": "rec_x",
            "riwayah": "hafs",
            "style": "murattal",
            "source": "src1",
            "channel": "ch1",
            "audio_category": "by_surah",
        },
        "vocab_additions": None,
        "audio_manifest": {
            "chapters": {
                "1": {
                    "url": "https://cdn.example/001.mp3",
                    "bitrate_kbps": 128,
                    "bitrate_mode": "cbr",
                }
            },
        },
    }


def _patch_whoami(monkeypatch, mapping):
    import huggingface_hub

    from services.auth import token_auth

    token_auth._clear_cache_for_test()

    def _fake(token=None, **_kw):
        if token in mapping:
            return mapping[token]
        raise RuntimeError("401 invalid token")

    monkeypatch.setattr(huggingface_hub, "whoami", _fake)


# ---- cookie path ----


def test_ingest_owner_cookie_happy_path(signed_in_client):
    rid = _seed_accepted_intake()
    client, _ = signed_in_client(role="owner", hf_user_id="u-O", login="owner")
    res = client.post(f"/api/admin/intake/{rid}/ingest", headers=_HEADERS, data=json.dumps(_body()))
    assert res.status_code == 200, res.data
    body = json.loads(res.data)
    assert body["ok"] and body["slug"] == "rec_x_hafs_ch1"
    assert body["state"] == "awaiting_alignment"


def test_ingest_pending_intake_no_accept_needed(signed_in_client):
    """A pending submission is directly ingestable — aligning it is the accept.
    Ingest mints the delivery, seeds alignment, and flips the row to accepted."""
    rid = _seed_pending_intake()
    client, _ = signed_in_client(role="owner", hf_user_id="u-O", login="owner")
    res = client.post(f"/api/admin/intake/{rid}/ingest", headers=_HEADERS, data=json.dumps(_body()))
    assert res.status_code == 200, res.data
    body = json.loads(res.data)
    assert body["ok"] and body["slug"] == "rec_x_hafs_ch1"
    assert body["state"] == "awaiting_alignment"

    from services.db import repo_requests

    row = repo_requests.get_by_id(rid)
    assert row["status"] == "accepted" and row["slug"] == "rec_x_hafs_ch1"


def test_ingest_anonymous_401(flask_client):
    rid = _seed_accepted_intake()
    res = flask_client.post(
        f"/api/admin/intake/{rid}/ingest", headers=_HEADERS, data=json.dumps(_body())
    )
    assert res.status_code == 401


def test_ingest_non_owner_cookie_403(signed_in_client):
    rid = _seed_accepted_intake()
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M", login="maint")
    res = client.post(f"/api/admin/intake/{rid}/ingest", headers=_HEADERS, data=json.dumps(_body()))
    assert res.status_code == 403


def test_ingest_cookie_path_requires_same_origin(signed_in_client):
    rid = _seed_accepted_intake()
    client, _ = signed_in_client(role="owner", hf_user_id="u-O")
    # No Origin/Referer → cookie path rejects cross-origin.
    res = client.post(
        f"/api/admin/intake/{rid}/ingest",
        headers={"Content-Type": "application/json"},
        data=json.dumps(_body()),
    )
    assert res.status_code == 403


# ---- bearer path ----


def test_ingest_bearer_owner_happy_path(flask_client, monkeypatch):
    from tests.conftest import _seed_role

    _seed_role("owner-b", login="ownerb", role="owner")
    _patch_whoami(monkeypatch, {"tok-owner": {"id": "owner-b", "name": "ownerb"}})
    rid = _seed_accepted_intake()

    # Bearer path: NO Origin header (server-to-server), must still succeed.
    res = flask_client.post(
        f"/api/admin/intake/{rid}/ingest",
        headers={"Content-Type": "application/json", "Authorization": "Bearer tok-owner"},
        data=json.dumps(_body()),
    )
    assert res.status_code == 200, res.data
    assert json.loads(res.data)["slug"] == "rec_x_hafs_ch1"


def test_ingest_bearer_non_owner_403(flask_client, monkeypatch):
    from tests.conftest import _seed_role

    _seed_role("maint-b", login="maintb", role="maintainer")
    _patch_whoami(monkeypatch, {"tok-maint": {"id": "maint-b", "name": "maintb"}})
    rid = _seed_accepted_intake()

    res = flask_client.post(
        f"/api/admin/intake/{rid}/ingest",
        headers={"Content-Type": "application/json", "Authorization": "Bearer tok-maint"},
        data=json.dumps(_body()),
    )
    assert res.status_code == 403


def test_ingest_bad_bearer_token_401(flask_client, monkeypatch):
    _patch_whoami(monkeypatch, {"tok-good": {"id": "owner-b", "name": "o"}})
    rid = _seed_accepted_intake()
    res = flask_client.post(
        f"/api/admin/intake/{rid}/ingest",
        headers={"Content-Type": "application/json", "Authorization": "Bearer tok-bad"},
        data=json.dumps(_body()),
    )
    assert res.status_code == 401


# ---- error mappings ----


def test_ingest_slug_collision_409(signed_in_client):
    from datetime import datetime, timezone

    from qua_shared.schemas import AudioCategory, Delivery
    from services import db
    from services.db import repo_catalog

    with db.transaction():
        repo_catalog.insert_delivery(
            Delivery(
                slug="rec_x_hafs_ch1",
                reciter_id="rec_x",
                riwayah="hafs",
                style="murattal",
                source="src1",
                channel="ch1",
                audio_category=AudioCategory.BY_SURAH,
                chapter_count=114,
                added_at=datetime.now(UTC),
                added_by_hf_id="seed",
            )
        )
    rid = _seed_accepted_intake()
    client, _ = signed_in_client(role="owner", hf_user_id="u-O")
    res = client.post(f"/api/admin/intake/{rid}/ingest", headers=_HEADERS, data=json.dumps(_body()))
    assert res.status_code == 409


def test_ingest_unknown_request_404(signed_in_client):
    client, _ = signed_in_client(role="owner", hf_user_id="u-O")
    res = client.post(
        "/api/admin/intake/rq_nope/ingest", headers=_HEADERS, data=json.dumps(_body())
    )
    assert res.status_code == 404
