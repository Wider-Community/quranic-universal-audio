"""Catalog service: ``<bucket>/catalog/reciter_catalog.json``.

Inspector backend is sole writer. In-memory ``ReciterCatalog`` model
hydrated at startup, replaced atomically on every mutating call.

Phase 1 surface:
- ``hydrate()`` / ``snapshot()`` for boot-time + read access
- ``add_reciter()`` / ``edit_reciter()`` / ``add_delivery()`` / ``add_audio_source()``
  for maintainer admin actions

Endpoints exposing these mutations land in Phase 4/5; this module provides
the service layer those endpoints will call. The Phase 1 stub catalog has
vocab-only content; mutation calls aren't expected to fire in Phase 1 itself.

Authority for schema: docs/reference/reciter-catalog.md (the pydantic models
in ``scripts/lib/schemas/catalog.py`` are the runtime authority).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from pydantic import ValidationError

from scripts.lib.schemas import (
    Actor,
    AudioCategory,
    Delivery,
    ReciterCatalog,
    ReciterEntry,
    Source,
)

from . import audit, permissions, storage_paths
from .hf_bucket import StorageNotFound, get_backend

logger = logging.getLogger(__name__)


# ---- Errors ----


class CatalogError(Exception):
    pass


class InvalidCatalogChange(CatalogError):
    pass


class NotAuthorizedForCatalog(CatalogError):
    pass


# ---- In-memory store ----


_store: ReciterCatalog = ReciterCatalog()
_store_lock = threading.Lock()


def hydrate() -> None:
    """Load or initialize the catalog from the bucket. Idempotent."""
    global _store
    backend = get_backend()
    try:
        raw = backend.read_json(storage_paths.catalog_path())
        loaded = ReciterCatalog.model_validate(raw)
    except StorageNotFound:
        logger.warning(
            "catalog: catalog file missing on bucket; initializing empty "
            "in-memory store. Seed the stub via "
            "`.local/inspector-deploy/v2/seed_catalog_stub.py`."
        )
        loaded = ReciterCatalog()
    except ValidationError as e:
        logger.exception("catalog: invalid bucket catalog — refusing to hydrate")
        raise InvalidCatalogChange(str(e)) from e
    with _store_lock:
        _store = loaded


def snapshot() -> ReciterCatalog:
    """Return a defensive copy of the in-memory catalog."""
    with _store_lock:
        return _store.model_copy(deep=True)


def find_delivery(slug: str) -> Delivery | None:
    with _store_lock:
        return _store.find_delivery(slug)


def find_reciter(reciter_id: str) -> ReciterEntry | None:
    with _store_lock:
        return _store.find_reciter(reciter_id)


def display_name(slug: str) -> str | None:
    """Resolve a delivery slug to its reciter's ``name_en``.

    Returns ``None`` when the slug is unknown to the catalog (e.g. before
    catalog promotion, or after a delivery was removed). Callers must
    tolerate the fallback gracefully — surfacing a raw slug to the user is
    never acceptable in user-facing copy.
    """
    with _store_lock:
        delivery = _store.find_delivery(slug)
        if delivery is None:
            return None
        reciter = _store.find_reciter(delivery.reciter_id)
        return reciter.name_en if reciter is not None else None


# ---- Authorization ----


def _require_maintainer(actor: Actor) -> None:
    if not permissions.is_maintainer(actor):
        raise NotAuthorizedForCatalog(
            f"actor role {actor.role!r} cannot mutate catalog; "
            "requires MAINTAINER or OWNER"
        )


# ---- Mutations ----


def _persist(new_store: ReciterCatalog) -> None:
    backend = get_backend()
    backend.write_json_atomic(
        storage_paths.catalog_path(),
        new_store.model_dump(mode="json"),
    )


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
    """Append a new reciter to ``reciters[]``. ``reciter_id`` must be unique."""
    global _store
    _require_maintainer(actor)

    with _store_lock:
        if _store.find_reciter(reciter_id) is not None:
            raise InvalidCatalogChange(f"reciter_id {reciter_id!r} already exists")

        new_store = _store.model_copy(deep=True)
        new_entry = ReciterEntry(
            reciter_id=reciter_id,
            name_en=name_en,
            name_ar=name_ar,
            country=country,
            notes=notes,
        )
        new_store.reciters.append(new_entry)
        try:
            new_store = ReciterCatalog.model_validate(new_store.model_dump(mode="json"))
        except ValidationError as e:
            raise InvalidCatalogChange(str(e)) from e
        _persist(new_store)
        _store = new_store

    audit.append(
        event="catalog.added",
        actor=actor,
        payload={"kind": "reciter", "reciter_id": reciter_id, "name_en": name_en},
        reason=reason,
    )
    return new_entry


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
    global _store
    _require_maintainer(actor)

    with _store_lock:
        existing = _store.find_reciter(reciter_id)
        if existing is None:
            raise InvalidCatalogChange(f"reciter_id {reciter_id!r} not found")

        new_store = _store.model_copy(deep=True)
        patch: dict = {}
        for r in new_store.reciters:
            if r.reciter_id == reciter_id:
                if name_en is not None and name_en != r.name_en:
                    patch["name_en"] = {"from": r.name_en, "to": name_en}
                    r.name_en = name_en
                if name_ar is not None and name_ar != r.name_ar:
                    patch["name_ar"] = {"from": r.name_ar, "to": name_ar}
                    r.name_ar = name_ar
                if country is not None and country != r.country:
                    patch["country"] = {"from": r.country, "to": country}
                    r.country = country
                if notes is not None and notes != r.notes:
                    patch["notes"] = {"from": r.notes, "to": notes}
                    r.notes = notes
                existing = r
                break

        if not patch:
            return existing

        try:
            new_store = ReciterCatalog.model_validate(new_store.model_dump(mode="json"))
        except ValidationError as e:
            raise InvalidCatalogChange(str(e)) from e
        _persist(new_store)
        _store = new_store

    audit.append(
        event="catalog.edited",
        actor=actor,
        payload={"kind": "reciter", "reciter_id": reciter_id, "patch": patch},
        reason=reason,
    )
    return existing


def add_delivery(
    *,
    actor: Actor,
    delivery: Delivery,
    reason: str | None = None,
) -> Delivery:
    """Append a new delivery. Slug + FKs validated by ``ReciterCatalog``."""
    global _store
    _require_maintainer(actor)

    with _store_lock:
        if _store.find_delivery(delivery.slug) is not None:
            raise InvalidCatalogChange(
                f"delivery slug {delivery.slug!r} already exists"
            )
        new_store = _store.model_copy(deep=True)
        new_store.deliveries.append(delivery)
        try:
            new_store = ReciterCatalog.model_validate(new_store.model_dump(mode="json"))
        except ValidationError as e:
            raise InvalidCatalogChange(str(e)) from e
        _persist(new_store)
        _store = new_store

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


def add_audio_source(
    *,
    actor: Actor,
    source: Source,
    reason: str | None = None,
) -> Source:
    """Append a new entry to ``vocab.sources[]``."""
    global _store
    _require_maintainer(actor)

    with _store_lock:
        existing_slugs = {s.slug for s in _store.vocab.sources}
        if source.slug in existing_slugs:
            raise InvalidCatalogChange(f"source {source.slug!r} already exists")
        new_store = _store.model_copy(deep=True)
        new_store.vocab.sources.append(source)
        try:
            new_store = ReciterCatalog.model_validate(new_store.model_dump(mode="json"))
        except ValidationError as e:
            raise InvalidCatalogChange(str(e)) from e
        _persist(new_store)
        _store = new_store

    audit.append(
        event="catalog.audio_source_added",
        actor=actor,
        payload={"slug": source.slug, "name": source.name},
        reason=reason,
    )
    return source


__all__ = [
    "AudioCategory",
    "CatalogError",
    "Delivery",
    "InvalidCatalogChange",
    "NotAuthorizedForCatalog",
    "ReciterCatalog",
    "ReciterEntry",
    "Source",
    "add_audio_source",
    "add_delivery",
    "add_reciter",
    "edit_reciter",
    "find_delivery",
    "find_reciter",
    "hydrate",
    "snapshot",
]
