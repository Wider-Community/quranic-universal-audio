"""Fan a just-recorded event out to per-user notification rows.

Two entry points, one per source write-path:

- ``emit_for_event`` — called from ``state._apply_event`` (and intake) INSIDE
  the live durable transaction, right after the transition row is appended.
  A ``_RESOLVERS`` table maps event name → the target user(s); each target
  becomes one ``repo_notifications.create`` row (deduped on the transition id).
- ``notify_flag_reply`` — called from the segment-save flow, which writes the
  bucket (not SQLite), so it opens its OWN ``durable_transaction``.

Both are **best-effort**: the whole body is wrapped in try/except-log. Losing a
notification is acceptable; raising into the caller would roll back a lifecycle
transition or a segment save, which is not. Self-suppression drops a target
equal to the actor (you don't get notified for your own action), except for the
auto-claim "assigned" case which is explicitly kept.

Flask-free. ``catalog``/``sync`` are imported lazily to keep this module off the
state-machine import-time graph (it is imported lazily from ``_apply_event``).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from typing import Any, NamedTuple

from qua_shared.schemas import Actor, AuditRecord, ReciterRow
from services.db import repo_notifications

from . import copy

logger = logging.getLogger(__name__)


class _Target(NamedTuple):
    hf_user_id: str | None
    title: str
    body: str | None
    payload: dict[str, Any] | None
    keep_self: bool


_Resolver = Callable[[AuditRecord, ReciterRow | None, dict, str], list[_Target]]


def _reciter_name(record: AuditRecord, extra: dict) -> str:
    """Display name for the notification title. Prefers an explicit name in
    ``extra`` (slugless intake carries the proposed reciter name), else resolves
    the delivery slug via the catalog, else falls back to the slug."""
    name = extra.get("reciter_name")
    if name:
        return str(name)
    if record.slug:
        from services.state import catalog

        return catalog.display_name(record.slug) or record.slug
    return "your request"


def _r_request_rejected_soft(record, before, extra, name) -> list[_Target]:
    req: Actor | None = extra.get("requester")
    if req is None:
        return []
    return [_Target(req.hf_user_id, copy.request_sent_back(name), record.reason, None, False)]


def _r_request_rejected_hard(record, before, extra, name) -> list[_Target]:
    req: Actor | None = extra.get("requester")
    if req is None:
        return []
    return [_Target(req.hf_user_id, copy.request_discarded(name), record.reason, None, False)]


def _r_alignment_completed(record, before, extra, name) -> list[_Target]:
    # Only set when the request did NOT auto-claim; the auto-claim path notifies
    # via the folded reciter.claimed "assigned" instead (no double-notify).
    req: Actor | None = extra.get("requester")
    if req is None:
        return []
    return [_Target(req.hf_user_id, copy.ready_for_review(name), None, None, False)]


def _r_claimed(record, before, extra, name) -> list[_Target]:
    # Manual claims are self-initiated (no notification). Only the auto-claim
    # fold — folded by state._maybe_auto_claim with this payload marker —
    # produces an "assigned" notification, kept for the actor (== requester).
    if not record.payload.get("notify_auto_claim"):
        return []
    return [_Target(record.actor.hf_user_id, copy.assigned(name), None, None, True)]


def _r_force_released(record, before, extra, name) -> list[_Target]:
    if before is None or not before.assignee_hf_id:
        return []
    return [_Target(before.assignee_hf_id, copy.force_released(name), None, None, False)]


def _r_intake_returned(record, before, extra, name) -> list[_Target]:
    rid = extra.get("requester_id")
    if not rid:
        return []
    return [_Target(rid, copy.submission_sent_back(name), record.reason, None, False)]


def _r_intake_discarded(record, before, extra, name) -> list[_Target]:
    rid = extra.get("requester_id")
    if not rid:
        return []
    return [_Target(rid, copy.submission_discarded(name), record.reason, None, False)]


_RESOLVERS: dict[str, _Resolver] = {
    "reciter.request_rejected_soft": _r_request_rejected_soft,
    "reciter.request_rejected_hard": _r_request_rejected_hard,
    "reciter.alignment_completed": _r_alignment_completed,
    "reciter.claimed": _r_claimed,
    "claim.force_released": _r_force_released,
    "request.intake_returned": _r_intake_returned,
    "request.intake_discarded": _r_intake_discarded,
}


def emit_for_event(
    conn: sqlite3.Connection,
    record: AuditRecord,
    *,
    before: ReciterRow | None = None,
    extra: dict | None = None,
) -> None:
    """Materialize per-user notifications for a just-appended transition row.

    Runs inside the caller's live transaction (writes enroll via ``get_conn``);
    never opens its own. Best-effort — a failure is logged and swallowed so the
    motivating transition is never rolled back.
    """
    try:
        resolver = _RESOLVERS.get(record.event)
        if resolver is None:
            return
        extra = extra or {}
        name = _reciter_name(record, extra)
        actor_id = record.actor.hf_user_id if record.actor else None
        for t in resolver(record, before, extra, name):
            if not t.hf_user_id:
                continue
            if t.hf_user_id == actor_id and not t.keep_self:
                continue
            repo_notifications.create(
                hf_user_id=t.hf_user_id,
                event=record.event,
                slug=record.slug,
                title=t.title,
                body=t.body,
                payload=t.payload,
                source_key=record.request_id,
            )
    except Exception:  # noqa: BLE001 — best-effort; never break the transition
        logger.exception(
            "notifications.emit_for_event failed for event=%s slug=%s",
            getattr(record, "event", "?"),
            getattr(record, "slug", "?"),
        )


def notify_flag_reply(
    *,
    flagger_id: str | None,
    replier: Actor,
    slug: str,
    segment_uid: str,
    comment: str,
    at_utc: str,
) -> None:
    """Notify the original flagger that someone replied on their flagged segment.

    Opens its own ``durable_transaction`` (the segment save writes the bucket,
    not SQLite). Self-suppressed when the replier is the flagger. Best-effort.
    """
    try:
        if not flagger_id or flagger_id == replier.hf_user_id:
            return
        from services.state import catalog

        name = catalog.display_name(slug) or slug
        from services.db import sync as _sync

        with _sync.durable_transaction():
            repo_notifications.create(
                hf_user_id=flagger_id,
                event="flag.reply",
                slug=slug,
                title=copy.flag_reply(name),
                body=comment,
                payload={"segment_uid": segment_uid},
                source_key=f"flag:{slug}:{segment_uid}:{at_utc}",
            )
    except Exception:  # noqa: BLE001 — best-effort; never break the save
        logger.exception(
            "notifications.notify_flag_reply failed for slug=%s uid=%s", slug, segment_uid
        )
