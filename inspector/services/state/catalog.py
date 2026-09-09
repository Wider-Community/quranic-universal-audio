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
from collections.abc import Mapping
from datetime import UTC, datetime

from qua_shared.catalog_visibility import is_everyayah_channel
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
from qua_shared.schemas.bucket.catalog import Derived, SourceChannelPair
from services.db import errors as db_errors
from services.db import repo_catalog, repo_releases
from services.db import sync as _sync

from . import audit

logger = logging.getLogger(__name__)

# All delivery metadata is represented by at least one public catalog or
# release projection. Editing one therefore invalidates the affected artifact;
# the next HF/GH publish operation carries the new value outward.
PUBLIC_DELIVERY_FIELDS = frozenset(
    {
        "riwayah",
        "style",
        "recording_context",
        "recording_year",
        "variant_label",
        "source",
        "channel",
        "source_url",
        "audio_category",
        "chapter_count",
        "codec",
        "container",
        "sample_rate_hz",
        "channels",
        "bitrate_mode",
        "bitrate_kbps_nominal",
        "total_duration_sec",
    }
)
PUBLIC_RECITER_FIELDS = frozenset({"name_en", "name_ar", "country"})
RECITER_EDITABLE_FIELDS = frozenset({"name_en", "name_ar", "country", "notes"})
DELIVERY_EDITABLE_FIELDS = frozenset(PUBLIC_DELIVERY_FIELDS)


# ---- Errors ----


class CatalogError(Exception):
    pass


class InvalidCatalogChange(CatalogError):
    pass


class NotAuthorizedForCatalog(CatalogError):
    pass


def _actor_is_owner(actor: Actor) -> bool:
    role = getattr(actor.role, "value", actor.role)
    return role == "owner"


def _require_everyayah_owner(actor: Actor, channel: str) -> None:
    if is_everyayah_channel(channel) and not _actor_is_owner(actor):
        raise NotAuthorizedForCatalog("EveryAyah catalog rows are owner-only")


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
    if isinstance(cached, ReciterCatalog):
        return cached
    cat = repo_catalog.snapshot()
    _cache.set_catalog_snapshot_cache(seq, cat)
    return cat


def for_viewer(*, include_everyayah: bool = False) -> ReciterCatalog:
    """Return the catalog projection appropriate for an Inspector viewer.

    The owner receives the canonical snapshot. Other viewers receive a
    self-consistent projection: EveryAyah deliveries, EveryAyah-only reciters,
    and derived source/channel counts are removed together.
    """
    cat = snapshot()
    if include_everyayah:
        return cat
    deliveries = [d for d in cat.deliveries if not is_everyayah_channel(d.channel)]
    reciter_ids = {d.reciter_id for d in deliveries}
    reciters = [r for r in cat.reciters if r.reciter_id in reciter_ids]
    counts: dict[tuple[str, str], int] = {}
    for d in deliveries:
        key = (d.source, d.channel)
        counts[key] = counts.get(key, 0) + 1
    derived = Derived(
        source_channels=[
            SourceChannelPair(source=source, channel=channel, delivery_count=count)
            for (source, channel), count in sorted(counts.items())
        ]
    )
    vocab = cat.vocab.model_copy(
        update={
            "channels": [
                channel for channel in cat.vocab.channels if not is_everyayah_channel(channel.slug)
            ]
        }
    )
    return cat.model_copy(
        update={
            "reciters": reciters,
            "deliveries": deliveries,
            "derived": derived,
            "vocab": vocab,
        }
    )


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
    if not _actor_is_owner(actor):
        reciter_deliveries = [d for d in snapshot().deliveries if d.reciter_id == reciter_id]
        if reciter_deliveries and all(is_everyayah_channel(d.channel) for d in reciter_deliveries):
            raise NotAuthorizedForCatalog("EveryAyah-only reciters are owner-only")
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


def edit_reciter_fields(
    *,
    actor: Actor,
    reciter_id: str,
    fields: Mapping[str, object],
    reason: str | None = None,
) -> ReciterEntry:
    """Apply an explicit field map; ``None`` intentionally clears metadata."""
    _require_capability(actor, "catalog.edit")
    unknown = set(fields) - RECITER_EDITABLE_FIELDS
    if unknown:
        raise InvalidCatalogChange(f"unknown reciter fields: {sorted(unknown)!r}")
    existing = repo_catalog.find_reciter(reciter_id)
    if existing is None:
        raise InvalidCatalogChange(f"reciter_id {reciter_id!r} not found")
    if not _actor_is_owner(actor):
        reciter_deliveries = [d for d in snapshot().deliveries if d.reciter_id == reciter_id]
        if reciter_deliveries and all(is_everyayah_channel(d.channel) for d in reciter_deliveries):
            raise NotAuthorizedForCatalog("EveryAyah-only reciters are owner-only")
    try:
        candidate = ReciterEntry.model_validate(
            {**existing.model_dump(mode="python"), **dict(fields)}
        )
    except Exception as exc:
        raise InvalidCatalogChange(str(exc)) from exc
    patch = {
        field: {"from": getattr(existing, field), "to": getattr(candidate, field)}
        for field in fields
        if getattr(existing, field) != getattr(candidate, field)
    }
    if not patch:
        return existing
    with _sync.durable_transaction():
        updated = repo_catalog.edit_reciter(
            reciter_id, **{field: change["to"] for field, change in patch.items()}
        )
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
    return updated or candidate


def add_delivery(
    *,
    actor: Actor,
    delivery: Delivery,
    reason: str | None = None,
) -> Delivery:
    _require_capability(actor, "catalog.add")
    _require_everyayah_owner(actor, delivery.channel)
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
    variant_label: str | None = None,
    reason: str | None = None,
) -> Delivery:
    """Mutate a delivery row in place. ``slug``/``reciter_id`` immutable. Editable
    surface: riwayah/style/recording_context/recording_year + ``variant_label``
    (the free-text UI distinguisher between same-reciter deliveries, e.g. Qasr vs
    Tawassut). Invalid vocab FK → ``InvalidCatalogChange`` (SQLite FK)."""
    _require_capability(actor, "catalog.edit")
    existing = repo_catalog.find_delivery(slug)
    if existing is None:
        raise InvalidCatalogChange(f"delivery slug {slug!r} not found")
    _require_everyayah_owner(actor, existing.channel)
    proposed = {
        "riwayah": riwayah,
        "style": style,
        "recording_context": recording_context,
        "recording_year": recording_year,
        "variant_label": variant_label,
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


def edit_delivery_fields(
    *,
    actor: Actor,
    slug: str,
    fields: Mapping[str, object],
    reason: str | None = None,
) -> Delivery:
    """Apply the complete delivery metadata edit surface atomically."""
    _require_capability(actor, "catalog.edit")
    unknown = set(fields) - DELIVERY_EDITABLE_FIELDS
    if unknown:
        raise InvalidCatalogChange(f"unknown delivery fields: {sorted(unknown)!r}")
    existing = repo_catalog.find_delivery(slug)
    if existing is None:
        raise InvalidCatalogChange(f"delivery slug {slug!r} not found")
    _require_everyayah_owner(actor, existing.channel)
    try:
        candidate = Delivery.model_validate({**existing.model_dump(mode="python"), **dict(fields)})
    except Exception as exc:
        raise InvalidCatalogChange(str(exc)) from exc
    _require_everyayah_owner(actor, candidate.channel)
    patch = {
        field: {"from": getattr(existing, field), "to": getattr(candidate, field)}
        for field in fields
        if getattr(existing, field) != getattr(candidate, field)
    }
    if not patch:
        return existing
    with _sync.durable_transaction():
        try:
            updated = repo_catalog.edit_delivery(
                slug, **{field: change["to"] for field, change in patch.items()}
            )
        except sqlite3.IntegrityError as exc:
            raise InvalidCatalogChange(str(exc)) from exc
        audit.append(
            event="catalog.edited",
            actor=actor,
            slug=slug,
            payload={"kind": "delivery", "slug": slug, "patch": patch},
            reason=reason,
        )
        if PUBLIC_DELIVERY_FIELDS & patch.keys():
            repo_releases.stamp_stale(slug, at=datetime.now(UTC), reason=StaleReason.CATALOG_EDIT)
    return updated or candidate


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
    "edit_delivery_fields",
    "edit_reciter",
    "edit_reciter_fields",
    "find_delivery",
    "find_reciter",
    "display_name",
    "hydrate",
    "snapshot",
]
