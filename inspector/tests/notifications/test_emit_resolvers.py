"""Unit coverage for the notification emitter resolvers.

Drives ``emit_for_event`` / ``notify_flag_reply`` directly with constructed
records and asserts the materialized ``notifications`` rows (the durability
boundary), rather than mocking the repo. Covers per-event target resolution,
self-suppression, the SYSTEM-actor alignment case, the auto-claim keep-self
case, dedup, and flag-reply self-suppression.
"""

from __future__ import annotations

from qua_shared.schemas import Actor, AuditRecord, ReciterRow, ReciterState
from services.db import _serde, repo_notifications
from services.db import sync as _sync
from services.notifications import emit

_OWNER = Actor(hf_user_id="owner-1", login_at_time="owner", role="owner")
_SYSTEM = Actor(hf_user_id="system", login_at_time="system", role="owner")
_REQUESTER = Actor(hf_user_id="req-1", login_at_time="req", role="contributor")


def _record(event, *, actor, slug="r_test", payload=None, reason=None) -> AuditRecord:
    return AuditRecord(
        ts=_serde.now(),
        event=event,
        actor=actor,
        slug=slug,
        payload=payload or {},
        request_id=f"req_{event}_{slug}",
        reason=reason,
    )


def _emit(record, **kwargs):
    with _sync.durable_transaction() as conn:
        emit.emit_for_event(conn, record, **kwargs)


def _ur_row(slug="r_test", assignee="rev-1") -> ReciterRow:
    return ReciterRow(
        slug=slug,
        state=ReciterState.UNDER_REVIEW,
        state_since=_serde.now(),
        assignee_hf_id=assignee,
        assignee_login="reviewer",
        assignee_since=_serde.now(),
    )


def test_request_rejected_soft_notifies_requester_with_reason():
    rec = _record(
        "reciter.request_rejected_soft", actor=_OWNER, reason="needs a cleaner source link"
    )
    _emit(rec, extra={"requester": _REQUESTER})

    rows = repo_notifications.list_active("req-1")
    assert len(rows) == 1
    assert "was sent back" in rows[0]["title"]
    assert rows[0]["body"] == "needs a cleaner source link"
    assert rows[0]["slug"] == "r_test"


def test_request_rejected_hard_notifies_requester():
    rec = _record(
        "reciter.request_rejected_hard", actor=_OWNER, reason="duplicate of existing combo"
    )
    _emit(rec, extra={"requester": _REQUESTER})

    rows = repo_notifications.list_active("req-1")
    assert len(rows) == 1
    assert "was discarded" in rows[0]["title"]


def test_alignment_completed_notifies_requester_system_actor():
    rec = _record("reciter.alignment_completed", actor=_SYSTEM)
    _emit(rec, extra={"requester": _REQUESTER})

    rows = repo_notifications.list_active("req-1")
    assert len(rows) == 1
    assert "ready for review" in rows[0]["title"]


def test_alignment_completed_without_requester_is_noop():
    """No pending requester captured (admin-initiated alignment) → no rows."""
    _emit(_record("reciter.alignment_completed", actor=_SYSTEM), extra={})
    assert repo_notifications.list_active("req-1") == []


def test_auto_claim_fold_notifies_requester_keep_self():
    """The folded reciter.claimed has actor == requester; the keep-self marker
    means they still get the "assigned" notification (not self-suppressed)."""
    rec = _record(
        "reciter.claimed",
        actor=_REQUESTER,
        payload={"notify_auto_claim": True},
    )
    _emit(
        rec,
        before=ReciterRow(
            slug="r_test", state=ReciterState.AWAITING_REVIEW, state_since=_serde.now()
        ),
    )

    rows = repo_notifications.list_active("req-1")
    assert len(rows) == 1
    assert "assigned to" in rows[0]["title"]


def test_manual_claim_is_noop():
    """A manual self-claim (no auto-claim marker) produces no notification."""
    rec = _record("reciter.claimed", actor=_REQUESTER, payload={})
    _emit(
        rec,
        before=ReciterRow(
            slug="r_test", state=ReciterState.AWAITING_REVIEW, state_since=_serde.now()
        ),
    )
    assert repo_notifications.list_active("req-1") == []


def test_force_released_notifies_prior_assignee():
    rec = _record("claim.force_released", actor=_OWNER)
    _emit(rec, before=_ur_row(assignee="rev-1"))

    rows = repo_notifications.list_active("rev-1")
    assert len(rows) == 1
    assert "was released" in rows[0]["title"]


def test_force_released_self_action_suppressed():
    """An owner force-releasing their OWN claim isn't notified about it."""
    rec = _record("claim.force_released", actor=_OWNER)
    _emit(rec, before=_ur_row(assignee="owner-1"))
    assert repo_notifications.list_active("owner-1") == []


def test_intake_returned_notifies_requester_by_id():
    rec = _record("request.intake_returned", actor=_OWNER, slug=None, reason="link is unreachable")
    _emit(rec, extra={"requester_id": "req-2", "reciter_name": "New Reciter"})

    rows = repo_notifications.list_active("req-2")
    assert len(rows) == 1
    assert rows[0]["title"] == "Your submission for New Reciter was sent back"
    assert rows[0]["slug"] is None


def test_emit_is_deduped_on_resubmit():
    """Re-driving the same transition (same request_id) inserts exactly once."""
    rec = _record("reciter.request_rejected_soft", actor=_OWNER, reason="x" * 12)
    _emit(rec, extra={"requester": _REQUESTER})
    _emit(rec, extra={"requester": _REQUESTER})
    assert len(repo_notifications.list_active("req-1")) == 1


def test_unmapped_event_is_noop():
    _emit(_record("reciter.marked_ready", actor=_OWNER), before=_ur_row())
    assert repo_notifications.list_active("rev-1") == []


def test_flag_reply_notifies_flagger():
    emit.notify_flag_reply(
        flagger_id="flagger-1",
        replier=_OWNER,
        slug="r_test",
        segment_uid="seg-9",
        comment="good catch, fixed it",
        at_utc="2026-06-09T00:00:00.000Z",
    )
    rows = repo_notifications.list_active("flagger-1")
    assert len(rows) == 1
    assert "you flagged in" in rows[0]["title"]
    assert rows[0]["body"] == "good catch, fixed it"


def test_flag_reply_self_reply_suppressed():
    """Replying to your own flag doesn't notify you."""
    emit.notify_flag_reply(
        flagger_id="owner-1",
        replier=_OWNER,
        slug="r_test",
        segment_uid="seg-9",
        comment="note to self",
        at_utc="2026-06-09T00:00:00.000Z",
    )
    assert repo_notifications.list_active("owner-1") == []
