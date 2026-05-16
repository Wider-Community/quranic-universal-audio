"""Activity state service — bucket-resident store for the activity rails.

Owns ``activity/state.json``: per-user dismissals (admin rail) + global
tombstones (public rail). Hydrates on startup; every mutation rewrites the
JSON atomically (single-writer, single-process — see ``app.py``).

Audit log stays append-only. This sidecar is the only mutable surface
backing the activity rails; the audit records themselves never change.
"""

from __future__ import annotations

import logging
import threading

from scripts.lib.schemas import ActivityState, Actor

from services.state import audit
from services.storage import storage_paths
from services.storage.hf_bucket import StorageNotFound, get_backend

logger = logging.getLogger(__name__)


_store: ActivityState = ActivityState()
_store_lock = threading.Lock()


def hydrate() -> None:
    """Load (or initialize) ``activity/state.json``. Idempotent."""
    global _store
    backend = get_backend()
    try:
        raw = backend.read_json(storage_paths.activity_state_path())
        loaded = ActivityState.model_validate(raw)
    except StorageNotFound:
        logger.info(
            "activity_state: state file missing on bucket; initializing empty store"
        )
        loaded = ActivityState()
    with _store_lock:
        _store = loaded


def snapshot() -> ActivityState:
    """Return a deep copy of the current state."""
    with _store_lock:
        return _store.model_copy(deep=True)


def is_deleted(audit_id: str) -> bool:
    with _store_lock:
        return audit_id in _store.deleted


def is_dismissed(audit_id: str, hf_user_id: str) -> bool:
    with _store_lock:
        return audit_id in _store.dismissals.get(hf_user_id, [])


# ---- Mutations ----


def _persist(new_store: ActivityState) -> None:
    backend = get_backend()
    backend.write_json_atomic(
        storage_paths.activity_state_path(),
        new_store.model_dump(mode="json"),
    )


def dismiss(audit_id: str, *, actor: Actor) -> None:
    """Record a per-user dismissal for ``actor.hf_user_id``.

    Idempotent: dismissing the same id twice leaves the store untouched
    after the first call.
    """
    global _store
    with _store_lock:
        new_store = _store.model_copy(deep=True)
        existing = new_store.dismissals.get(actor.hf_user_id, [])
        if audit_id in existing:
            return
        new_store.dismissals[actor.hf_user_id] = existing + [audit_id]
        _persist(new_store)
        _store = new_store

    audit.append(
        event="activity.dismissed",
        actor=actor,
        payload={"audit_id": audit_id},
    )


def undismiss(audit_id: str, *, actor: Actor) -> None:
    """Remove ``audit_id`` from the caller's dismissals (no-op if absent)."""
    global _store
    with _store_lock:
        existing = _store.dismissals.get(actor.hf_user_id, [])
        if audit_id not in existing:
            return
        new_store = _store.model_copy(deep=True)
        new_store.dismissals[actor.hf_user_id] = [
            x for x in existing if x != audit_id
        ]
        # Tidy: drop the key entirely when the list empties out so the file
        # doesn't accumulate empty arrays.
        if not new_store.dismissals[actor.hf_user_id]:
            del new_store.dismissals[actor.hf_user_id]
        _persist(new_store)
        _store = new_store

    audit.append(
        event="activity.undismissed",
        actor=actor,
        payload={"audit_id": audit_id},
    )


def delete(audit_id: str, *, actor: Actor, reason: str) -> None:
    """Tombstone an audit record so it disappears from the public feed.

    Owner-only at the route layer; this service trusts the caller. The
    reason ≥10 chars constraint is enforced at the route layer too.
    """
    global _store
    with _store_lock:
        if audit_id in _store.deleted:
            return
        new_store = _store.model_copy(deep=True)
        new_store.deleted.append(audit_id)
        _persist(new_store)
        _store = new_store

    audit.append(
        event="admin.activity_deleted",
        actor=actor,
        payload={"audit_id": audit_id},
        reason=reason,
    )
