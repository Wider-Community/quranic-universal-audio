"""Tests for the request-flow state-machine events:

- ``reciter.requested`` — user submits a request; CATALOGUED → AWAITING_ALIGNMENT
- ``reciter.request_rejected_soft`` — admin sends back; AWAITING_ALIGNMENT → CATALOGUED
- ``reciter.request_rejected_hard`` — admin discards; AWAITING_ALIGNMENT → CATALOGUED + visibility=DISCARDED
- ``reciter.alignment_completed`` — auto-detect or admin accepts; AWAITING_ALIGNMENT → AWAITING_REVIEW
  (applies any pending catalog edits in the same handler)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.lib.schemas import (
    Actor,
    AudioCategory,
    Channel,
    Delivery,
    ReciterCatalog,
    ReciterEntry,
    RecordingContext,
    ReciterRow,
    ReciterState,
    ReciterStateFile,
    Riwayah,
    Role,
    Source,
    Style,
    Visibility,
    Vocab,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _actor(role: str = "contributor", hf_user_id: str = "u-1") -> Actor:
    return Actor(hf_user_id=hf_user_id, login_at_time="alice", role=Role(role))


def _seed_catalog():
    """A small catalog with one CATALOGUED slug ready to be requested."""
    return ReciterCatalog(
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
            ],
        ),
        reciters=[
            ReciterEntry(reciter_id="test_reciter", name_en="Original Name"),
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
                added_at=datetime.now(timezone.utc),
                added_by_hf_id="seed",
            ),
        ],
    )


@pytest.fixture
def state_env(tmp_path, monkeypatch):
    """In-memory state + catalog + pending_requests, all hydrated against
    an empty FilesystemBackend rooted at ``tmp_path``."""
    from services import catalog as catalog_service
    from services import hf_bucket as _hf_bucket
    from services import pending_requests as pending_requests_service
    from services import state as state_service
    from services import storage_paths

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)

    # Seed the catalog.
    backend.write_json_atomic(
        storage_paths.catalog_path(),
        _seed_catalog().model_dump(mode="json"),
    )

    # Seed a CATALOGUED state row for test_reciter.
    rows = ReciterStateFile(
        reciters=[
            ReciterRow(
                slug="test_reciter",
                state=ReciterState.CATALOGUED,
                state_since=datetime.now(timezone.utc),
            ),
        ]
    )
    backend.write_json_atomic(
        storage_paths.state_path(), rows.model_dump(mode="json"),
    )

    catalog_service.hydrate()
    state_service.hydrate()
    pending_requests_service.hydrate()

    yield state_service, pending_requests_service, catalog_service, backend

    _hf_bucket.reset_backend()


# ---------------------------------------------------------------------------
# reciter.requested
# ---------------------------------------------------------------------------


def test_requested_happy_path(state_env, monkeypatch):
    state_service, pending_service, _, _ = state_env
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    state_service.transition(
        "test_reciter",
        "reciter.requested",
        actor=_actor(),
        payload={
            "proposed_edits": {"name_en": "Better Name", "recording_year": 2020},
            "comments": "Found a higher-quality recording.",
        },
    )

    row = state_service.get_row("test_reciter")
    assert row is not None
    assert row.state == ReciterState.AWAITING_ALIGNMENT

    pending = pending_service.get("test_reciter")
    assert pending is not None
    assert pending.proposed_edits.name_en == "Better Name"
    assert pending.proposed_edits.recording_year == 2020
    assert pending.comments == "Found a higher-quality recording."
    assert pending.requester.hf_user_id == "u-1"


def test_requested_creates_row_when_none_exists(state_env, monkeypatch):
    """Most-common path: catalog delivery has no state row yet. Request
    creates a fresh row in AWAITING_ALIGNMENT in one step."""
    state_service, pending_service, _, backend = state_env
    from services import audit as audit_service
    from services import storage_paths
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    # Wipe the state file so test_reciter has no row.
    backend.write_json_atomic(
        storage_paths.state_path(),
        ReciterStateFile().model_dump(mode="json"),
    )
    state_service.hydrate()
    assert state_service.get_row("test_reciter") is None

    state_service.transition(
        "test_reciter",
        "reciter.requested",
        actor=_actor(),
        payload={
            "proposed_edits": {"name_en": "Better"},
            "comments": None,
        },
    )
    row = state_service.get_row("test_reciter")
    assert row is not None
    assert row.state == ReciterState.AWAITING_ALIGNMENT

    pending = pending_service.get("test_reciter")
    assert pending is not None
    assert pending.proposed_edits.name_en == "Better"


def test_requested_rejects_non_catalogued(state_env, monkeypatch):
    state_service, _, _, backend = state_env
    from services import audit as audit_service
    from services import storage_paths
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    # Flip the row to AWAITING_REVIEW.
    rows = ReciterStateFile(
        reciters=[
            ReciterRow(
                slug="test_reciter",
                state=ReciterState.AWAITING_REVIEW,
                state_since=datetime.now(timezone.utc),
            ),
        ]
    )
    backend.write_json_atomic(
        storage_paths.state_path(), rows.model_dump(mode="json"),
    )
    state_service.hydrate()

    with pytest.raises(state_service.InvalidTransition):
        state_service.transition(
            "test_reciter",
            "reciter.requested",
            actor=_actor(),
            payload={"proposed_edits": {}, "comments": None},
        )


def test_requested_rejects_discarded_visibility(state_env, monkeypatch):
    state_service, _, _, backend = state_env
    from services import audit as audit_service
    from services import storage_paths
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    rows = ReciterStateFile(
        reciters=[
            ReciterRow(
                slug="test_reciter",
                state=ReciterState.CATALOGUED,
                state_since=datetime.now(timezone.utc),
                visibility=Visibility.DISCARDED,
                visibility_reason="testing",
            ),
        ]
    )
    backend.write_json_atomic(
        storage_paths.state_path(), rows.model_dump(mode="json"),
    )
    state_service.hydrate()

    with pytest.raises(state_service.InvalidTransition):
        state_service.transition(
            "test_reciter",
            "reciter.requested",
            actor=_actor(),
            payload={"proposed_edits": {}, "comments": None},
        )


def test_requested_rejects_when_pending_exists(state_env, monkeypatch):
    state_service, pending_service, _, _ = state_env
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    state_service.transition(
        "test_reciter",
        "reciter.requested",
        actor=_actor(),
        payload={"proposed_edits": {}, "comments": None},
    )
    # Second request for the same slug — row is no longer CATALOGUED,
    # so it fails on the state check rather than the pending check.
    with pytest.raises(state_service.InvalidTransition):
        state_service.transition(
            "test_reciter",
            "reciter.requested",
            actor=_actor(hf_user_id="u-2"),
            payload={"proposed_edits": {}, "comments": None},
        )


def test_requested_rejects_oversized_comments(state_env, monkeypatch):
    state_service, _, _, _ = state_env
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    with pytest.raises(state_service.InvalidTransition):
        state_service.transition(
            "test_reciter",
            "reciter.requested",
            actor=_actor(),
            payload={"proposed_edits": {}, "comments": "x" * 1001},
        )


def test_requested_rejects_bad_year_in_edits(state_env, monkeypatch):
    state_service, _, _, _ = state_env
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    with pytest.raises(state_service.InvalidTransition):
        state_service.transition(
            "test_reciter",
            "reciter.requested",
            actor=_actor(),
            payload={
                "proposed_edits": {"recording_year": 1700},
                "comments": None,
            },
        )


# ---------------------------------------------------------------------------
# reciter.request_rejected_soft
# ---------------------------------------------------------------------------


def _seed_awaiting_alignment_with_pending(state_env, monkeypatch):
    """Helper: put a slug into AWAITING_ALIGNMENT with a pending request."""
    state_service, pending_service, _, _ = state_env
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)
    state_service.transition(
        "test_reciter",
        "reciter.requested",
        actor=_actor(),
        payload={
            "proposed_edits": {"name_en": "New Name"},
            "comments": "hi",
        },
    )
    return state_service, pending_service


def test_reject_soft_happy_path(state_env, monkeypatch):
    state_service, pending_service = _seed_awaiting_alignment_with_pending(
        state_env, monkeypatch
    )
    assert pending_service.get("test_reciter") is not None

    state_service.transition(
        "test_reciter",
        "reciter.request_rejected_soft",
        actor=_actor(role="maintainer"),
        reason="not a priority right now",
    )
    row = state_service.get_row("test_reciter")
    assert row is not None
    assert row.state == ReciterState.CATALOGUED
    assert row.visibility == Visibility.PUBLIC
    assert pending_service.get("test_reciter") is None


def test_reject_soft_rejects_non_admin(state_env, monkeypatch):
    state_service, _ = _seed_awaiting_alignment_with_pending(state_env, monkeypatch)
    with pytest.raises(state_service.NotAuthorizedForTransition):
        state_service.transition(
            "test_reciter",
            "reciter.request_rejected_soft",
            actor=_actor(role="contributor"),
            reason="ten chars+",
        )


def test_reject_soft_requires_reason(state_env, monkeypatch):
    state_service, _ = _seed_awaiting_alignment_with_pending(state_env, monkeypatch)
    with pytest.raises(state_service.InvalidTransition):
        state_service.transition(
            "test_reciter",
            "reciter.request_rejected_soft",
            actor=_actor(role="maintainer"),
            reason="too short",
        )


def test_reject_soft_requires_awaiting_alignment(state_env, monkeypatch):
    state_service, _, _, _ = state_env
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    with pytest.raises(state_service.InvalidTransition):
        state_service.transition(
            "test_reciter",
            "reciter.request_rejected_soft",
            actor=_actor(role="maintainer"),
            reason="this is a perfectly valid reason",
        )


# ---------------------------------------------------------------------------
# reciter.request_rejected_hard
# ---------------------------------------------------------------------------


def test_reject_hard_happy_path(state_env, monkeypatch):
    state_service, pending_service = _seed_awaiting_alignment_with_pending(
        state_env, monkeypatch
    )

    state_service.transition(
        "test_reciter",
        "reciter.request_rejected_hard",
        actor=_actor(role="maintainer"),
        reason="duplicate of an already-published reciter",
    )
    row = state_service.get_row("test_reciter")
    assert row is not None
    assert row.state == ReciterState.CATALOGUED
    assert row.visibility == Visibility.DISCARDED
    assert row.visibility_reason == "duplicate of an already-published reciter"
    assert pending_service.get("test_reciter") is None


def test_reject_hard_rejects_non_admin(state_env, monkeypatch):
    state_service, _ = _seed_awaiting_alignment_with_pending(state_env, monkeypatch)
    with pytest.raises(state_service.NotAuthorizedForTransition):
        state_service.transition(
            "test_reciter",
            "reciter.request_rejected_hard",
            actor=_actor(role="contributor"),
            reason="ten chars+ reason",
        )


def test_reject_hard_requires_reason(state_env, monkeypatch):
    state_service, _ = _seed_awaiting_alignment_with_pending(state_env, monkeypatch)
    with pytest.raises(state_service.InvalidTransition):
        state_service.transition(
            "test_reciter",
            "reciter.request_rejected_hard",
            actor=_actor(role="maintainer"),
            reason="short",
        )


# ---------------------------------------------------------------------------
# reciter.alignment_completed — extended to apply pending edits
# ---------------------------------------------------------------------------


def test_alignment_completed_applies_pending_edits(state_env, monkeypatch):
    state_service, pending_service, catalog_service, _ = state_env
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    # User submits a request with proposed edits.
    state_service.transition(
        "test_reciter",
        "reciter.requested",
        actor=_actor(),
        payload={
            "proposed_edits": {
                "name_en": "Approved Name",
                "country": "EG",
                "recording_year": 2022,
            },
            "comments": None,
        },
    )
    # System actor fires alignment_completed.
    system_actor = Actor(
        hf_user_id="system", login_at_time="system", role=Role.OWNER,
    )
    state_service.transition(
        "test_reciter",
        "reciter.alignment_completed",
        actor=system_actor,
    )

    row = state_service.get_row("test_reciter")
    assert row is not None
    assert row.state == ReciterState.AWAITING_REVIEW

    reciter = catalog_service.find_reciter("test_reciter")
    assert reciter is not None
    assert reciter.name_en == "Approved Name"
    assert reciter.country == "EG"

    delivery = catalog_service.find_delivery("test_reciter")
    assert delivery is not None
    assert delivery.recording_year == 2022
    assert pending_service.get("test_reciter") is None


def test_alignment_completed_noop_when_no_pending(state_env, monkeypatch):
    state_service, _, _, backend = state_env
    from services import audit as audit_service
    from services import storage_paths
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    # Move the row to AWAITING_ALIGNMENT without a pending entry (e.g. admin
    # force-set state).
    rows = ReciterStateFile(
        reciters=[
            ReciterRow(
                slug="test_reciter",
                state=ReciterState.AWAITING_ALIGNMENT,
                state_since=datetime.now(timezone.utc),
            ),
        ]
    )
    backend.write_json_atomic(
        storage_paths.state_path(), rows.model_dump(mode="json"),
    )
    state_service.hydrate()

    system_actor = Actor(
        hf_user_id="system", login_at_time="system", role=Role.OWNER,
    )
    state_service.transition(
        "test_reciter",
        "reciter.alignment_completed",
        actor=system_actor,
    )
    row = state_service.get_row("test_reciter")
    assert row is not None
    assert row.state == ReciterState.AWAITING_REVIEW
