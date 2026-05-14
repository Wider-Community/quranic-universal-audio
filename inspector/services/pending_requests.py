"""Pending request service — bucket-resident store for open user requests.

Sixth bucket store (alongside state, access, catalog, audit, activity_state).
Same hydrate / snapshot / atomic-write pattern as the rest; ``apply_and_clear``
is the only departure — it applies the requester's proposed edits to the
catalog when an admin auto-accepts (i.e. the alignment pipeline produces
files under ``wip/<slug>/``).

The audit log is the authoritative record. This sidecar is a denormalized
index of "what's pending" for fast review. If the file goes missing, the
data is recoverable by replaying ``audit/<YYYY>-<MM>.jsonl`` for
``reciter.requested`` events that don't have a downstream accept/reject.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from scripts.lib.schemas import (
    Actor,
    PendingRequest,
    PendingRequestsFile,
    ProposedEdits,
)

from . import audit, catalog as catalog_service, storage_paths
from .hf_bucket import StorageNotFound, get_backend

logger = logging.getLogger(__name__)


# ---- Errors ----


class PendingRequestsError(Exception):
    pass


class RequestAlreadyPending(PendingRequestsError):
    """Raised when a second request is submitted for a slug that already has
    one pending. The route layer surfaces this as HTTP 409.
    """


# ---- In-memory store ----


_store: PendingRequestsFile = PendingRequestsFile()
_store_lock = threading.Lock()


def hydrate() -> None:
    """Load (or initialize) ``requests/pending.json``. Idempotent."""
    global _store
    backend = get_backend()
    try:
        raw = backend.read_json(storage_paths.pending_requests_path())
        loaded = PendingRequestsFile.model_validate(raw)
    except StorageNotFound:
        logger.info(
            "pending_requests: file missing on bucket; initializing empty store"
        )
        loaded = PendingRequestsFile()
    with _store_lock:
        _store = loaded


def snapshot() -> PendingRequestsFile:
    """Return a deep copy of the current store."""
    with _store_lock:
        return _store.model_copy(deep=True)


def get(slug: str) -> PendingRequest | None:
    """Return the pending entry for ``slug`` or ``None``."""
    with _store_lock:
        entry = _store.by_slug.get(slug)
        return entry.model_copy(deep=True) if entry is not None else None


# ---- Mutations ----


def _persist(new_store: PendingRequestsFile) -> None:
    backend = get_backend()
    backend.write_json_atomic(
        storage_paths.pending_requests_path(),
        new_store.model_dump(mode="json"),
    )


def submit(
    slug: str,
    *,
    requester: Actor,
    edits: ProposedEdits,
    comments: str | None,
    auto_claim: bool = False,
) -> PendingRequest:
    """Record a new pending request for ``slug``.

    Raises ``RequestAlreadyPending`` if an entry already exists. The
    state-machine handler (``reciter.requested``) also enforces the same
    invariant inside the slug lock, so this is a defense-in-depth check.

    ``auto_claim`` is the user-facing "assign me as reviewer when
    alignment completes" checkbox — see ``PendingRequest.auto_claim`` for
    the downstream side-effect.
    """
    global _store
    with _store_lock:
        if slug in _store.by_slug:
            raise RequestAlreadyPending(
                f"slug {slug!r} already has a pending request"
            )
        entry = PendingRequest(
            slug=slug,
            submitted_at=datetime.now(timezone.utc),
            requester=requester,
            proposed_edits=edits,
            comments=comments,
            auto_claim=auto_claim,
        )
        new_store = _store.model_copy(deep=True)
        new_store.by_slug[slug] = entry
        _persist(new_store)
        _store = new_store
    return entry


def clear(slug: str) -> None:
    """Drop the pending entry for ``slug``. No-op if absent."""
    global _store
    with _store_lock:
        if slug not in _store.by_slug:
            return
        new_store = _store.model_copy(deep=True)
        del new_store.by_slug[slug]
        _persist(new_store)
        _store = new_store


def apply_and_clear(slug: str, *, actor: Actor) -> None:
    """Apply the pending request's proposed edits to the catalog, then clear.

    Called from the dispatcher when ``reciter.alignment_completed`` fires —
    either via the server-side auto-detect reconciler (system actor) or a
    manual admin trigger. Safe to call when no pending entry exists: it
    no-ops in that case so the caller doesn't need to pre-check.

    Conflict detection (proposed ``(riwayah, style)`` matching another
    delivery of the same reciter) emits a non-blocking ``catalog.conflict_warning``
    audit record. The edits still apply.
    """
    pending = get(slug)
    if pending is None:
        return

    edits = pending.proposed_edits
    if edits.has_any():
        delivery = catalog_service.find_delivery(slug)
        if delivery is not None:
            # Reciter-level edits (name_en, name_ar, country).
            reciter_kwargs: dict[str, object] = {}
            if edits.name_en is not None:
                reciter_kwargs["name_en"] = edits.name_en
            if edits.name_ar is not None:
                reciter_kwargs["name_ar"] = edits.name_ar
            if edits.country is not None:
                reciter_kwargs["country"] = edits.country
            if reciter_kwargs:
                try:
                    catalog_service.edit_reciter(
                        actor=actor,
                        reciter_id=delivery.reciter_id,
                        reason="auto-applied from pending request",
                        **reciter_kwargs,  # type: ignore[arg-type]
                    )
                except catalog_service.CatalogError:
                    logger.exception(
                        "pending_requests: failed applying reciter edits for %s",
                        slug,
                    )

            # Delivery-level edits + conflict warning.
            delivery_kwargs: dict[str, object] = {}
            if edits.riwayah is not None:
                delivery_kwargs["riwayah"] = edits.riwayah
            if edits.style is not None:
                delivery_kwargs["style"] = edits.style
            if edits.recording_context is not None:
                delivery_kwargs["recording_context"] = edits.recording_context
            if edits.recording_year is not None:
                delivery_kwargs["recording_year"] = edits.recording_year

            # Warn (non-blocking) if proposed riwayah+style collides with another
            # delivery of the same reciter.
            proposed_riwayah = edits.riwayah or delivery.riwayah
            proposed_style = edits.style or delivery.style
            catalog = catalog_service.snapshot()
            collision = next(
                (
                    d
                    for d in catalog.deliveries
                    if d.slug != slug
                    and d.reciter_id == delivery.reciter_id
                    and d.riwayah == proposed_riwayah
                    and d.style == proposed_style
                ),
                None,
            )
            if collision is not None:
                audit.append(
                    event="catalog.conflict_warning",
                    actor=actor,
                    slug=slug,
                    payload={
                        "conflict_with_slug": collision.slug,
                        "riwayah": proposed_riwayah,
                        "style": proposed_style,
                    },
                )

            if delivery_kwargs:
                try:
                    catalog_service.edit_delivery(
                        actor=actor,
                        slug=slug,
                        reason="auto-applied from pending request",
                        **delivery_kwargs,  # type: ignore[arg-type]
                    )
                except catalog_service.CatalogError:
                    logger.exception(
                        "pending_requests: failed applying delivery edits for %s",
                        slug,
                    )

    clear(slug)


__all__ = [
    "PendingRequestsError",
    "RequestAlreadyPending",
    "apply_and_clear",
    "clear",
    "get",
    "hydrate",
    "snapshot",
    "submit",
]
