"""Activity state service: facade over the activity sidecar tables.

Per-user dismissals (admin rail) + global tombstones (public rail) live in
``activity_dismissals`` / ``activity_tombstones`` (``repo_activity``), keyed on
the transition ``content_hash`` (the same id the FE already holds). The audit
trail for each mutation is a transition row appended in the same durable txn.
"""

from __future__ import annotations

import logging

from scripts.lib.schemas import ActivityState, Actor

from services.state import audit
from services.db import repo_activity
from services.db import sync as _sync

logger = logging.getLogger(__name__)


# ---- Boot / reads ----


def hydrate() -> None:
    """No-op under the SQLite substrate (DB is the source of truth)."""
    return None


def snapshot() -> ActivityState:
    """Reassemble the legacy view (``deleted`` list + ``dismissals`` map)."""
    return ActivityState(
        deleted=sorted(repo_activity.deleted_set()),
        dismissals=repo_activity.all_dismissals(),
    )


def is_deleted(audit_id: str) -> bool:
    return repo_activity.is_deleted(audit_id)


def is_dismissed(audit_id: str, hf_user_id: str) -> bool:
    return repo_activity.is_dismissed(audit_id, hf_user_id)


# ---- Mutations (durable; audit row in the same txn) ----


def dismiss(audit_id: str, *, actor: Actor) -> None:
    """Record a per-user dismissal for ``actor.hf_user_id`` (idempotent)."""
    with _sync.durable_transaction():
        if repo_activity.is_dismissed(audit_id, actor.hf_user_id):
            return
        repo_activity.dismiss(audit_id, actor.hf_user_id)
        audit.append(
            event="activity.dismissed",
            actor=actor,
            payload={"audit_id": audit_id},
        )


def undismiss(audit_id: str, *, actor: Actor) -> None:
    """Remove ``audit_id`` from the caller's dismissals (no-op if absent)."""
    with _sync.durable_transaction():
        if not repo_activity.is_dismissed(audit_id, actor.hf_user_id):
            return
        repo_activity.undismiss(audit_id, actor.hf_user_id)
        audit.append(
            event="activity.undismissed",
            actor=actor,
            payload={"audit_id": audit_id},
        )


def delete(audit_id: str, *, actor: Actor, reason: str) -> None:
    """Tombstone an audit record so it disappears from the public feed.
    Owner-only + reason ≥10 chars enforced at the route layer."""
    with _sync.durable_transaction():
        if repo_activity.is_deleted(audit_id):
            return
        repo_activity.delete(audit_id, deleted_by=actor.hf_user_id, reason=reason)
        audit.append(
            event="admin.activity_deleted",
            actor=actor,
            payload={"audit_id": audit_id},
            reason=reason,
        )
