"""Tests for the request-flow routes.

Covers all four routes under ``inspector/routes/requests.py``:

- ``POST /api/reciter/<slug>/request`` — contributor+
- ``GET  /api/admin/request/<slug>`` — maintainer+ (with tier-aware actor redaction)
- ``POST /api/admin/request/<slug>/reject-soft`` — maintainer+
- ``POST /api/admin/request/<slug>/reject-hard`` — maintainer+
- ``POST /api/admin/reciter/<slug>/undiscard`` — owner-only
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("INSPECTOR_SESSION_SECRET", "0" * 64)

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_backend(tmp_path, monkeypatch):
    """Per-test FilesystemBackend so route writes never reach the real bucket."""
    from scripts.lib.schemas import (
        AudioCategory,
        Channel,
        Delivery,
        ReciterCatalog,
        ReciterEntry,
        ReciterRow,
        ReciterState,
        ReciterStateFile,
        Riwayah,
        Source,
        Style,
        Visibility,
        Vocab,
    )
    from services import catalog as catalog_service
    from services import hf_bucket as _hf_bucket
    from services import pending_requests as pending_requests_service
    from services import state as state_service
    from services import storage_paths

    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)

    # Seed the catalog (3 deliveries) + state rows into the SQLite substrate.
    from services import db
    from services.db import repo_catalog
    from tests.conftest import _seed_state

    now = datetime.now(timezone.utc)
    vocab = Vocab(
        riwayat=[Riwayah(slug="hafs", short="H", name="Hafs"),
                 Riwayah(slug="warsh", short="W", name="Warsh")],
        styles=[Style(slug="murattal", short="M", name="Murattal")],
        sources=[Source(slug="src1", name="Source One")],
        channels=[Channel(slug="ch1", short="c1", name="Channel One")],
    )
    with db.transaction():
        repo_catalog.load_vocab(vocab)
        for rid, name in (
            ("rec_clean", "Clean Reciter"),
            ("rec_pending", "Pending Reciter"),
            ("rec_discarded", "Discarded Reciter"),
        ):
            repo_catalog.insert_reciter(ReciterEntry(reciter_id=rid, name_en=name))
            repo_catalog.insert_delivery(Delivery(
                slug=rid, reciter_id=rid, riwayah="hafs", style="murattal",
                source="src1", channel="ch1", audio_category=AudioCategory.BY_SURAH,
                chapter_count=114, added_at=now, added_by_hf_id="seed",
            ))

    _seed_state("rec_clean", state="catalogued", reciter_id="rec_clean")
    _seed_state("rec_pending", state="awaiting_alignment", reciter_id="rec_pending")
    _seed_state("rec_discarded", state="catalogued", visibility="discarded",
                visibility_reason="testing setup", reciter_id="rec_discarded")

    # Seed an in-flight pending entry for rec_pending so admin GET + reject
    # tests have something to inspect.
    from scripts.lib.schemas import Actor, ProposedEdits, Role
    pending_requests_service.submit(
        "rec_pending",
        requester=Actor(
            hf_user_id="u-requester",
            login_at_time="requester",
            role=Role.CONTRIBUTOR,
        ),
        edits=ProposedEdits(name_en="Renamed", recording_year=2024),
        comments="Pre-seeded pending request for tests.",
    )

    # Silence audit appends so tests don't write JSONL into tmp_path on every call.
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    yield backend

    _hf_bucket.reset_backend()


# ---------------------------------------------------------------------------
# POST /api/reciter/<slug>/request
# ---------------------------------------------------------------------------


def test_submit_anonymous_returns_401(flask_client):
    res = flask_client.post(
        "/api/reciter/rec_clean/request",
        headers=_HEADERS,
        data=json.dumps({"proposed_edits": {}, "comments": None}),
    )
    assert res.status_code == 401


def test_submit_contributor_happy_path(signed_in_client):
    client, _ = signed_in_client(role="contributor", hf_user_id="u-1", login="alice")
    res = client.post(
        "/api/reciter/rec_clean/request",
        headers=_HEADERS,
        data=json.dumps({
            "proposed_edits": {"name_en": "Cleaner Name", "recording_year": 2023},
            "comments": "Found a better recording.",
        }),
    )
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["state"] == "awaiting_alignment"

    from services import pending_requests as pending_requests_service
    pending = pending_requests_service.get("rec_clean")
    assert pending is not None
    assert pending.proposed_edits.name_en == "Cleaner Name"
    assert pending.requester.hf_user_id == "u-1"


def test_submit_rejects_when_already_pending(signed_in_client):
    client, _ = signed_in_client(role="contributor", hf_user_id="u-1")
    res = client.post(
        "/api/reciter/rec_pending/request",
        headers=_HEADERS,
        data=json.dumps({"proposed_edits": {}, "comments": None}),
    )
    assert res.status_code == 409


def test_submit_rejects_unknown_reciter(signed_in_client):
    client, _ = signed_in_client(role="contributor", hf_user_id="u-1")
    res = client.post(
        "/api/reciter/nope/request",
        headers=_HEADERS,
        data=json.dumps({"proposed_edits": {}, "comments": None}),
    )
    assert res.status_code == 404


def test_submit_rejects_discarded(signed_in_client):
    client, _ = signed_in_client(role="contributor", hf_user_id="u-1")
    res = client.post(
        "/api/reciter/rec_discarded/request",
        headers=_HEADERS,
        data=json.dumps({"proposed_edits": {}, "comments": None}),
    )
    assert res.status_code == 400


def test_submit_rejects_bad_year(signed_in_client):
    client, _ = signed_in_client(role="contributor", hf_user_id="u-1")
    res = client.post(
        "/api/reciter/rec_clean/request",
        headers=_HEADERS,
        data=json.dumps({
            "proposed_edits": {"recording_year": 1700},
            "comments": None,
        }),
    )
    assert res.status_code == 400


def test_submit_rejects_bad_origin(signed_in_client):
    client, _ = signed_in_client(role="contributor", hf_user_id="u-1")
    res = client.post(
        "/api/reciter/rec_clean/request",
        headers={"Content-Type": "application/json", "Origin": "http://evil.example"},
        data=json.dumps({"proposed_edits": {}, "comments": None}),
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/admin/request/<slug>
# ---------------------------------------------------------------------------


def test_get_pending_anonymous_returns_401(flask_client):
    res = flask_client.get("/api/admin/request/rec_pending")
    assert res.status_code == 401


def test_get_pending_contributor_returns_403(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    res = client.get("/api/admin/request/rec_pending")
    assert res.status_code == 403


def test_get_pending_maintainer_redacts_requester_login(signed_in_client):
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.get("/api/admin/request/rec_pending")
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["slug"] == "rec_pending"
    assert body["proposed_edits"]["name_en"] == "Renamed"
    assert "requester_login" not in body
    assert "requester_hf_user_id" not in body
    assert body["requester_role"] == "contributor"


def test_get_pending_owner_includes_requester_login(signed_in_client):
    client, _ = signed_in_client(role="owner", hf_user_id="u-O")
    res = client.get("/api/admin/request/rec_pending")
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["requester_login"] == "requester"
    assert body["requester_hf_user_id"] == "u-requester"


def test_get_pending_404_when_no_pending(signed_in_client):
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.get("/api/admin/request/rec_clean")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/admin/request/<slug>/reject-soft
# ---------------------------------------------------------------------------


def test_reject_soft_contributor_returns_403(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    res = client.post(
        "/api/admin/request/rec_pending/reject-soft",
        headers=_HEADERS,
        data=json.dumps({"reason": "ten chars+ reason"}),
    )
    assert res.status_code == 403


def test_reject_soft_maintainer_happy_path(signed_in_client):
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.post(
        "/api/admin/request/rec_pending/reject-soft",
        headers=_HEADERS,
        data=json.dumps({"reason": "not a priority right now"}),
    )
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["state"] == "catalogued"

    from services import pending_requests as pending_requests_service
    from services import state as state_service
    assert pending_requests_service.get("rec_pending") is None
    row = state_service.get_row("rec_pending")
    assert row is not None
    assert row.visibility.value == "public"


def test_reject_soft_requires_reason(signed_in_client):
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.post(
        "/api/admin/request/rec_pending/reject-soft",
        headers=_HEADERS,
        data=json.dumps({"reason": "short"}),
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/admin/request/<slug>/reject-hard
# ---------------------------------------------------------------------------


def test_reject_hard_contributor_returns_403(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    res = client.post(
        "/api/admin/request/rec_pending/reject-hard",
        headers=_HEADERS,
        data=json.dumps({"reason": "duplicate of another reciter"}),
    )
    assert res.status_code == 403


def test_reject_hard_maintainer_sets_discarded(signed_in_client):
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.post(
        "/api/admin/request/rec_pending/reject-hard",
        headers=_HEADERS,
        data=json.dumps({"reason": "duplicate of an already-published reciter"}),
    )
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["state"] == "catalogued"

    from services import state as state_service
    row = state_service.get_row("rec_pending")
    assert row is not None
    assert row.visibility.value == "discarded"
    assert row.visibility_reason == "duplicate of an already-published reciter"


def test_reject_hard_requires_reason(signed_in_client):
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.post(
        "/api/admin/request/rec_pending/reject-hard",
        headers=_HEADERS,
        data=json.dumps({"reason": "short"}),
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/admin/reciter/<slug>/undiscard
# ---------------------------------------------------------------------------


def test_undiscard_anonymous_returns_401(flask_client):
    res = flask_client.post(
        "/api/admin/reciter/rec_discarded/undiscard",
        headers=_HEADERS,
        data=json.dumps({"reason": "restoring per user request"}),
    )
    assert res.status_code == 401


def test_undiscard_maintainer_returns_403(signed_in_client):
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.post(
        "/api/admin/reciter/rec_discarded/undiscard",
        headers=_HEADERS,
        data=json.dumps({"reason": "restoring per user request"}),
    )
    assert res.status_code == 403


def test_undiscard_owner_happy_path(signed_in_client):
    client, _ = signed_in_client(role="owner", hf_user_id="u-O")
    res = client.post(
        "/api/admin/reciter/rec_discarded/undiscard",
        headers=_HEADERS,
        data=json.dumps({"reason": "restoring per user request"}),
    )
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["visibility"] == "public"

    from services import state as state_service
    row = state_service.get_row("rec_discarded")
    assert row is not None
    assert row.visibility.value == "public"


def test_undiscard_requires_reason(signed_in_client):
    client, _ = signed_in_client(role="owner", hf_user_id="u-O")
    res = client.post(
        "/api/admin/reciter/rec_discarded/undiscard",
        headers=_HEADERS,
        data=json.dumps({"reason": "short"}),
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/admin/reconcile (admin_reconcile_bp)
# ---------------------------------------------------------------------------


def test_reconcile_anonymous_returns_401(flask_client):
    res = flask_client.post("/api/admin/reconcile", headers=_HEADERS)
    assert res.status_code == 401


def test_reconcile_contributor_returns_403(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    res = client.post("/api/admin/reconcile", headers=_HEADERS)
    assert res.status_code == 403


def test_reconcile_maintainer_returns_count(signed_in_client, monkeypatch):
    """Stubbed: this exercises the route gate + that it calls into the reconciler,
    not the reconciler's behavior (covered in test_auto_detect)."""
    from services import auto_detect as auto_detect_service
    monkeypatch.setattr(auto_detect_service, "reconcile_once", lambda: 7)

    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.post("/api/admin/reconcile", headers=_HEADERS)
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["ok"] is True
    assert body["fired_count"] == 7
