"""Pending request service: facade over the SQLite ``requests`` table.

Requests are stored in one unified ``requests`` table (``repo_requests``);
a row's ``status`` field (``pending`` → ``accepted``/``returned``/``discarded``)
tracks resolution state. Public signatures are unchanged;
``apply_and_archive_completed`` keeps the reciter-vs-delivery edit split +
the non-blocking ``catalog.conflict_warning``.
"""

from __future__ import annotations

import logging

from scripts.lib.schemas import (
    Actor,
    PendingRequest,
    PendingRequestsFile,
    ProposedEdits,
)

from . import audit, catalog as catalog_service
from services.db import repo_requests
from services.db import sync as _sync

logger = logging.getLogger(__name__)


# ---- Errors ----


class PendingRequestsError(Exception):
    pass


class RequestAlreadyPending(PendingRequestsError):
    """A second request was submitted for a slug that already has one pending.
    The route layer surfaces this as HTTP 409."""


# ---- Boot / reads ----


def hydrate() -> None:
    """No-op under the SQLite substrate (DB is the source of truth)."""
    return None


def snapshot() -> PendingRequestsFile:
    """Reassemble the legacy ``by_slug`` pending view from the requests table."""
    store = PendingRequestsFile()
    for entry in repo_requests.all_pending():
        store.by_slug[entry.slug] = entry
    return store


def get(slug: str) -> PendingRequest | None:
    return repo_requests.get_pending(slug)


# ---- Mutations (durable; nesting-safe inside state.transition's txn) ----


def submit(
    slug: str,
    *,
    requester: Actor,
    edits: ProposedEdits,
    comments: str | None,
    auto_claim: bool = False,
) -> PendingRequest:
    """Record a new pending request for ``slug``. Raises ``RequestAlreadyPending``
    if one already exists (also enforced by the partial-unique index)."""
    with _sync.durable_transaction():
        if repo_requests.has_pending(slug):
            raise RequestAlreadyPending(
                f"slug {slug!r} already has a pending request"
            )
        repo_requests.submit(
            slug=slug,
            requester=requester,
            proposed_edits=edits,
            comments=comments,
            auto_claim=auto_claim,
        )
        entry = repo_requests.get_pending(slug)
    assert entry is not None  # just inserted
    return entry


def clear(slug: str) -> None:
    """Drop the pending entry for ``slug`` without archiving. No-op if absent."""
    with _sync.durable_transaction():
        repo_requests.delete_pending(slug)


def apply_and_archive_completed(slug: str, *, actor: Actor) -> None:
    """Apply the pending request's proposed edits to the catalog, then resolve
    it to ``accepted``. No-op if no pending entry. Catalog-edit failures are
    logged but don't block resolution (matches the "cleared regardless" contract).

    Conflict detection (proposed ``(riwayah, style)`` matching another delivery
    of the same reciter) emits a non-blocking ``catalog.conflict_warning``."""
    with _sync.durable_transaction():
        pending = repo_requests.get_pending(slug)
        if pending is None:
            return

        edits = pending.proposed_edits
        if edits.has_any():
            delivery = catalog_service.find_delivery(slug)
            if delivery is not None:
                _apply_edits(slug, delivery, edits, actor)

        repo_requests.resolve(
            slug=slug, status="accepted", transitioned_by=actor, reason=None,
        )


def _apply_edits(slug, delivery, edits, actor) -> None:
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
                "pending_requests: failed applying reciter edits for %s", slug
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

    proposed_riwayah = edits.riwayah or delivery.riwayah
    proposed_style = edits.style or delivery.style
    catalog = catalog_service.snapshot()
    collision = next(
        (
            d for d in catalog.deliveries
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
                "pending_requests: failed applying delivery edits for %s", slug
            )


def archive_returned(slug: str, *, reason: str, by_actor: Actor) -> None:
    """Resolve the pending entry for ``slug`` to ``returned`` (preserving its
    payload for the requester). No-op if absent."""
    with _sync.durable_transaction():
        repo_requests.resolve(
            slug=slug, status="returned", transitioned_by=by_actor, reason=reason,
        )


def archive_discarded(slug: str, *, reason: str, by_actor: Actor) -> None:
    """Resolve the pending entry for ``slug`` to ``discarded``. No-op if absent."""
    with _sync.durable_transaction():
        repo_requests.resolve(
            slug=slug, status="discarded", transitioned_by=by_actor, reason=reason,
        )


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
