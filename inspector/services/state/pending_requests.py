"""Pending request service — bucket-resident store for open user requests.

Sixth bucket store (alongside state, access, catalog, audit, activity_state).
Same hydrate / snapshot / atomic-write pattern as the rest. Terminal-state
transitions move entries out of ``requests/pending.json`` and into one of
three sibling archive files via ``services.state.request_archive``:

- ``apply_and_archive_completed`` (called from ``reciter.alignment_completed``)
- ``archive_returned``            (called from ``reciter.request_rejected_soft``)
- ``archive_discarded``           (called from ``reciter.request_rejected_hard``)

The audit log is the authoritative record. This sidecar is a denormalized
"what's pending right now" index for fast review; the archive files are
its per-slug history counterparts.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from scripts.lib.schemas import (
    Actor,
    ArchivedRequest,
    PendingRequest,
    PendingRequestsFile,
    ProposedEdits,
)

from . import audit, catalog as catalog_service, request_archive
from services.storage import storage_paths
from services.storage.hf_bucket import StorageNotFound, get_backend

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


def _archive(
    pending: PendingRequest,
    *,
    kind: request_archive.ArchiveKind,
    transitioned_by: Actor,
    reason: str | None,
) -> None:
    """Build an ``ArchivedRequest`` from ``pending`` and append it to ``kind``.

    Pure plumbing — callers wrap their own clear() so the pending file and
    the archive file move in lockstep with the state transition.
    """
    entry = ArchivedRequest(
        slug=pending.slug,
        submitted_at=pending.submitted_at,
        requester=pending.requester,
        proposed_edits=pending.proposed_edits,
        comments=pending.comments,
        auto_claim=pending.auto_claim,
        archived_at=datetime.now(timezone.utc),
        transitioned_by=transitioned_by,
        reason=reason,
    )
    request_archive.append(kind, entry)


def apply_and_archive_completed(slug: str, *, actor: Actor) -> None:
    """Apply the pending request's proposed edits to the catalog, archive
    it as ``completed``, then clear from pending.

    Called from the dispatcher when ``reciter.alignment_completed`` fires —
    either via the server-side auto-detect reconciler (system actor) or a
    manual admin trigger. Safe to call when no pending entry exists: it
    no-ops in that case so the caller doesn't need to pre-check.

    Conflict detection (proposed ``(riwayah, style)`` matching another
    delivery of the same reciter) emits a non-blocking ``catalog.conflict_warning``
    audit record. The edits still apply.

    Archive write happens *after* catalog edits so the archived entry
    reflects exactly what the original request asked for; failures inside
    ``catalog_service.edit_*`` are logged but do not block the archive +
    clear path (matches the docstring contract of "the pending entry is
    cleared regardless of whether edits applied cleanly").
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

    _archive(
        pending,
        kind=request_archive.ArchiveKind.COMPLETED,
        transitioned_by=actor,
        reason=None,
    )
    clear(slug)


def archive_returned(slug: str, *, reason: str, by_actor: Actor) -> None:
    """Archive the pending entry for ``slug`` into ``returned.json``, then clear.

    Called from ``_h_request_rejected_soft``. ``reason`` is the admin's
    send-back justification (already normalized + length-checked by the
    state handler's ``_require_reason``).

    Pending edits are preserved verbatim in the archive entry — the
    requester can use ``requests/returned.json`` to recover what they
    originally asked for and resubmit a corrected version.

    No-op if no pending entry exists (the state handler enforces
    AWAITING_ALIGNMENT before calling, so the entry should always be
    present; the no-op is defense-in-depth).
    """
    pending = get(slug)
    if pending is None:
        return
    _archive(
        pending,
        kind=request_archive.ArchiveKind.RETURNED,
        transitioned_by=by_actor,
        reason=reason,
    )
    clear(slug)


def archive_discarded(slug: str, *, reason: str, by_actor: Actor) -> None:
    """Archive the pending entry for ``slug`` into ``discarded.json``, then clear.

    Called from ``_h_request_rejected_hard``. ``reason`` is the admin's
    discard justification (already normalized + length-checked by the
    state handler).

    The row's ``visibility`` flips to DISCARDED in the state handler;
    this archive complements that by preserving the original request
    payload for forensics.
    """
    pending = get(slug)
    if pending is None:
        return
    _archive(
        pending,
        kind=request_archive.ArchiveKind.DISCARDED,
        transitioned_by=by_actor,
        reason=reason,
    )
    clear(slug)


__all__ = [
    "PendingRequestsError",
    "RequestAlreadyPending",
    "apply_and_archive_completed",
    "archive_discarded",
    "archive_returned",
    "clear",
    "get",
    "hydrate",
    "snapshot",
    "submit",
]
