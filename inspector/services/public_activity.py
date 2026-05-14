"""Public activity feed — redacted projection of the audit log.

Reads ``audit/<YYYY>-<MM>.jsonl`` partitions and surfaces only the public
events classified by ``services/activity_classification``. Every other
event class — admin overrides, force-releases, reassignments, discards,
merge-rejected, intermediate state revisions, role changes — is redacted
from the public feed.

Assignee identity is omitted by default. When the caller is an owner, the
``actor_login`` + ``actor_hf_user_id`` fields are populated so owners can
see "@login requested X · 2h ago". Maintainers, contributors, and anonymous
visitors get the redacted shape.

Records tombstoned in ``services/activity_state.deleted`` are filtered out
for everyone (owner-only delete affordance writes the tombstone).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, TypedDict

from scripts.lib.schemas import Role

from . import activity_classification, activity_state
from . import catalog as catalog_service
from . import permissions, storage_paths
from .hf_bucket import get_backend


PublicEventKind = str  # matches keys in activity_classification.PUBLIC_EVENTS


class PublicActivityCard(TypedDict, total=False):
    """One redacted feed entry. ``actor_*`` fields populated only for owners."""

    ts: str
    kind: PublicEventKind
    name: str
    riwayah: str | None
    style: str | None
    text: str
    audit_id: str
    actor_login: str
    actor_hf_user_id: str


_TEMPLATES: dict[str, str] = {
    "added": "{name} added to catalog",
    "requested": "{name} has been requested",
    "available_review": "{name} is now available for review",
    "under_review": "{name} is now under review",
    "published": "{name} is now published",
}


def _iter_partitions(months: int) -> Iterable[dict]:
    """Yield raw audit records from the current month + previous N-1 months.

    Records are yielded newest-first per partition; partitions are
    iterated newest-first too, so concatenation gives a roughly
    chronological-descending stream that the caller re-sorts before
    paginating.
    """
    now = datetime.now(timezone.utc)
    backend = get_backend()
    for offset in range(months):
        year = now.year
        month = now.month - offset
        while month <= 0:
            month += 12
            year -= 1
        path = storage_paths.audit_partition_path(
            datetime(year, month, 1, tzinfo=timezone.utc),
        )
        if not backend.exists(path):
            continue
        yield from reversed(list(backend.iter_jsonl(path)))


def _delivery_descriptor(slug: str) -> tuple[str, str, str] | None:
    delivery = catalog_service.find_delivery(slug)
    if delivery is None:
        return None
    reciter = catalog_service.find_reciter(delivery.reciter_id)
    if reciter is None:
        return None
    return reciter.name_en, delivery.riwayah, delivery.style


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
        name, riwayah, style = descriptor
    else:
        name = catalog_service.display_name(slug)
        if name is None:
            return None
        riwayah = None
        style = None

    card: PublicActivityCard = PublicActivityCard(
        ts=ts,
        kind=kind,
        name=name,
        riwayah=riwayah,
        style=style,
        text=_TEMPLATES.get(kind, "{name}").format(name=name),
        audit_id=activity_classification.audit_id(record),
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
    caller_role: Role | None = None,
) -> list[PublicActivityCard]:
    """Read + filter + transform audit log into the public feed.

    Records tombstoned in the activity-state store are filtered out for
    everyone. When ``caller_role`` is an owner, each card gets the actor's
    HF login; otherwise identity stays redacted.
    """
    include_actor = caller_role is not None and permissions.is_owner(
        type("_R", (), {"role": caller_role})()
    )
    state_snap = activity_state.snapshot()
    deleted_ids = set(state_snap.deleted)

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
    cards.sort(key=lambda c: c["ts"], reverse=True)
    return cards


def feed(
    cursor: int = 0,
    limit: int = 50,
    *,
    caller_role: Role | None = None,
) -> dict:
    """Return one page of the feed plus a next cursor."""
    cards = all_public_cards(caller_role=caller_role)
    total = len(cards)
    page = cards[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < total else None
    return {
        "cards": page,
        "next_cursor": next_cursor,
        "total": total,
    }
