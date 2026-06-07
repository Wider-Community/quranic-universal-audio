"""Catalog service: facade over the SQLite catalog tables (``repo_catalog``).

Inspector backend is sole writer. ``snapshot()`` reassembles the full
``ReciterCatalog`` (vocab + reciters + deliveries + aliases + persisted
``derived`` + ``generated_at``) so ``/api/static/catalog.json`` stays
byte-identical. Mutations keep the legacy public signatures, compute the
``catalog.edited`` audit ``patch={field:{from,to}}`` shape (the repo persists
only — it does NOT build the patch), and append the transition inside the
caller's transaction so the audit row is atomic with the edit.

Authority for schema: docs/reference/catalog.md (the pydantic models
in ``qua_shared/schemas/catalog.py`` are the runtime authority).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime

from qua_shared.schemas import (
    Actor,
    AudioCategory,
    Channel,
    Delivery,
    ReciterCatalog,
    ReciterEntry,
    Source,
    StaleReason,
)
from services.db import errors as db_errors
from services.db import repo_catalog, repo_releases
from services.db import sync as _sync

from . import audit

logger = logging.getLogger(__name__)

# Catalog fields that surface in a public projection (HF ``mushafs`` catalog +
# GH release ``catalog.json``). Editing one of these desyncs the published
# artifacts → stamp the affected delivery rows ``catalog_edit``-stale. Fields
# outside this set (``notes``/``variant_label``/``source``) are admin-only and
# never warrant a republish. Keep in lockstep with the edit surfaces below.
PUBLIC_DELIVERY_FIELDS = frozenset({"riwayah", "style", "recording_context", "recording_year"})
PUBLIC_RECITER_FIELDS = frozenset({"name_en", "name_ar", "country"})


# ---- Errors ----


class CatalogError(Exception):
    pass


class InvalidCatalogChange(CatalogError):
    pass


class NotAuthorizedForCatalog(CatalogError):
    pass


# ---- Boot ----


def hydrate() -> None:
    """No-op under the SQLite substrate (the DB is the source of truth, loaded
    at boot by ``db.sync.pull`` + ``init_db``). Kept so legacy boot/test call
    sites don't churn."""
    return None


# ---- Reads ----


def snapshot() -> ReciterCatalog:
    """Full catalog read model. Cached on ``db_seq`` (the rebuild is ~38 ms
    today, ~300–700 ms at scale, and runs on hot read paths). The returned
    instance is shared — treat as READ-ONLY (no consumer mutates it). Cached
    in the service via ``db_seq`` keying; per-request cache misses are rebuilt
    from the SQLite tables."""
    from services import db as _db
    from services.storage import cache as _cache

    seq = _db.current_db_seq()
    cached = _cache.get_catalog_snapshot_cache(seq)
    if cached is not None:
        return cached
    cat = repo_catalog.snapshot()
    _cache.set_catalog_snapshot_cache(seq, cat)
    return cat


def find_delivery(slug: str) -> Delivery | None:
    return repo_catalog.find_delivery(slug)


def find_reciter(reciter_id: str) -> ReciterEntry | None:
    return repo_catalog.find_reciter(reciter_id)


def display_name(slug: str) -> str | None:
    """Resolve a delivery slug to its reciter's ``name_en`` (``None`` if the
    slug is unknown). Callers must tolerate the fallback — never surface a raw
    slug in user-facing copy."""
    delivery = repo_catalog.find_delivery(slug)
    if delivery is None:
        return None
    reciter = repo_catalog.find_reciter(delivery.reciter_id)
    return reciter.name_en if reciter is not None else None


# ---- Authorization ----


def _require_capability(actor: Actor, capability: str) -> None:
    """Capability gate for catalog mutations (data-driven; raises the
    catalog-layer error). ``add_*`` → ``catalog.add``, ``edit_*`` →
    ``catalog.edit``. These functions have no direct HTTP route — they run
    inside server-triggered transitions (e.g. alignment_completed) — so this is
    defense-in-depth that still routes through the single resolver rather than a
    stray hardcoded tier check. Lazy import avoids an import cycle."""
    from services.auth import capabilities as _capabilities

    if not _capabilities.can(actor, capability):
        raise NotAuthorizedForCatalog(f"actor role {actor.role!r} lacks capability {capability!r}")


# ---- Mutations (each wraps its own durable txn; nesting-safe when called
#      from inside another boundary's transaction, e.g. the accept flow). ----


def add_reciter(
    *,
    actor: Actor,
    reciter_id: str,
    name_en: str,
    name_ar: str | None = None,
    country: str | None = None,
    notes: str | None = None,
    reason: str | None = None,
) -> ReciterEntry:
    _require_capability(actor, "catalog.add")
    entry = ReciterEntry(
        reciter_id=reciter_id,
        name_en=name_en,
        name_ar=name_ar,
        country=country,
        notes=notes,
    )
    with _sync.durable_transaction():
        try:
            repo_catalog.add_reciter(entry)
        except db_errors.Duplicate as e:
            raise InvalidCatalogChange(str(e)) from e
        audit.append(
            event="catalog.added",
            actor=actor,
            payload={"kind": "reciter", "reciter_id": reciter_id, "name_en": name_en},
            reason=reason,
        )
    return entry


def edit_reciter(
    *,
    actor: Actor,
    reciter_id: str,
    name_en: str | None = None,
    name_ar: str | None = None,
    country: str | None = None,
    notes: str | None = None,
    reason: str | None = None,
) -> ReciterEntry:
    """Mutate a reciter row in place. ``reciter_id`` is immutable."""
    _require_capability(actor, "catalog.edit")
    # Compute the patch BEFORE opening a txn so a no-change call does no bucket
    # I/O / db_seq bump (matches the legacy "no _persist on empty patch").
    existing = repo_catalog.find_reciter(reciter_id)
    if existing is None:
        raise InvalidCatalogChange(f"reciter_id {reciter_id!r} not found")
    proposed = {
        "name_en": name_en,
        "name_ar": name_ar,
        "country": country,
        "notes": notes,
    }
    patch: dict = {}
    for field, new in proposed.items():
        if new is not None and new != getattr(existing, field):
            patch[field] = {"from": getattr(existing, field), "to": new}
    if not patch:
        return existing
    with _sync.durable_transaction():
        updated = repo_catalog.edit_reciter(reciter_id, **{k: v["to"] for k, v in patch.items()})
        audit.append(
            event="catalog.edited",
            actor=actor,
            payload={"kind": "reciter", "reciter_id": reciter_id, "patch": patch},
            reason=reason,
        )
        if PUBLIC_RECITER_FIELDS & patch.keys():
            repo_releases.stamp_stale_for_reciter(
                reciter_id, at=datetime.now(UTC), reason=StaleReason.CATALOG_EDIT
            )
    return updated or existing


def add_delivery(
    *,
    actor: Actor,
    delivery: Delivery,
    reason: str | None = None,
) -> Delivery:
    _require_capability(actor, "catalog.add")
    with _sync.durable_transaction():
        try:
            repo_catalog.add_delivery(delivery)
        except db_errors.Duplicate as e:
            raise InvalidCatalogChange(str(e)) from e
        except sqlite3.IntegrityError as e:  # FK to vocab/reciter
            raise InvalidCatalogChange(str(e)) from e
        audit.append(
            event="catalog.added",
            actor=actor,
            payload={
                "kind": "delivery",
                "slug": delivery.slug,
                "reciter_id": delivery.reciter_id,
            },
            reason=reason,
        )
    return delivery


def edit_delivery(
    *,
    actor: Actor,
    slug: str,
    riwayah: str | None = None,
    style: str | None = None,
    recording_context: str | None = None,
    recording_year: int | None = None,
    reason: str | None = None,
) -> Delivery:
    """Mutate a delivery row in place. ``slug``/``reciter_id`` immutable. Only
    the legacy editable surface (riwayah/style/recording_context/recording_year)
    is exposed. Invalid vocab FK → ``InvalidCatalogChange`` (SQLite FK)."""
    _require_capability(actor, "catalog.edit")
    existing = repo_catalog.find_delivery(slug)
    if existing is None:
        raise InvalidCatalogChange(f"delivery slug {slug!r} not found")
    proposed = {
        "riwayah": riwayah,
        "style": style,
        "recording_context": recording_context,
        "recording_year": recording_year,
    }
    patch: dict = {}
    for field, new in proposed.items():
        if new is not None and new != getattr(existing, field):
            patch[field] = {"from": getattr(existing, field), "to": new}
    if not patch:
        return existing
    with _sync.durable_transaction():
        try:
            updated = repo_catalog.edit_delivery(slug, **{k: v["to"] for k, v in patch.items()})
        except sqlite3.IntegrityError as e:
            raise InvalidCatalogChange(str(e)) from e
        audit.append(
            event="catalog.edited",
            actor=actor,
            slug=slug,
            payload={"kind": "delivery", "slug": slug, "patch": patch},
            reason=reason,
        )
        if PUBLIC_DELIVERY_FIELDS & patch.keys():
            repo_releases.stamp_stale(slug, at=datetime.now(UTC), reason=StaleReason.CATALOG_EDIT)
    return updated or existing


def add_audio_source(
    *,
    actor: Actor,
    source: Source,
    reason: str | None = None,
) -> Source:
    _require_capability(actor, "catalog.add")
    with _sync.durable_transaction():
        try:
            repo_catalog.add_source(source)
        except db_errors.Duplicate as e:
            raise InvalidCatalogChange(str(e)) from e
        audit.append(
            event="catalog.audio_source_added",
            actor=actor,
            payload={"slug": source.slug, "name": source.name},
            reason=reason,
        )
    return source


def add_source(
    *,
    actor: Actor,
    source: Source,
    reason: str | None = None,
) -> Source:
    """Idempotently add a vocab source so ``add_delivery``'s ``source`` FK can be
    satisfied. A no-op (returns the existing row) when the slug is already
    present — the intake ingest may resend ``vocab_additions`` it already
    applied. Maintainer+; nesting-safe (enrolls in the caller's txn)."""
    _require_capability(actor, "catalog.add")
    existing = repo_catalog.find_source(source.slug)
    if existing is not None:
        return existing
    with _sync.durable_transaction():
        repo_catalog.add_source(source)
        audit.append(
            event="catalog.audio_source_added",
            actor=actor,
            payload={"slug": source.slug, "name": source.name},
            reason=reason,
        )
    return source


def add_channel(
    *,
    actor: Actor,
    channel: Channel,
    reason: str | None = None,
) -> Channel:
    """Idempotently add a vocab channel so ``add_delivery``'s ``channel`` FK can
    be satisfied. No-op when the slug already exists. Maintainer+; nesting-safe."""
    _require_capability(actor, "catalog.add")
    existing = repo_catalog.find_channel(channel.slug)
    if existing is not None:
        return existing
    with _sync.durable_transaction():
        repo_catalog.add_channel(channel)
        audit.append(
            event="catalog.channel_added",
            actor=actor,
            payload={"slug": channel.slug, "name": channel.name},
            reason=reason,
        )
    return channel


__all__ = [
    "AudioCategory",
    "CatalogError",
    "Channel",
    "Delivery",
    "InvalidCatalogChange",
    "NotAuthorizedForCatalog",
    "ReciterCatalog",
    "ReciterEntry",
    "Source",
    "add_audio_source",
    "add_channel",
    "add_delivery",
    "add_reciter",
    "add_source",
    "edit_delivery",
    "edit_reciter",
    "find_delivery",
    "find_reciter",
    "display_name",
    "hydrate",
    "snapshot",
]
