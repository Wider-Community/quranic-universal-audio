"""Tests for ``services/pending_requests`` — the 6th bucket store.

Same hydrate / snapshot / write-through pattern as the existing four,
plus an ``apply_and_archive_completed`` method that applies the user's proposed
edits to the catalog at auto-acceptance time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone

import pytest

from qua_shared.schemas import (
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
    from services import request_archive as request_archive_service

    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))

    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)
    # requests.slug FK → deliveries: seed the catalog (vocab + reciter +
    # delivery) the submit + apply_and_archive tests use.
    _seed_test_catalog_db()

    yield pending_requests_service, backend

    _hf_bucket.reset_backend()


def _seed_test_catalog_db():
    """Seed the test catalog (rich vocab + ``test_reciter`` delivery) into the
    SQLite substrate so submit (FK) + apply_and_archive (edits) both work."""
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    from qua_shared.schemas import (
        AudioCategory,
        Channel,
        Delivery,
        ReciterEntry,
        RecordingContext,
        Riwayah,
        Source,
        Style,
        Vocab,
    )
    from services import db
    from services.db import repo_catalog

    vocab = Vocab(
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
    )
    with db.transaction():
        repo_catalog.load_vocab(vocab)
        repo_catalog.insert_reciter(
            ReciterEntry(
                reciter_id="test_reciter",
                name_en="Original Name",
                name_ar=None,
                country=None,
            )
        )
        repo_catalog.insert_delivery(
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
                added_at=_dt.now(UTC),
                added_by_hf_id="seed",
            )
        )


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


# (Removed test_hydrate_loads_existing_file: pending.json bucket hydrate no
# longer exists — the substrate DB is the source of truth.)


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
# apply_and_archive_completed
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_catalog(fresh_pending, monkeypatch):
    """The catalog is already seeded by ``fresh_pending`` (``_seed_test_catalog_db``);
    apply_and_archive_completed has the ``test_reciter`` delivery + vocab to patch."""
    return fresh_pending


def _system_actor() -> Actor:
    return _actor(hf_user_id="system", login="system", role="owner")


def _completed_for(svc_request_archive, slug: str):
    return svc_request_archive.get_for_slug(
        slug,
        svc_request_archive.ArchiveKind.COMPLETED,
    )


def _returned_for(svc_request_archive, slug: str):
    return svc_request_archive.get_for_slug(
        slug,
        svc_request_archive.ArchiveKind.RETURNED,
    )


def _discarded_for(svc_request_archive, slug: str):
    return svc_request_archive.get_for_slug(
        slug,
        svc_request_archive.ArchiveKind.DISCARDED,
    )


def test_apply_and_archive_completed_applies_reciter_fields(seeded_catalog, monkeypatch):
    svc, _ = seeded_catalog
    from services import audit as audit_service
    from services import catalog as catalog_service
    from services import request_archive as request_archive_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    svc.submit(
        "test_reciter",
        requester=_actor(),
        edits=_edits(name_en="New Name", country="SA"),
        comments=None,
    )

    actor = _system_actor()
    svc.apply_and_archive_completed("test_reciter", actor=actor)

    reciter = catalog_service.find_reciter("test_reciter")
    assert reciter is not None
    assert reciter.name_en == "New Name"
    assert reciter.country == "SA"
    assert svc.get("test_reciter") is None

    archived = _completed_for(request_archive_service, "test_reciter")
    assert len(archived) == 1
    entry = archived[0]
    assert entry.proposed_edits.name_en == "New Name"
    assert entry.transitioned_by.hf_user_id == "system"
    assert entry.reason is None
    assert entry.archived_at is not None


def test_apply_and_archive_completed_applies_delivery_fields(seeded_catalog, monkeypatch):
    svc, _ = seeded_catalog
    from services import audit as audit_service
    from services import catalog as catalog_service
    from services import request_archive as request_archive_service

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

    actor = _system_actor()
    svc.apply_and_archive_completed("test_reciter", actor=actor)

    delivery = catalog_service.find_delivery("test_reciter")
    assert delivery is not None
    assert delivery.riwayah == "warsh"
    assert delivery.style == "mujawwad"
    assert delivery.recording_context == "broadcast"
    assert delivery.recording_year == 2020
    assert svc.get("test_reciter") is None
    assert len(_completed_for(request_archive_service, "test_reciter")) == 1


def test_apply_and_archive_completed_noop_when_no_pending(seeded_catalog, monkeypatch):
    svc, _ = seeded_catalog
    from services import audit as audit_service
    from services import request_archive as request_archive_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    actor = _system_actor()
    svc.apply_and_archive_completed("test_reciter", actor=actor)  # no entry
    assert svc.get("test_reciter") is None
    assert _completed_for(request_archive_service, "test_reciter") == []


def test_apply_and_archive_completed_with_empty_edits_still_archives(seeded_catalog, monkeypatch):
    """Submission with no proposed edits is still archived on accept."""
    svc, _ = seeded_catalog
    from services import audit as audit_service
    from services import request_archive as request_archive_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    svc.submit("test_reciter", requester=_actor(), edits=_edits(), comments="hi")
    actor = _system_actor()
    svc.apply_and_archive_completed("test_reciter", actor=actor)
    assert svc.get("test_reciter") is None
    archived = _completed_for(request_archive_service, "test_reciter")
    assert len(archived) == 1
    assert archived[0].comments == "hi"


def test_apply_and_archive_completed_warns_on_riwayah_style_conflict(seeded_catalog, monkeypatch):
    """Proposed (riwayah, style) matching another delivery of the same reciter
    emits a non-blocking audit warning. The edit still applies and archives."""
    svc, _ = seeded_catalog
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    from qua_shared.schemas import AudioCategory, Delivery
    from services import audit as audit_service
    from services import catalog as catalog_service
    from services import request_archive as request_archive_service

    calls: list[dict] = []
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: calls.append(kw))

    actor = _system_actor()
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
            added_at=_dt.now(UTC),
            added_by_hf_id="seed",
        ),
    )
    calls.clear()

    svc.submit(
        "test_reciter",
        requester=_actor(),
        edits=_edits(riwayah="warsh", style="mujawwad"),
        comments=None,
    )
    svc.apply_and_archive_completed("test_reciter", actor=actor)

    events = [c["event"] for c in calls]
    assert "catalog.conflict_warning" in events
    assert svc.get("test_reciter") is None
    assert len(_completed_for(request_archive_service, "test_reciter")) == 1


# ---------------------------------------------------------------------------
# archive_returned / archive_discarded
# ---------------------------------------------------------------------------


def test_archive_returned_moves_pending_into_returned(fresh_pending):
    svc, _ = fresh_pending
    from services import request_archive as request_archive_service

    svc.submit(
        "test_reciter",
        requester=_actor(),
        edits=_edits(name_en="Proposed Name"),
        comments="please fix the name",
    )

    admin = _actor(hf_user_id="admin-1", login="admin", role="maintainer")
    svc.archive_returned(
        "test_reciter",
        reason="please clarify the recording context",
        by_actor=admin,
    )

    assert svc.get("test_reciter") is None
    archived = _returned_for(request_archive_service, "test_reciter")
    assert len(archived) == 1
    entry = archived[0]
    assert entry.proposed_edits.name_en == "Proposed Name"
    assert entry.comments == "please fix the name"
    assert entry.reason == "please clarify the recording context"
    assert entry.transitioned_by.hf_user_id == "admin-1"


def test_archive_returned_noop_when_no_pending(fresh_pending):
    svc, _ = fresh_pending
    from services import request_archive as request_archive_service

    admin = _actor(hf_user_id="admin-1", login="admin", role="maintainer")
    svc.archive_returned("nonexistent", reason="x" * 10, by_actor=admin)
    assert _returned_for(request_archive_service, "nonexistent") == []


def test_archive_returned_then_resubmit_keeps_history(fresh_pending):
    """A slug can be returned, re-requested, returned again — both archive
    entries should be preserved in chronological order."""
    svc, _ = fresh_pending
    from services import request_archive as request_archive_service

    admin = _actor(hf_user_id="admin-1", login="admin", role="maintainer")

    svc.submit("test_reciter", requester=_actor(), edits=_edits(name_en="V1"), comments=None)
    svc.archive_returned("test_reciter", reason="reason one  ", by_actor=admin)

    svc.submit("test_reciter", requester=_actor(), edits=_edits(name_en="V2"), comments=None)
    svc.archive_returned("test_reciter", reason="reason two  ", by_actor=admin)

    archived = _returned_for(request_archive_service, "test_reciter")
    assert len(archived) == 2
    assert archived[0].proposed_edits.name_en == "V1"
    assert archived[1].proposed_edits.name_en == "V2"


def test_archive_discarded_moves_pending_into_discarded(fresh_pending):
    svc, _ = fresh_pending
    from services import request_archive as request_archive_service

    svc.submit(
        "test_reciter",
        requester=_actor(),
        edits=_edits(name_en="Discard me"),
        comments=None,
    )

    admin = _actor(hf_user_id="admin-1", login="admin", role="maintainer")
    svc.archive_discarded(
        "test_reciter",
        reason="duplicate of an existing delivery",
        by_actor=admin,
    )

    assert svc.get("test_reciter") is None
    archived = _discarded_for(request_archive_service, "test_reciter")
    assert len(archived) == 1
    entry = archived[0]
    assert entry.reason == "duplicate of an existing delivery"
    assert entry.transitioned_by.hf_user_id == "admin-1"


def test_archive_discarded_noop_when_no_pending(fresh_pending):
    svc, _ = fresh_pending
    from services import request_archive as request_archive_service

    admin = _actor(hf_user_id="admin-1", login="admin", role="maintainer")
    svc.archive_discarded("nonexistent", reason="x" * 10, by_actor=admin)
    assert _discarded_for(request_archive_service, "nonexistent") == []
