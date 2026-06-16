"""Unit coverage for the notification emitter resolvers.

Drives ``emit_for_event`` / ``notify_flag_reply`` directly with constructed
records and asserts the materialized ``notifications`` rows (the durability
boundary), rather than mocking the repo. Covers per-event target resolution,
self-suppression, the SYSTEM-actor alignment case, the auto-claim keep-self
case, dedup, and flag-reply self-suppression.
"""

from __future__ import annotations

from qua_shared.schemas import Actor, AuditRecord, ReciterRow, ReciterState
from services.db import _serde, repo_notifications, repo_requests
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
    _emit(_record("reciter.published", actor=_OWNER), before=_ur_row())
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


# ---------------------------------------------------------------------------
# Owner-facing review alerts (gated by notifications.receive_review_alerts)
# ---------------------------------------------------------------------------


def test_marked_ready_with_notes_notifies_owners(seed_role):
    """A reviewer marks ready with a written note → every owner gets a card
    carrying the note and the modal-open payload marker."""
    seed_role("owner-1", role="owner")
    seed_role("owner-2", role="owner")
    rec = _record(
        "reciter.marked_ready",
        actor=_REQUESTER,
        payload={"comment_checks": "", "comment_issues": "3 ayat still low-confidence"},
    )
    _emit(rec, before=_ur_row())

    for oid in ("owner-1", "owner-2"):
        rows = repo_notifications.list_active(oid)
        assert len(rows) == 1
        assert "reviewer left notes" in rows[0]["title"]
        assert "3 ayat still low-confidence" in rows[0]["body"]
        assert rows[0]["payload"] == {"openMarkReadyReview": True}


def test_marked_ready_without_notes_is_noop(seed_role):
    """A clean mark-ready (no free-text notes) notifies no owner."""
    seed_role("owner-1", role="owner")
    rec = _record(
        "reciter.marked_ready",
        actor=_REQUESTER,
        payload={"comment_checks": "  ", "comment_issues": ""},
    )
    _emit(rec, before=_ur_row())
    assert repo_notifications.list_active("owner-1") == []


def test_marked_ready_self_suppressed_for_acting_owner(seed_role):
    """An owner who marks ready themselves isn't notified; other owners are."""
    seed_role("owner-1", role="owner")
    seed_role("owner-2", role="owner")
    rec = _record(
        "reciter.marked_ready",
        actor=_OWNER,  # owner-1 is the actor
        payload={"comment_issues": "left a note"},
    )
    _emit(rec, before=_ur_row())
    assert repo_notifications.list_active("owner-1") == []
    assert len(repo_notifications.list_active("owner-2")) == 1


def test_new_request_notifies_owners_self_suppressed(seed_role):
    """notify_owners_new_request fans out to owners with the kind payload; the
    requester (even if an owner) isn't notified about their own request."""
    seed_role("owner-1", role="owner")
    seed_role("owner-2", role="owner")
    requester_owner = Actor(hf_user_id="owner-1", login_at_time="owner", role="owner")
    emit.notify_owners_new_request(
        kind="existing_combo_edit",
        requester=requester_owner,
        slug="r_test",
        request_id="rq_abc",
        body="please re-check surah 2",
    )
    assert repo_notifications.list_active("owner-1") == []  # self-suppressed
    rows = repo_notifications.list_active("owner-2")
    assert len(rows) == 1
    assert rows[0]["event"] == "request.received"
    assert rows[0]["payload"]["kind"] == "existing_combo_edit"
    assert rows[0]["body"] == "please re-check surah 2"


def test_flag_created_and_replied_notify_owners(seed_role):
    seed_role("owner-1", role="owner")
    emit.notify_owners_flag_activity(
        actor=_REQUESTER,
        slug="r_test",
        segment_uid="seg-3",
        kind="created",
        body="2:255 — segment ends mid-word",
        at_utc="2026-06-09T00:00:00.000Z",
    )
    emit.notify_owners_flag_activity(
        actor=_REQUESTER,
        slug="r_test",
        segment_uid="seg-3",
        kind="replied",
        body="2:255 — fixed, please re-check",
        at_utc="2026-06-09T00:01:00.000Z",
    )
    rows = repo_notifications.list_active("owner-1")
    events = sorted(r["event"] for r in rows)
    assert events == ["flag.created", "flag.replied"]
    assert all(r["payload"] == {"segment_uid": "seg-3"} for r in rows)


def test_flag_activity_self_suppressed_for_acting_owner(seed_role):
    """An owner flagging/replying isn't notified about their own action."""
    seed_role("owner-1", role="owner")
    emit.notify_owners_flag_activity(
        actor=_OWNER,  # owner-1
        slug="r_test",
        segment_uid="seg-3",
        kind="created",
        body="2:255 — note",
        at_utc="2026-06-09T00:00:00.000Z",
    )
    assert repo_notifications.list_active("owner-1") == []


def test_alignment_completed_archives_request_alerts(seed_role, seed_state):
    """When the reciter reaches review, the owners' request.received cards for
    that slug auto-archive (dismissed)."""
    seed_role("owner-2", role="owner")
    seed_state("r_test", state="awaiting_alignment")  # delivery row for the requests FK
    with _sync.durable_transaction():
        rid = repo_requests.submit(slug="r_test", requester=_REQUESTER, kind="existing_combo_edit")
    emit.notify_owners_new_request(
        kind="existing_combo_edit",
        requester=_REQUESTER,
        slug="r_test",
        request_id=rid,
        body=None,
    )
    assert len(repo_notifications.list_active("owner-2")) == 1

    _emit(_record("reciter.alignment_completed", actor=_SYSTEM), extra={})

    assert repo_notifications.list_active("owner-2") == []
    archived = repo_notifications.list_archived("owner-2")
    assert len(archived) == 1
    assert archived[0]["event"] == "request.received"
