"""Public activity feed — redacted projection of the audit log.

Reads ``audit/<YYYY>-<MM>.jsonl`` partitions and surfaces only the six
allowlisted user-facing events (Phase 6 §"Public activity feed").
Every other event class — admin overrides, force-releases, reassignments,
discards, merge-rejected, intermediate state revisions, role changes —
is redacted from the public feed.

Assignee identity is never included on the card. Slug is internal-only
(used to resolve the reciter display name via the catalog).

Slice H of phase 6.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Literal, TypedDict

from . import catalog as catalog_service
from . import storage_paths
from .hf_bucket import get_backend


# Six-event allowlist. Every other audit event is redacted from the
# public feed. The mapping value is the public "kind" rendered on the
# card (consumers use it for the colored marker dot).
PublicEventKind = Literal[
    "added",
    "requested",
    "available_review",
    "under_review",
    "publishing",
    "published",
]

_EVENT_TO_KIND: dict[str, PublicEventKind] = {
    "catalog.added": "added",
    "reciter.alignment_completed": "available_review",
    "reciter.claimed": "under_review",
    "reciter.marked_ready": "publishing",
    "reciter.timestamps_completed": "published",
}

# When a state transition lands in awaiting_alignment, surface it as
# "requested" — covers the manual seed path where the catalog row is
# created with an existing state transition queued.
_TO_STATE_REQUESTED = "awaiting_alignment"


class PublicActivityCard(TypedDict, total=False):
    """One redacted feed entry."""
    ts: str                  # ISO datetime UTC
    kind: PublicEventKind
    name: str                # reciter display name; resolved via catalog
    text: str                # human-readable line (no slug, no assignee)


_TEMPLATES: dict[PublicEventKind, str] = {
    "added": "{name} added to catalog",
    "requested": "{name} has been requested",
    "available_review": "{name} is now available for review",
    "under_review": "{name} is now under review",
    "publishing": "{name} is being published",
    "published": "{name} is now published",
}


def _classify(record: dict) -> PublicEventKind | None:
    event = record.get("event")
    if event in _EVENT_TO_KIND:
        return _EVENT_TO_KIND[event]
    # State transitions arriving via state.transition() carry a
    # to_state field; surface those that land on awaiting_alignment as
    # "requested" cards (catalog seed with queued alignment).
    if record.get("to_state") == _TO_STATE_REQUESTED:
        return "requested"
    return None


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
        # iter_jsonl yields records in file order (oldest-first); we
        # reverse here to get newest-first.
        yield from reversed(list(backend.iter_jsonl(path)))


def _to_card(record: dict, kind: PublicEventKind) -> PublicActivityCard | None:
    slug = record.get("slug")
    if not isinstance(slug, str):
        return None
    name = catalog_service.display_name(slug)
    if name is None:
        return None
    ts = record.get("ts")
    if not isinstance(ts, str):
        return None
    return PublicActivityCard(
        ts=ts,
        kind=kind,
        name=name,
        text=_TEMPLATES[kind].format(name=name),
    )


def all_public_cards(months: int = 2) -> list[PublicActivityCard]:
    """Read + filter + transform audit log into the public feed.

    Walks ``months`` partitions (default 2 — current + previous) so the
    feed has enough headroom for the 50-event page even at the start of
    a month. Sorted newest-first.
    """
    cards: list[PublicActivityCard] = []
    for record in _iter_partitions(months):
        if record.get("result") != "ok":
            continue
        kind = _classify(record)
        if kind is None:
            continue
        card = _to_card(record, kind)
        if card is None:
            continue
        cards.append(card)
    # Defensive sort — partition order is newest-first by construction
    # but interleaved months may briefly drift around midnight UTC.
    cards.sort(key=lambda c: c["ts"], reverse=True)
    return cards


def feed(cursor: int = 0, limit: int = 50) -> dict:
    """Return one page of the feed plus a next cursor.

    Cursor is an opaque integer offset into the sorted card list. Small
    Phase-6 traffic; no need for token-style cursors yet.
    """
    cards = all_public_cards()
    total = len(cards)
    page = cards[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < total else None
    return {
        "cards": page,
        "next_cursor": next_cursor,
        "total": total,
    }
