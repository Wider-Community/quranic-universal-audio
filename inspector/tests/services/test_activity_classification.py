"""Tests for ``services/activity_classification``.

Centralised classifier that maps every state-machine event to one of two
buckets: ``public`` (anyone can see) or ``hidden`` (off the rail). The
admin notifications rail was retired; admin-only events now live in
``HIDDEN_EVENTS`` (still audited via ``transitions``, just not surfaced
on a passive feed — the Admin dashboard tabs are the discovery surface).

Also covers ``audit_id`` — a stable content-derived identifier used by
the global-tombstone store to point at audit records without mutating the
append-only audit log.
"""

from __future__ import annotations

import pytest


def _record(
    event,
    *,
    slug="husary_qdc",
    to_state=None,
    ts="2026-05-13T12:00:00+00:00",
    result="ok",
    actor_hf_id="u-1",
    actor_login="alice",
    actor_role="maintainer",
):
    return {
        "event": event,
        "slug": slug,
        "to_state": to_state,
        "ts": ts,
        "result": result,
        "actor": {
            "hf_user_id": actor_hf_id,
            "login_at_time": actor_login,
            "role": actor_role,
        },
    }


# ---------------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event,expected_kind",
    [
        ("catalog.added", "added"),
        ("reciter.alignment_completed", "available_review"),
        ("reciter.claimed", "under_review"),
        # `released` covers BOTH HF dataset push + GH release cut in v2.
        # `reciter.published` (TS gen completion) is HIDDEN in v2 — it's admin
        # infrastructure, not a public-release milestone.
        ("released", "released"),
    ],
)
def test_public_events_classified_with_kind(event, expected_kind):
    from services import activity_classification as ac

    record = _record(event)
    assert ac.classify(record) == "public"
    assert ac.PUBLIC_EVENTS[event] == expected_kind


def test_awaiting_alignment_state_transition_classified_public_requested():
    """The synthetic 'requested' kind is driven by to_state, not event name."""
    from services import activity_classification as ac

    record = _record("state.transition", to_state="awaiting_alignment")
    assert ac.classify(record) == "public"
    assert ac.public_kind_for(record) == "requested"


@pytest.mark.parametrize(
    "event",
    [
        # Former ADMIN_ONLY_EVENTS — admin notifications rail retired; these
        # are now hidden (the Admin dashboard tabs cover them).
        "reciter.released",
        "reciter.marked_ready",
        "reciter.unmarked_ready",
        "reciter.merge_rejected",
        # v2: TS-gen completion is admin infrastructure (was wrongly PUBLIC in v1).
        "reciter.published",
        "reciter.unpublished",
        "reciter.discarded",
        "reciter.undiscarded",
        "claim.force_released",
        "claim.reassigned",
        "admin.unlocked_for_revision",
        # Always hidden.
        "catalog.edited",
        "access.role_granted",
        "access.role_revoked",
        "access.role_updated",
        "admin.activity_deleted",
    ],
)
def test_hidden_events_classified(event):
    from services import activity_classification as ac

    assert ac.classify(_record(event)) == "hidden"


def test_unknown_event_defaults_to_hidden():
    """Safe-default: new events not in either allowlist stay off the rail."""
    from services import activity_classification as ac

    assert ac.classify(_record("totally.new.event")) == "hidden"


def test_reciter_requested_is_public_only():
    """Request *review* moved to the Admin dashboard → Requests tab, so
    `reciter.requested` is public-only now: public prose on the rail, no
    admin surface."""
    from services import activity_classification as ac

    record = _record("reciter.requested")
    assert ac.classify(record) == "public"
    assert ac.public_kind_for(record) == "requested"


@pytest.mark.parametrize(
    "event",
    [
        "reciter.request_rejected_soft",
        "reciter.request_rejected_hard",
    ],
)
def test_request_reject_events_hidden(event):
    """Reject outcomes are off the rail (still audited) — they live in the
    Requests tab now."""
    from services import activity_classification as ac

    record = _record(event)
    assert ac.classify(record) == "hidden"
    assert ac.public_kind_for(record) is None


def test_catalog_conflict_warning_is_hidden():
    """The non-blocking conflict signal emitted by apply_and_archive_completed must not
    surface on the rail."""
    from services import activity_classification as ac

    assert ac.classify(_record("catalog.conflict_warning")) == "hidden"


def test_anti_drift_every_state_handler_is_classified():
    """Anti-drift: every event registered in ``services/state.py:_HANDLERS``
    must have an explicit bucket in the classifier. Forces new events to be
    deliberately classified at the time they're added, not silently dropped.
    """
    from services import activity_classification as ac
    from services import state as state_service

    handlers = state_service._HANDLERS  # type: ignore[attr-defined]
    for event in handlers:
        assert ac.is_classified(event), (
            f"state.py registers {event!r} but it isn't classified in "
            "activity_classification. Add it to PUBLIC_EVENTS or HIDDEN_EVENTS."
        )


# ---------------------------------------------------------------------------
# audit_id()
# ---------------------------------------------------------------------------


def test_audit_id_is_deterministic():
    from services import activity_classification as ac

    r = _record("reciter.claimed")
    assert ac.audit_id(r) == ac.audit_id(r)


def test_audit_id_changes_when_record_differs():
    from services import activity_classification as ac

    base = _record("reciter.claimed")
    different_ts = _record("reciter.claimed", ts="2026-05-14T12:00:00+00:00")
    different_actor = _record("reciter.claimed", actor_hf_id="u-2")
    different_slug = _record("reciter.claimed", slug="other_qdc")

    base_id = ac.audit_id(base)
    assert ac.audit_id(different_ts) != base_id
    assert ac.audit_id(different_actor) != base_id
    assert ac.audit_id(different_slug) != base_id


def test_audit_id_is_short_hex_string():
    from services import activity_classification as ac

    aid = ac.audit_id(_record("reciter.claimed"))
    assert isinstance(aid, str)
    assert len(aid) == 16
    int(aid, 16)  # parses as hex


def test_audit_id_handles_missing_slug_and_actor():
    """Some legacy records may carry None for slug or actor — id should still
    be derivable (we never raise from this function)."""
    from services import activity_classification as ac

    bare = {
        "event": "catalog.added",
        "ts": "2026-05-13T12:00:00+00:00",
        "result": "ok",
    }
    aid = ac.audit_id(bare)
    assert isinstance(aid, str)
    assert len(aid) == 16


def test_audit_id_collision_resistant_over_fixture():
    """Across 100 distinct synthetic records every audit_id is unique."""
    from services import activity_classification as ac

    records = [
        _record(
            "reciter.claimed",
            slug=f"slug_{i:03d}",
            ts=f"2026-05-{(i % 28) + 1:02d}T12:00:00+00:00",
            actor_hf_id=f"u-{i}",
        )
        for i in range(100)
    ]
    ids = {ac.audit_id(r) for r in records}
    assert len(ids) == 100
