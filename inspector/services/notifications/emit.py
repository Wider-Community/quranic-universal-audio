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

#: Capability that gates the owner-facing review alerts (new request, mark-ready
#: with notes, segment flag/reply). Owner-only by default; an owner can delegate
#: it to maintainers from the Permissions tab.
REVIEW_ALERTS_CAP = "notifications.receive_review_alerts"


def _review_alert_recipients() -> list[str]:
    """Every user who currently holds ``REVIEW_ALERTS_CAP`` (owners + delegated
    maintainers). Imported lazily to keep the state-machine import graph clean."""
    from services.auth import capabilities as _caps

    return _caps.users_with_capability(REVIEW_ALERTS_CAP)


def _owner_targets(title: str, body: str | None, payload: dict[str, Any] | None) -> list[_Target]:
    """One ``_Target`` per review-alert recipient, all sharing the frozen
    title/body/payload. Per-target self-suppression (drop the acting user) is
    applied by ``emit_for_event``'s loop."""
    return [_Target(uid, title, body, payload, False) for uid in _review_alert_recipients()]


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


def _r_marked_ready(record, before, extra, name) -> list[_Target]:
    # Owner-facing alert — ONLY when the contributor left written notes in one
    # of the mark-ready form's free-text boxes. A clean mark-ready (boxes empty,
    # or an owner-bypass with no body) notifies no one — the reciter already
    # shows up in the Reviews queue. Body carries the notes verbatim; the payload
    # marker opens the read-only review modal in the Segments tab on click.
    payload = record.payload or {}
    checks = str(payload.get("comment_checks") or "").strip()
    issues = str(payload.get("comment_issues") or "").strip()
    if not checks and not issues:
        return []
    parts: list[str] = []
    if checks:
        parts.append(f"On the checks: {checks}")
    if issues:
        parts.append(f"Remaining issues: {issues}")
    return _owner_targets(
        copy.marked_ready_with_notes(name), "\n".join(parts), {"openMarkReadyReview": True}
    )


_RESOLVERS: dict[str, _Resolver] = {
    "reciter.request_rejected_soft": _r_request_rejected_soft,
    "reciter.request_rejected_hard": _r_request_rejected_hard,
    "reciter.alignment_completed": _r_alignment_completed,
    "reciter.claimed": _r_claimed,
    "claim.force_released": _r_force_released,
    "request.intake_returned": _r_intake_returned,
    "request.intake_discarded": _r_intake_discarded,
    "reciter.marked_ready": _r_marked_ready,
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
        extra = extra or {}
        name = _reciter_name(record, extra)
        actor_id = record.actor.hf_user_id if record.actor else None
        # Stable per-transition dedup key: a request-scoped id when present
        # (so request alerts archive together), else the transition's own
        # identity (event:slug:ts) so a re-driven transaction can't double-insert.
        source_key = (
            f"request:{record.request_id}"
            if record.request_id
            else f"event:{record.event}:{record.slug}:{record.ts.isoformat()}"
        )
        if resolver is not None:
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
                    source_key=source_key,
                )

        # Auto-archive the "new request" alerts once the reciter reaches review:
        # the request has been fully handled, so its card is stale for everyone.
        if record.event == "reciter.alignment_completed" and record.slug:
            _archive_request_alerts(record.slug)
    except Exception:  # noqa: BLE001 — best-effort; never break the transition
        logger.exception(
            "notifications.emit_for_event failed for event=%s slug=%s",
            getattr(record, "event", "?"),
            getattr(record, "slug", "?"),
        )


def _archive_request_alerts(slug: str) -> None:
    """Dismiss every owner's ``request.received`` card for ``slug``. Each request
    row for the slug shares one ``source_key`` across all recipients, so one
    ``dismiss_by_source_key`` per request clears the whole fan-out. Runs in the
    caller's live transaction."""
    from services.db import repo_requests

    for rid in repo_requests.ids_for_slug(slug):
        repo_notifications.dismiss_by_source_key(f"request:{rid}")


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


def notify_owners_new_request(
    *,
    kind: str,
    requester: Actor,
    slug: str | None,
    request_id: str,
    body: str | None,
    reciter_name: str | None = None,
) -> None:
    """Fan a just-submitted request out to the review-alert recipients.

    Called from BOTH request-creation paths (the slug-based edit-request route
    and the slugless intake submit) — deliberately NOT a ``reciter.requested``
    resolver, since that event re-fires on intake ingest and would double-notify.
    ``reciter_name`` is resolved from the catalog when omitted (slug-based);
    slugless intake passes the proposed/looked-up name explicitly. Opens its own
    ``durable_transaction``; self-suppressed for the requester. Best-effort. The
    card is informational (no click-through) and auto-archives when the reciter
    reaches review (see ``_archive_request_alerts``)."""
    try:
        if reciter_name is None:
            from services.state import catalog

            reciter_name = (catalog.display_name(slug) if slug else None) or "a new request"
        from services.db import sync as _sync

        with _sync.durable_transaction():
            for uid in _review_alert_recipients():
                if uid == requester.hf_user_id:
                    continue
                repo_notifications.create(
                    hf_user_id=uid,
                    event="request.received",
                    slug=slug,
                    title=copy.request_received(reciter_name),
                    body=body,
                    payload={"kind": kind, "request_id": request_id},
                    source_key=f"request:{request_id}",
                )
    except Exception:  # noqa: BLE001 — best-effort; never break the submission
        logger.exception(
            "notifications.notify_owners_new_request failed for request=%s", request_id
        )


def notify_owners_ts_flag(
    *,
    slug: str,
    verse_key: str,
    comment: str | None,
    author_id: str | None,
    author_login: str | None,
    at_utc: str,
) -> None:
    """Fan a new Timestamps-tab verse flag out to the review-alert recipients.

    Fires once per NEW comment (re-edits of an existing comment don't re-notify).
    Anonymous flags have ``author_id``/``author_login`` ``None``. ``author_login``
    rides in the payload so the rail can show it to identity-capable owners; the
    body stays identity-free. Opens its own ``durable_transaction``;
    self-suppressed for a signed-in flagger. Best-effort. Clicking the card
    deep-links to the Timestamps tab at this reciter + verse.
    """
    try:
        from services.state import catalog

        name = catalog.display_name(slug) or slug
        body = f"{verse_key} — {comment}" if comment else verse_key
        from services.db import sync as _sync

        with _sync.durable_transaction():
            for uid in _review_alert_recipients():
                if author_id and uid == author_id:
                    continue
                repo_notifications.create(
                    hf_user_id=uid,
                    event="ts_flag.created",
                    slug=slug,
                    title=copy.ts_flag_reported(name),
                    body=body,
                    payload={
                        "verse_key": verse_key,
                        "author_id": author_id,
                        "author_login": author_login,
                    },
                    source_key=f"tsflag:{slug}:{verse_key}:{at_utc}",
                )
    except Exception:  # noqa: BLE001 — best-effort; never break the flag write
        logger.exception(
            "notifications.notify_owners_ts_flag failed for slug=%s verse=%s", slug, verse_key
        )


def notify_owners_flag_activity(
    *,
    actor: Actor,
    slug: str,
    segment_uid: str,
    kind: str,
    body: str | None,
    at_utc: str,
) -> None:
    """Fan a new flag (``kind='created'``) or a flag reply (``kind='replied'``)
    out to the review-alert recipients. Distinct audience from
    ``notify_flag_reply`` (which tells the *original flagger*). Opens its own
    ``durable_transaction``; self-suppressed for the acting user, so an owner's
    own flag/reply never notifies them. Best-effort."""
    try:
        from services.state import catalog

        name = catalog.display_name(slug) or slug
        title = copy.flag_created(name) if kind == "created" else copy.flag_replied(name)
        from services.db import sync as _sync

        with _sync.durable_transaction():
            for uid in _review_alert_recipients():
                if uid == actor.hf_user_id:
                    continue
                repo_notifications.create(
                    hf_user_id=uid,
                    event="flag.created" if kind == "created" else "flag.replied",
                    slug=slug,
                    title=title,
                    body=body,
                    payload={"segment_uid": segment_uid},
                    source_key=f"ownerflag:{kind}:{slug}:{segment_uid}:{at_utc}",
                )
    except Exception:  # noqa: BLE001 — best-effort; never break the save
        logger.exception(
            "notifications.notify_owners_flag_activity failed for slug=%s uid=%s", slug, segment_uid
        )
