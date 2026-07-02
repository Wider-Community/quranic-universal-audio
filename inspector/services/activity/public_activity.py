"""Public activity feed — redacted projection of the ``transitions`` log.

Reads a rolling window of the SQLite ``transitions`` table (``repo_transitions``)
and surfaces only the public events classified by
``services/activity_classification``. Every other event class — admin
overrides, force-releases, reassignments, discards, merge-rejected,
intermediate state revisions, role changes — is redacted from the public feed.

Assignee identity is omitted by default. When the caller is an owner, the
``actor_login`` + ``actor_hf_user_id`` fields are populated so owners can
see "@login requested X · 2h ago". Maintainers, contributors, and anonymous
visitors get the redacted shape.

Records tombstoned in ``activity_tombstones`` are filtered out for everyone
(owner-only delete affordance writes the tombstone). The dismissal/tombstone
key is the STORED ``content_hash`` column — never recomputed from the row,
because a migration-NULLed slug would recompute a different hash and silently
stop matching.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TypedDict

from services.db import _serde, repo_activity, repo_transitions
from services.state import catalog as catalog_service

from . import activity_classification

PublicEventKind = str  # matches keys in activity_classification.PUBLIC_EVENTS


class PublicActivityCard(TypedDict, total=False):
    """One redacted feed entry. ``actor_*`` fields populated only for owners."""

    ts: str
    kind: PublicEventKind
    name: str
    name_ar: str | None
    riwayah: str | None
    style: str | None
    text: str
    audit_id: str
    actor_login: str
    actor_hf_user_id: str


_TEMPLATES: dict[str, str] = {
    "added": "{name} added to catalog",
    "requested": "{name} has been requested",
    "available_for_review": "{name} is now available for review",
    "under_review": "{name} is now under review",
    "published": "{name} is now published",
}


def _window_cutoff_iso(months: int) -> str:
    """ISO timestamp for the start of the earliest month in an N-month window
    (current month + previous N-1), matching the legacy partition span."""
    now = datetime.now(UTC)
    year, month = now.year, now.month - (months - 1)
    while month <= 0:
        month += 12
        year -= 1
    iso = _serde.to_iso(datetime(year, month, 1, tzinfo=UTC))
    assert iso is not None  # non-None datetime always serializes to a string
    return iso


def _iter_partitions(months: int) -> Iterable[dict]:
    """Yield transition records from the rolling N-month window, newest-first."""
    yield from repo_transitions.since(_window_cutoff_iso(months))


def _delivery_descriptor(slug: str) -> tuple[str, str | None, str, str] | None:
    delivery = catalog_service.find_delivery(slug)
    if delivery is None:
        return None
    reciter = catalog_service.find_reciter(delivery.reciter_id)
    if reciter is None:
        return None
    return reciter.name_en, reciter.name_ar, delivery.riwayah, delivery.style


def _to_card(
    record: dict,
    *,
    include_actor: bool,
) -> PublicActivityCard | None:
    kind = activity_classification.public_kind_for(record)
    if kind is None:
        return None
    slug = record.get("slug")
    if not isinstance(slug, str):
        return None
    ts = record.get("ts")
    if not isinstance(ts, str):
        return None
    descriptor = _delivery_descriptor(slug)
    if descriptor is not None:
        name, name_ar, riwayah, style = descriptor
    else:
        name = catalog_service.display_name(slug)
        if name is None:
            return None
        name_ar = None
        riwayah = None
        style = None

    card: PublicActivityCard = PublicActivityCard(
        ts=ts,
        kind=kind,
        name=name,
        name_ar=name_ar,
        riwayah=riwayah,
        style=style,
        text=_TEMPLATES.get(kind, "{name}").format(name=name),
        # STORED content_hash (the id the FE/dismissals already hold) — never
        # recompute from the row (a NULLed slug would mismatch).
        audit_id=record.get("content_hash") or activity_classification.audit_id(record),
    )
    if include_actor:
        actor = record.get("actor") or {}
        if isinstance(actor, dict):
            login = actor.get("login_at_time")
            hf_user_id = actor.get("hf_user_id")
            if isinstance(login, str):
                card["actor_login"] = login
            if isinstance(hf_user_id, str):
                card["actor_hf_user_id"] = hf_user_id
    return card


def all_public_cards(
    months: int = 2,
    *,
    include_identity: bool = False,
) -> list[PublicActivityCard]:
    """Read + filter + transform audit log into the public feed.

    Records tombstoned in the activity-state store are filtered out for
    everyone. When ``include_identity`` is True, each card gets the actor's
    HF login; otherwise identity stays redacted. The caller (route layer)
    resolves the ``identity.see_actor`` capability and passes the bool — this
    service stays Flask- and capability-agnostic.
    """
    include_actor = include_identity
    deleted_ids = repo_activity.deleted_set()

    cards: list[PublicActivityCard] = []
    for record in _iter_partitions(months):
        if record.get("result") != "ok":
            continue
        card = _to_card(record, include_actor=include_actor)
        if card is None:
            continue
        if card.get("audit_id") in deleted_ids:
            continue
        cards.append(card)
    cards.sort(key=lambda c: c.get("ts", ""), reverse=True)
    return cards


def feed(
    cursor: int = 0,
    limit: int = 50,
    *,
    include_identity: bool = False,
) -> dict:
    """Return one page of the feed plus a next cursor."""
    cards = all_public_cards(include_identity=include_identity)
    total = len(cards)
    page = cards[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < total else None
    return {
        "cards": page,
        "next_cursor": next_cursor,
        "total": total,
    }
