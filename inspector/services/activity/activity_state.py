"""Activity state service: facade over the global-tombstone sidecar.

Owner-only ``delete`` writes a row into ``activity_tombstones`` (keyed on
the transition ``content_hash`` the FE already holds) so the public-feed
reader filters the matching audit record out for everyone. The audit trail
for the mutation is a transition row appended in the same durable
transaction.

Per-user dismissals were retired alongside the admin notifications rail
(the Admin dashboard tabs are now the source of admin awareness); only the
public-feed tombstone path remains.
"""

from __future__ import annotations

import logging

from qua_shared.schemas import ActivityState, Actor
from services.db import repo_activity
from services.db import sync as _sync
from services.state import audit

logger = logging.getLogger(__name__)


# ---- Boot / reads ----


def hydrate() -> None:
    """No-op under the SQLite substrate (DB is the source of truth)."""
    return None


def snapshot() -> ActivityState:
    """Reassemble the legacy view (``deleted`` list of tombstoned audit_ids)."""
    return ActivityState(deleted=sorted(repo_activity.deleted_set()))


def is_deleted(audit_id: str) -> bool:
    return repo_activity.is_deleted(audit_id)


# ---- Mutations (durable; audit row in the same txn) ----


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
