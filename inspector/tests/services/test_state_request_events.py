"""Tests for the request-flow state-machine events:

- ``reciter.requested`` — user submits a request; CATALOGUED → AWAITING_ALIGNMENT
- ``reciter.request_rejected_soft`` — admin sends back; AWAITING_ALIGNMENT → CATALOGUED
- ``reciter.request_rejected_hard`` — admin discards; AWAITING_ALIGNMENT → CATALOGUED + visibility=DISCARDED
- ``reciter.alignment_completed`` — auto-detect or admin accepts; AWAITING_ALIGNMENT → AWAITING_REVIEW
  (applies any pending catalog edits in the same handler)
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone

import pytest

from qua_shared.schemas import (
    Actor,
    AudioCategory,
    Channel,
    Delivery,
    ReciterCatalog,
    ReciterEntry,
    ReciterState,
    RecordingContext,
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


def _record_and_call_through(monkeypatch) -> list[dict]:
    """Record audit.append calls + pass them through to the real implementation
    so the durability boundary still writes to ``repo_transitions``. A pure
    no-op stub would lose the regression-guard on emission entirely.
    """
    from services import audit as audit_service

    calls: list[dict] = []
    real = audit_service.append

    def _capture(*a, **kw):
        calls.append(kw if not a else {"args": a, "kwargs": kw})
        return real(*a, **kw)

    monkeypatch.setattr(audit_service, "append", _capture)
    return calls


def _seed_catalog_db():
    """Seed the small test catalog into the SQLite substrate."""
    from services import db
    from services.db import repo_catalog

    cat = _seed_catalog()
    with db.transaction():
        repo_catalog.load_vocab(cat.vocab)
        for r in cat.reciters:
            repo_catalog.insert_reciter(r)
        for d in cat.deliveries:
            repo_catalog.insert_delivery(d)


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
                added_at=datetime.now(UTC),
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

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)

    # Seed the catalog + a CATALOGUED state row for test_reciter into the DB.
    _seed_catalog_db()
    from tests.conftest import _seed_state

    _seed_state("test_reciter", state="catalogued", reciter_id="test_reciter")

    yield state_service, pending_requests_service, catalog_service, backend

    _hf_bucket.reset_backend()


# ---------------------------------------------------------------------------
# reciter.requested
# ---------------------------------------------------------------------------


def test_requested_happy_path(state_env, monkeypatch):
    """Drives the canonical happy path and pins both the in-memory pending
    state and the durability boundary on `repo_transitions`. The transition
    row in SQLite is the source of truth — a no-op audit stub used elsewhere
    in this file would let a handler regression that drops the transition
    write slip through, so we read repo_transitions back directly here."""
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

    from services.db import repo_transitions

    events = {t["event"] for t in repo_transitions.for_slug("test_reciter")}
    assert "reciter.requested" in events


def test_requested_creates_row_when_none_exists(state_env, monkeypatch):
    """Most-common path: catalog delivery has no state row yet. Request
    creates a fresh row in AWAITING_ALIGNMENT in one step."""
    state_service, pending_service, _, backend = state_env
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    # Drop the seeded row so test_reciter has no delivery_state.
    from services import db as _db

    with _db.transaction() as _c:
        _c.execute("DELETE FROM delivery_states WHERE slug = 'test_reciter'")
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

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    # Flip the row to AWAITING_REVIEW.
    from tests.conftest import _seed_state

    _seed_state("test_reciter", state="awaiting_review", reciter_id="test_reciter")

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

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    from tests.conftest import _seed_state

    _seed_state(
        "test_reciter",
        state="catalogued",
        visibility="discarded",
        visibility_reason="testing",
        reciter_id="test_reciter",
    )

    with pytest.raises(state_service.InvalidTransition):
        state_service.transition(
            "test_reciter",
            "reciter.requested",
            actor=_actor(),
            payload={"proposed_edits": {}, "comments": None},
        )


def test_requested_rejects_when_pending_exists(state_env, monkeypatch):
    """Exercise the pending-check guard in ``_h_requested``: the row is back at
    CATALOGUED but a pending entry already exists — the second request must
    fail on the pending-check, not the state precondition.
    """
    state_service, pending_service, _, _ = state_env
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    state_service.transition(
        "test_reciter",
        "reciter.requested",
        actor=_actor(),
        payload={"proposed_edits": {}, "comments": None},
    )

    # Force the row back to CATALOGUED while leaving the pending entry alive,
    # isolating the pending-check guard from the state precondition.
    from services import db
    from services.db import repo_state

    with db.transaction():
        repo_state.update_state(
            "test_reciter",
            state=ReciterState.CATALOGUED,
            state_since=datetime.now(UTC),
        )
    assert pending_service.get("test_reciter") is not None

    with pytest.raises(state_service.InvalidTransition, match="pending request"):
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
    state_service, pending_service = _seed_awaiting_alignment_with_pending(state_env, monkeypatch)
    assert pending_service.get("test_reciter") is not None

    state_service.transition(
        "test_reciter",
        "reciter.request_rejected_soft",
        actor=_actor(role="owner"),
        reason="not a priority right now",
    )
    row = state_service.get_row("test_reciter")
    assert row is not None
    assert row.state == ReciterState.CATALOGUED
    assert row.visibility == Visibility.PUBLIC
    assert pending_service.get("test_reciter") is None

    # Archive: entry moves into returned.json with reason + admin actor.
    from services import request_archive as request_archive_service

    archived = request_archive_service.get_for_slug(
        "test_reciter",
        request_archive_service.ArchiveKind.RETURNED,
    )
    assert len(archived) == 1
    assert archived[0].reason == "not a priority right now"
    assert archived[0].proposed_edits.name_en == "New Name"
    assert archived[0].transitioned_by.role == "owner"


def test_reject_soft_rejects_non_owner(state_env, monkeypatch):
    """Send-back is owner-only — both contributors and maintainers are denied."""
    state_service, _ = _seed_awaiting_alignment_with_pending(state_env, monkeypatch)
    for role in ("contributor", "maintainer"):
        with pytest.raises(state_service.NotAuthorizedForTransition):
            state_service.transition(
                "test_reciter",
                "reciter.request_rejected_soft",
                actor=_actor(role=role),
                reason="ten chars+ reason",
            )


def test_reject_soft_requires_reason(state_env, monkeypatch):
    state_service, _ = _seed_awaiting_alignment_with_pending(state_env, monkeypatch)
    with pytest.raises(state_service.InvalidTransition):
        state_service.transition(
            "test_reciter",
            "reciter.request_rejected_soft",
            actor=_actor(role="owner"),
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
            actor=_actor(role="owner"),
            reason="this is a perfectly valid reason",
        )


# ---------------------------------------------------------------------------
# reciter.request_rejected_hard
# ---------------------------------------------------------------------------


def test_reject_hard_happy_path(state_env, monkeypatch):
    state_service, pending_service = _seed_awaiting_alignment_with_pending(state_env, monkeypatch)

    state_service.transition(
        "test_reciter",
        "reciter.request_rejected_hard",
        actor=_actor(role="owner"),
        reason="duplicate of an already-published reciter",
    )
    row = state_service.get_row("test_reciter")
    assert row is not None
    assert row.state == ReciterState.CATALOGUED
    assert row.visibility == Visibility.DISCARDED
    assert row.visibility_reason == "duplicate of an already-published reciter"
    assert pending_service.get("test_reciter") is None

    from services import request_archive as request_archive_service

    archived = request_archive_service.get_for_slug(
        "test_reciter",
        request_archive_service.ArchiveKind.DISCARDED,
    )
    assert len(archived) == 1
    assert archived[0].reason == "duplicate of an already-published reciter"
    assert archived[0].transitioned_by.role == "owner"


def test_reject_hard_rejects_non_owner(state_env, monkeypatch):
    """Discard is owner-only — both contributors and maintainers are denied."""
    state_service, _ = _seed_awaiting_alignment_with_pending(state_env, monkeypatch)
    for role in ("contributor", "maintainer"):
        with pytest.raises(state_service.NotAuthorizedForTransition):
            state_service.transition(
                "test_reciter",
                "reciter.request_rejected_hard",
                actor=_actor(role=role),
                reason="ten chars+ reason",
            )


def test_reject_hard_requires_reason(state_env, monkeypatch):
    state_service, _ = _seed_awaiting_alignment_with_pending(state_env, monkeypatch)
    with pytest.raises(state_service.InvalidTransition):
        state_service.transition(
            "test_reciter",
            "reciter.request_rejected_hard",
            actor=_actor(role="owner"),
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
        hf_user_id="system",
        login_at_time="system",
        role=Role.OWNER,
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

    from services import request_archive as request_archive_service

    archived = request_archive_service.get_for_slug(
        "test_reciter",
        request_archive_service.ArchiveKind.COMPLETED,
    )
    assert len(archived) == 1
    assert archived[0].proposed_edits.name_en == "Approved Name"
    assert archived[0].reason is None
    assert archived[0].transitioned_by.hf_user_id == "system"


def test_alignment_completed_auto_claims_when_flag_set(state_env, monkeypatch):
    """auto_claim=True: alignment_completed fires a follow-up reciter.claimed
    on the requester's behalf, landing the row in UNDER_REVIEW."""
    state_service, _, _, _ = state_env
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    requester = _actor(hf_user_id="u-req", role="contributor")
    state_service.transition(
        "test_reciter",
        "reciter.requested",
        actor=requester,
        payload={"proposed_edits": {}, "comments": None, "auto_claim": True},
    )

    system = Actor(hf_user_id="system", login_at_time="system", role=Role.OWNER)
    state_service.transition(
        "test_reciter",
        "reciter.alignment_completed",
        actor=system,
    )

    row = state_service.get_row("test_reciter")
    assert row is not None
    assert row.state == ReciterState.UNDER_REVIEW
    assert row.assignee_hf_id == "u-req"


def test_alignment_completed_skips_auto_claim_when_flag_unset(state_env, monkeypatch):
    """Default behavior: no auto_claim, row sits in AWAITING_REVIEW for a
    contributor to pick up."""
    state_service, _, _, _ = state_env
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    state_service.transition(
        "test_reciter",
        "reciter.requested",
        actor=_actor(role="contributor"),
        payload={"proposed_edits": {}, "comments": None},
    )
    system = Actor(hf_user_id="system", login_at_time="system", role=Role.OWNER)
    state_service.transition(
        "test_reciter",
        "reciter.alignment_completed",
        actor=system,
    )
    row = state_service.get_row("test_reciter")
    assert row is not None
    assert row.state == ReciterState.AWAITING_REVIEW
    assert row.assignee_hf_id is None


def test_alignment_completed_skips_auto_claim_when_other_claim_held(state_env):
    """auto_claim=True but requester already holds another active claim:
    skip silently, row stays in AWAITING_REVIEW for someone else to grab.
    A ``reciter.auto_claim_skipped`` audit record is written so the skip
    is forensically inspectable."""
    state_service, _, _, backend = state_env

    # Seed an existing claim for the requester on a different slug
    # (test_reciter is already CATALOGUED from state_env).
    from tests.conftest import _seed_state

    _seed_state(
        "other_reciter", state="under_review", assignee_hf_id="u-req", assignee_login="alice"
    )

    requester = _actor(hf_user_id="u-req", role="contributor")
    state_service.transition(
        "test_reciter",
        "reciter.requested",
        actor=requester,
        payload={"proposed_edits": {}, "comments": None, "auto_claim": True},
    )
    system = Actor(hf_user_id="system", login_at_time="system", role=Role.OWNER)
    state_service.transition(
        "test_reciter",
        "reciter.alignment_completed",
        actor=system,
    )
    row = state_service.get_row("test_reciter")
    assert row is not None
    # Auto-claim skipped because the requester has another active claim;
    # row stays in AWAITING_REVIEW for a different contributor.
    assert row.state == ReciterState.AWAITING_REVIEW
    assert row.assignee_hf_id is None

    from services.db import repo_transitions

    skip_records = [
        r
        for r in repo_transitions.for_slug("test_reciter")
        if r["event"] == "reciter.auto_claim_skipped"
    ]
    assert len(skip_records) == 1
    skip = skip_records[0]
    assert skip["slug"] == "test_reciter"
    assert skip["actor"]["hf_user_id"] == "u-req"
    assert skip["payload"]["reason"] == "other_active_claim"
    assert skip["payload"]["existing_claim_slug"] == "other_reciter"


def test_owner_auto_claim_bypasses_one_claim_limit(state_env):
    """Owners are exempt from the one-claim-per-user rule (matches
    can_claim + the /api/claim route): an owner who already holds a claim
    should still get auto-claimed on a second request, and NO skip audit
    is emitted."""
    state_service, _, _, backend = state_env

    # test_reciter is CATALOGUED from state_env; add the owner's existing claim.
    from tests.conftest import _seed_state

    _seed_state(
        "other_reciter", state="under_review", assignee_hf_id="u-owner", assignee_login="alice"
    )

    owner = _actor(hf_user_id="u-owner", role="owner")
    state_service.transition(
        "test_reciter",
        "reciter.requested",
        actor=owner,
        payload={"proposed_edits": {}, "comments": None, "auto_claim": True},
    )
    system = Actor(hf_user_id="system", login_at_time="system", role=Role.OWNER)
    state_service.transition(
        "test_reciter",
        "reciter.alignment_completed",
        actor=system,
    )
    row = state_service.get_row("test_reciter")
    assert row is not None
    # Owner exempt: auto-claim proceeded despite the other UNDER_REVIEW row.
    assert row.state == ReciterState.UNDER_REVIEW
    assert row.assignee_hf_id == "u-owner"

    from services.db import repo_transitions

    skip_records = [
        r
        for r in repo_transitions.for_slug("test_reciter")
        if r["event"] == "reciter.auto_claim_skipped"
    ]
    assert skip_records == []


def test_alignment_completed_noop_when_no_pending(state_env, monkeypatch):
    state_service, _, _, backend = state_env
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    # Move the row to AWAITING_ALIGNMENT without a pending entry (e.g. admin
    # force-set state).
    from tests.conftest import _seed_state

    _seed_state("test_reciter", state="awaiting_alignment", reciter_id="test_reciter")

    system_actor = Actor(
        hf_user_id="system",
        login_at_time="system",
        role=Role.OWNER,
    )
    state_service.transition(
        "test_reciter",
        "reciter.alignment_completed",
        actor=system_actor,
    )
    row = state_service.get_row("test_reciter")
    assert row is not None
    assert row.state == ReciterState.AWAITING_REVIEW
