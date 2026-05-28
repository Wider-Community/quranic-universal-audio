"""Visibility classifier for audit events — single source of truth.

Maps every state-machine event registered in ``services/state.py:_HANDLERS``
to one of three buckets:

- ``public`` — surfaced on the anonymous-visible Recent Activity rail.
- ``admin_only`` — surfaced on the maintainer/owner-only Admin Notifications
  rail (with actor identity for owners; redacted for maintainers).
- ``hidden`` — off both rails. Bulk/operational events, role administrivia,
  feedback-loop events (dismissals), and intermediate stages whose meaningful
  endpoint is already covered by another event.

``services/public_activity`` and ``services/admin_activity`` both read this
module so the two feeds can never disagree about what is or isn't public.
Adding a new event to ``state.py`` without classifying it here trips
``test_anti_drift_every_state_handler_is_classified`` in the unit suite.
"""

from __future__ import annotations

import hashlib
from typing import Literal


Bucket = Literal["public", "admin_only", "hidden"]


# Public bucket: event -> public-card "kind" (drives the marker dot + template).
PUBLIC_EVENTS: dict[str, str] = {
    "catalog.added": "added",
    # `reciter.requested` shows on the public rail as plain "X was requested"
    # prose. Request *review* is no longer a notification — it lives in the
    # Admin dashboard → Requests tab — so this event is public-only (it is NOT
    # in ADMIN_ONLY_EVENTS; `admin_kind_for()` returns None for it).
    "reciter.requested": "requested",
    "reciter.alignment_completed": "available_review",
    "reciter.claimed": "under_review",
    # `reciter.published` is the human "publish this reciter" action; the
    # downstream `reciter.timestamps_completed` is a pipeline event and is
    # hidden from both rails to avoid duplicating the same milestone.
    "reciter.published": "published",
}


# Admin-only bucket: event -> admin-card "kind".
ADMIN_ONLY_EVENTS: dict[str, str] = {
    "reciter.released": "released",
    "reciter.marked_ready": "marked_ready",
    "reciter.unmarked_ready": "unmarked_ready",
    "reciter.merge_rejected": "merge_rejected",
    "reciter.unpublished": "unpublished",
    "reciter.dataset_published": "dataset_published",
    "reciter.discarded": "discarded",
    "reciter.undiscarded": "undiscarded",
    "claim.force_released": "force_released",
    "claim.reassigned": "reassigned",
    "admin.unlocked_for_revision": "unlocked_for_revision",
}


# Hidden bucket: explicitly classified as "don't surface anywhere".
# Listed verbatim so the anti-drift test can confirm intentional exclusion
# (vs. "developer added a new event and forgot to classify it").
HIDDEN_EVENTS: frozenset[str] = frozenset({
    "catalog.edited",
    # Request review moved off the notifications rail into the Admin dashboard
    # → Requests tab. The submit event stays public prose (PUBLIC_EVENTS);
    # the admin-side reject outcomes are hidden from both rails (still audited).
    "reciter.request_rejected_soft",
    "reciter.request_rejected_hard",
    # Non-blocking warning emitted by ``services.pending_requests.apply_and_archive_completed``
    # when a requester's proposed (riwayah, style) matches another delivery of
    # the same reciter. Visible in the audit log for debugging only.
    "catalog.conflict_warning",
    # Recorded by the auto-claim hook when an alignment_completed transition
    # would otherwise have claimed for the requester, but they already hold
    # another UNDER_REVIEW slug (or were demoted). Hidden from both rails —
    # the audit log carries the forensic trail; promote to admin_only or
    # public if/when a UI surface is added.
    "reciter.auto_claim_skipped",
    "reciter.timestamps_completed",
    "admin.clear_prefetch_purge_at",
    "access.role_granted",
    "access.role_revoked",
    "access.role_updated",
    # Feedback-loop events written by this feature itself — never surface
    # them as notifications (dismissing a card shouldn't create another).
    "activity.dismissed",
    "admin.activity_deleted",
})


# Special case: pre-event state-transition records carrying to_state ==
# "awaiting_alignment" surface as the "requested" public kind. Matches the
# legacy rule in services/public_activity.py.
_TO_STATE_REQUESTED = "awaiting_alignment"
_REQUESTED_KIND = "requested"


def classify(record: dict) -> Bucket:
    """Return the visibility bucket for an audit record.

    Unknown events default to ``hidden`` — the safe choice that keeps new
    events off both rails until they're explicitly classified.

    Precedence for dual-bucket events (currently only ``reciter.requested``):
    ``public`` wins so the anti-drift test treats the event as classified
    and the public rail's "Requested" entry stays visible. The admin rail
    consumes ``admin_kind_for()`` directly, not ``classify()``, so dual
    bucketing is honored downstream regardless.
    """
    event = record.get("event")
    if isinstance(event, str):
        if event in PUBLIC_EVENTS:
            return "public"
        if event in ADMIN_ONLY_EVENTS:
            return "admin_only"
        if event in HIDDEN_EVENTS:
            return "hidden"
    if record.get("to_state") == _TO_STATE_REQUESTED:
        return "public"
    return "hidden"


def public_kind_for(record: dict) -> str | None:
    """Return the public-card kind for ``record`` or None if not public."""
    event = record.get("event")
    if isinstance(event, str) and event in PUBLIC_EVENTS:
        return PUBLIC_EVENTS[event]
    if record.get("to_state") == _TO_STATE_REQUESTED:
        return _REQUESTED_KIND
    return None


def admin_kind_for(record: dict) -> str | None:
    """Return the admin-card kind for ``record`` or None if not admin-only."""
    event = record.get("event")
    if isinstance(event, str) and event in ADMIN_ONLY_EVENTS:
        return ADMIN_ONLY_EVENTS[event]
    return None


def is_classified(event: str) -> bool:
    """True iff ``event`` has an explicit bucket. Used by the anti-drift test."""
    return (
        event in PUBLIC_EVENTS
        or event in ADMIN_ONLY_EVENTS
        or event in HIDDEN_EVENTS
    )


def audit_id(record: dict) -> str:
    """Stable content-derived id for one audit record.

    Used as the key for per-user dismissals and global tombstones — both
    stores point at audit records without mutating the append-only log.

    Derived from the fields that, in practice, uniquely identify a record:
    timestamp + event + slug + actor hf_user_id + result. The hash is
    truncated to 16 hex chars (64 bits) — more than enough for our scale
    (a few thousand records over the audit lifetime).
    """
    ts = record.get("ts") or ""
    event = record.get("event") or ""
    slug = record.get("slug") or ""
    actor = record.get("actor") or {}
    actor_hf = ""
    if isinstance(actor, dict):
        actor_hf = actor.get("hf_user_id") or ""
    result = record.get("result") or "ok"
    raw = f"{ts}|{event}|{slug}|{actor_hf}|{result}".encode("utf-8")
    return hashlib.sha1(raw, usedforsecurity=False).hexdigest()[:16]
