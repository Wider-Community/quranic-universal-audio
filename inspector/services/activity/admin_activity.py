"""Admin-only activity feed — tier-aware projection of the audit log.

Surfaces events classified as ``admin_only`` by ``activity_classification``
to maintainers + owners. Owners additionally see the actor's HF login on
each card; maintainers see identity-redacted cards.

Per-user dismissals (``services/activity_state``) hide cards from the live
feed; ``archived=True`` returns the dismissed cards so the rail can render
a collapsible archive section.

Mirrors the shape of ``services/public_activity`` so the frontend can
consume both feeds with similar code paths.
"""

from __future__ import annotations

from typing import TypedDict

from scripts.lib.schemas import Role

from . import activity_classification, public_activity
from services.state import catalog as catalog_service
from services.auth import permissions
from services.db import repo_activity


class AdminActivityCard(TypedDict, total=False):
    audit_id: str
    ts: str
    kind: str
    name: str
    riwayah: str | None
    style: str | None
    text: str
    # Present only for owner callers — maintainer view stays redacted.
    actor_login: str
    actor_hf_user_id: str


_TEMPLATES: dict[str, str] = {
    "released": "{name} claim released",
    "marked_ready": "{name} marked ready for publish",
    "unmarked_ready": "{name} unmarked ready",
    "merge_rejected": "{name} marked-ready submission rejected",
    "unpublished": "{name} unpublished",
    "dataset_published": "{name} published to dataset",
    "removed_from_dataset": "{name} removed from dataset",
    "discarded": "{name} discarded",
    "undiscarded": "{name} restored",
    "force_released": "{name} claim force-released",
    "reassigned": "{name} claim reassigned",
    "unlocked_for_revision": "{name} unlocked for revision",
}


def _to_card(record: dict, *, include_actor: bool) -> AdminActivityCard | None:
    kind = activity_classification.admin_kind_for(record)
    if kind is None:
        return None
    slug = record.get("slug")
    if not isinstance(slug, str):
        return None
    ts = record.get("ts")
    if not isinstance(ts, str):
        return None

    delivery = catalog_service.find_delivery(slug)
    riwayah: str | None = None
    style: str | None = None
    name: str | None = None
    if delivery is not None:
        reciter = catalog_service.find_reciter(delivery.reciter_id)
        if reciter is not None:
            name = reciter.name_en
            riwayah = delivery.riwayah
            style = delivery.style
    if name is None:
        name = catalog_service.display_name(slug)
    if name is None:
        return None

    card: AdminActivityCard = AdminActivityCard(
        # STORED content_hash — never recompute (a NULLed slug would mismatch
        # the migrated dismissal/tombstone the FE already holds).
        audit_id=record.get("content_hash") or activity_classification.audit_id(record),
        ts=ts,
        kind=kind,
        name=name,
        riwayah=riwayah,
        style=style,
        text=_TEMPLATES.get(kind, "{name}").format(name=name),
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


def all_admin_cards(
    *,
    caller_role: Role,
    caller_hf_id: str,
    include_dismissed: bool = False,
) -> tuple[list[AdminActivityCard], int]:
    """Return (live_cards, archived_count) for the caller.

    Live cards exclude dismissals; archived cards are the dismissed set.
    When ``include_dismissed=True`` the dismissed set is returned instead
    (still sorted newest-first) and ``archived_count`` is the live count.
    """
    include_actor = permissions.is_owner(type("X", (), {"role": caller_role})())
    dismissed = repo_activity.dismissed_for_user(caller_hf_id)

    live: list[AdminActivityCard] = []
    archived: list[AdminActivityCard] = []
    for record in public_activity._iter_partitions(months=2):
        if record.get("result") != "ok":
            continue
        if activity_classification.classify(record) != "admin_only":
            continue
        card = _to_card(record, include_actor=include_actor)
        if card is None:
            continue
        if card["audit_id"] in dismissed:
            archived.append(card)
        else:
            live.append(card)

    live.sort(key=lambda c: c["ts"], reverse=True)
    archived.sort(key=lambda c: c["ts"], reverse=True)
    if include_dismissed:
        return archived, len(live)
    return live, len(archived)


def feed(
    *,
    caller_role: Role,
    caller_hf_id: str,
    cursor: int = 0,
    limit: int = 50,
    archived: bool = False,
) -> dict:
    """Return one page of the admin feed.

    Returns ``{cards, archived_count, next_cursor, total}``. ``archived_count``
    is the number of cards in the *other* bucket — i.e. when ``archived=False``
    it's the number of dismissed cards available to expand, and vice versa.
    """
    cards, other_count = all_admin_cards(
        caller_role=caller_role,
        caller_hf_id=caller_hf_id,
        include_dismissed=archived,
    )
    total = len(cards)
    page = cards[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < total else None
    return {
        "cards": page,
        "archived_count": other_count,
        "next_cursor": next_cursor,
        "total": total,
    }
