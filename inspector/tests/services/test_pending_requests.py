"""Tests for ``services/pending_requests`` — the 6th bucket store.

Same hydrate / snapshot / write-through pattern as the existing four,
plus an ``apply_and_clear`` method that applies the user's proposed
edits to the catalog at auto-acceptance time.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.lib.schemas import (
    Actor,
    PendingRequest,
    ProposedEdits,
    Role,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_pending(tmp_path, monkeypatch):
    """Per-test FilesystemBackend so each test starts with a clean store."""
    from services import hf_bucket as _hf_bucket
    from services import pending_requests as pending_requests_service

    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))

    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)
    pending_requests_service.hydrate()

    yield pending_requests_service, backend

    _hf_bucket.reset_backend()


def _actor(hf_user_id: str = "u-1", login: str = "alice", role: str = "contributor") -> Actor:
    return Actor(hf_user_id=hf_user_id, login_at_time=login, role=Role(role))


def _edits(**kwargs) -> ProposedEdits:
    return ProposedEdits(**kwargs)


# ---------------------------------------------------------------------------
# Hydrate
# ---------------------------------------------------------------------------


def test_hydrate_empty_when_no_file(fresh_pending):
    svc, _ = fresh_pending
    snap = svc.snapshot()
    assert snap.by_slug == {}


def test_hydrate_loads_existing_file(tmp_path, monkeypatch):
    from services import hf_bucket as _hf_bucket
    from services import pending_requests as svc
    from services import storage_paths

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)

    seed = {
        "by_slug": {
            "test_reciter": {
                "slug": "test_reciter",
                "submitted_at": "2026-01-01T00:00:00+00:00",
                "requester": {
                    "hf_user_id": "u-1",
                    "login_at_time": "alice",
                    "role": "contributor",
                },
                "proposed_edits": {"name_en": "Updated"},
                "comments": None,
            }
        }
    }
    backend.write_json_atomic(storage_paths.pending_requests_path(), seed)
    svc.hydrate()
    snap = svc.snapshot()
    assert "test_reciter" in snap.by_slug
    assert snap.by_slug["test_reciter"].requester.hf_user_id == "u-1"
    _hf_bucket.reset_backend()


# ---------------------------------------------------------------------------
# submit / get / clear
# ---------------------------------------------------------------------------


def test_submit_creates_entry(fresh_pending):
    svc, backend = fresh_pending
    from services import storage_paths

    svc.submit(
        "test_reciter",
        requester=_actor(),
        edits=_edits(name_en="Updated", recording_year=2020),
        comments="some comments",
    )
    snap = svc.snapshot()
    assert "test_reciter" in snap.by_slug
    entry = snap.by_slug["test_reciter"]
    assert entry.requester.hf_user_id == "u-1"
    assert entry.proposed_edits.name_en == "Updated"
    assert entry.proposed_edits.recording_year == 2020
    assert entry.comments == "some comments"

    raw = backend.read_json(storage_paths.pending_requests_path())
    assert "test_reciter" in raw["by_slug"]


def test_submit_rejects_when_pending_exists(fresh_pending):
    svc, _ = fresh_pending
    svc.submit("test_reciter", requester=_actor(), edits=_edits(), comments=None)
    with pytest.raises(svc.RequestAlreadyPending):
        svc.submit("test_reciter", requester=_actor(), edits=_edits(), comments=None)


def test_get_returns_entry_or_none(fresh_pending):
    svc, _ = fresh_pending
    assert svc.get("nope") is None
    svc.submit("test_reciter", requester=_actor(), edits=_edits(), comments=None)
    entry = svc.get("test_reciter")
    assert entry is not None
    assert entry.slug == "test_reciter"


def test_clear_removes_entry(fresh_pending):
    svc, _ = fresh_pending
    svc.submit("test_reciter", requester=_actor(), edits=_edits(), comments=None)
    svc.clear("test_reciter")
    assert svc.get("test_reciter") is None


def test_clear_is_idempotent(fresh_pending):
    svc, _ = fresh_pending
    svc.clear("nope")  # never existed
    svc.submit("test_reciter", requester=_actor(), edits=_edits(), comments=None)
    svc.clear("test_reciter")
    svc.clear("test_reciter")  # twice
    assert svc.get("test_reciter") is None


# ---------------------------------------------------------------------------
# apply_and_clear
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_catalog(fresh_pending, monkeypatch):
    """Install a small catalog so apply_and_clear has something to patch."""
    from datetime import datetime as _dt, timezone as _tz

    from scripts.lib.schemas import (
        AudioCategory,
        Channel,
        Delivery,
        ReciterCatalog,
        ReciterEntry,
        RecordingContext,
        Riwayah,
        Source,
        Style,
        Vocab,
    )
    from services import catalog as catalog_service
    from services import hf_bucket as _hf_bucket
    from services import storage_paths

    catalog = ReciterCatalog(
        vocab=Vocab(
            riwayat=[
                Riwayah(slug="hafs", short="H", name="Hafs"),
                Riwayah(slug="warsh", short="W", name="Warsh"),
            ],
            styles=[
                Style(slug="murattal", short="M", name="Murattal"),
                Style(slug="mujawwad", short="J", name="Mujawwad"),
            ],
            sources=[Source(slug="src1", name="Source One")],
            channels=[Channel(slug="ch1", short="c1", name="Channel One")],
            recording_contexts=[
                RecordingContext(slug="studio", name="Studio"),
                RecordingContext(slug="broadcast", name="Broadcast"),
            ],
        ),
        reciters=[
            ReciterEntry(
                reciter_id="test_reciter",
                name_en="Original Name",
                name_ar=None,
                country=None,
            ),
        ],
        deliveries=[
            Delivery(
                slug="test_reciter",
                reciter_id="test_reciter",
                riwayah="hafs",
                style="murattal",
                recording_context="studio",
                recording_year=2010,
                source="src1",
                channel="ch1",
                audio_category=AudioCategory.BY_SURAH,
                chapter_count=114,
                added_at=_dt.now(_tz.utc),
                added_by_hf_id="seed",
            ),
        ],
    )
    backend = _hf_bucket.get_backend()
    backend.write_json_atomic(
        storage_paths.catalog_path(), catalog.model_dump(mode="json"),
    )
    catalog_service.hydrate()
    return fresh_pending


def test_apply_and_clear_applies_reciter_fields(seeded_catalog, monkeypatch):
    svc, _ = seeded_catalog
    from services import audit as audit_service
    from services import catalog as catalog_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    svc.submit(
        "test_reciter",
        requester=_actor(),
        edits=_edits(name_en="New Name", country="SA"),
        comments=None,
    )

    actor = _actor(hf_user_id="system", login="system", role="owner")
    svc.apply_and_clear("test_reciter", actor=actor)

    reciter = catalog_service.find_reciter("test_reciter")
    assert reciter is not None
    assert reciter.name_en == "New Name"
    assert reciter.country == "SA"
    assert svc.get("test_reciter") is None


def test_apply_and_clear_applies_delivery_fields(seeded_catalog, monkeypatch):
    svc, _ = seeded_catalog
    from services import audit as audit_service
    from services import catalog as catalog_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    svc.submit(
        "test_reciter",
        requester=_actor(),
        edits=_edits(
            riwayah="warsh",
            style="mujawwad",
            recording_context="broadcast",
            recording_year=2020,
        ),
        comments=None,
    )

    actor = _actor(hf_user_id="system", login="system", role="owner")
    svc.apply_and_clear("test_reciter", actor=actor)

    delivery = catalog_service.find_delivery("test_reciter")
    assert delivery is not None
    assert delivery.riwayah == "warsh"
    assert delivery.style == "mujawwad"
    assert delivery.recording_context == "broadcast"
    assert delivery.recording_year == 2020
    assert svc.get("test_reciter") is None


def test_apply_and_clear_noop_when_no_pending(seeded_catalog, monkeypatch):
    svc, _ = seeded_catalog
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    actor = _actor(hf_user_id="system", login="system", role="owner")
    svc.apply_and_clear("test_reciter", actor=actor)  # no entry; should not raise
    assert svc.get("test_reciter") is None


def test_apply_and_clear_with_empty_edits_just_clears(seeded_catalog, monkeypatch):
    """Submission with no proposed edits should still be cleared on accept."""
    svc, _ = seeded_catalog
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    svc.submit("test_reciter", requester=_actor(), edits=_edits(), comments="hi")
    actor = _actor(hf_user_id="system", login="system", role="owner")
    svc.apply_and_clear("test_reciter", actor=actor)
    assert svc.get("test_reciter") is None


def test_apply_and_clear_warns_on_riwayah_style_conflict(seeded_catalog, monkeypatch):
    """Proposed (riwayah, style) matching another delivery of the same reciter
    emits a non-blocking audit warning. The edit still applies and clears."""
    svc, _ = seeded_catalog
    from datetime import datetime as _dt, timezone as _tz

    from scripts.lib.schemas import AudioCategory, Delivery
    from services import audit as audit_service
    from services import catalog as catalog_service

    calls: list[dict] = []
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: calls.append(kw))

    # Seed a second delivery for the same reciter so a conflict is possible.
    actor = _actor(hf_user_id="system", login="system", role="owner")
    catalog_service.add_delivery(
        actor=actor,
        delivery=Delivery(
            slug="test_reciter_warsh",
            reciter_id="test_reciter",
            riwayah="warsh",
            style="mujawwad",
            source="src1",
            channel="ch1",
            audio_category=AudioCategory.BY_SURAH,
            chapter_count=114,
            added_at=_dt.now(_tz.utc),
            added_by_hf_id="seed",
        ),
    )
    calls.clear()

    svc.submit(
        "test_reciter",
        requester=_actor(),
        edits=_edits(riwayah="warsh", style="mujawwad"),  # conflicts with the new row
        comments=None,
    )
    svc.apply_and_clear("test_reciter", actor=actor)

    events = [c["event"] for c in calls]
    assert "catalog.conflict_warning" in events
    assert svc.get("test_reciter") is None


# ---------------------------------------------------------------------------
# reconcile_with_state
# ---------------------------------------------------------------------------


def test_reconcile_with_state_drops_entries_past_awaiting_alignment(
    fresh_pending, monkeypatch
):
    """Entry whose state row already advanced (e.g. crashed clear after
    state persisted) must be dropped — that's the user-reported bug.
    """
    from datetime import datetime as _dt, timezone as _tz

    from scripts.lib.schemas import ReciterRow, ReciterState
    from services import pending_requests as svc_module
    from services import state as state_service

    svc, backend = fresh_pending
    svc.submit("test_reciter", requester=_actor(), edits=_edits(), comments=None)

    fake_row = ReciterRow(
        slug="test_reciter",
        state=ReciterState.AWAITING_REVIEW,
        state_since=_dt.now(_tz.utc),
    )
    monkeypatch.setattr(state_service, "get_row", lambda slug: fake_row if slug == "test_reciter" else None)

    dropped = svc_module.reconcile_with_state()
    assert dropped == 1
    assert svc.get("test_reciter") is None

    # Persisted to disk, not just in-memory.
    from services import storage_paths
    raw = backend.read_json(storage_paths.pending_requests_path())
    assert "test_reciter" not in raw["by_slug"]


def test_reconcile_with_state_keeps_awaiting_alignment_entries(
    fresh_pending, monkeypatch
):
    """Active requests (state == AWAITING_ALIGNMENT) must NOT be touched."""
    from scripts.lib.schemas import ReciterRow, ReciterState
    from services import pending_requests as svc_module
    from services import state as state_service

    svc, _ = fresh_pending
    svc.submit("active_reciter", requester=_actor(), edits=_edits(), comments=None)

    from datetime import datetime as _dt, timezone as _tz

    fake_row = ReciterRow(
        slug="active_reciter",
        state=ReciterState.AWAITING_ALIGNMENT,
        state_since=_dt.now(_tz.utc),
    )
    monkeypatch.setattr(state_service, "get_row", lambda slug: fake_row)

    dropped = svc_module.reconcile_with_state()
    assert dropped == 0
    assert svc.get("active_reciter") is not None


def test_reconcile_with_state_drops_entries_with_no_state_row(
    fresh_pending, monkeypatch
):
    """No state row at all → orphan (the request was submitted but the row
    was deleted out from under it somehow). Drop it.
    """
    from services import pending_requests as svc_module
    from services import state as state_service

    svc, _ = fresh_pending
    svc.submit("ghost_reciter", requester=_actor(), edits=_edits(), comments=None)

    monkeypatch.setattr(state_service, "get_row", lambda slug: None)

    dropped = svc_module.reconcile_with_state()
    assert dropped == 1
    assert svc.get("ghost_reciter") is None


def test_reconcile_with_state_is_noop_when_clean(fresh_pending, monkeypatch):
    """No orphans means no disk write."""
    from services import pending_requests as svc_module
    from services import state as state_service

    svc, _ = fresh_pending
    monkeypatch.setattr(state_service, "get_row", lambda slug: None)
    assert svc_module.reconcile_with_state() == 0
    assert svc.snapshot().by_slug == {}
