"""Reciter state service: reads/writes from SQLite ``delivery_states`` + ``claims`` tables.

Single source of truth for reciter lifecycle + assignee. Inspector backend
is sole writer. The SQLite DB (via ``repo_state``, ``repo_claims``) is the
canonical store; writes commit atomically via ``durable_transaction``.

The full state machine ships in Phase 1 even though most endpoint callers
land in later phases — the dispatcher is the single source of truth and
later phases just add routes. Per-event payload shapes are colocated below
as ``TypedDict``s so callers know exactly what each event expects.

Spec:
- docs/planning/inspector-deploy/v2/inspector-state-management.md §4
  (canonical event vocabulary + transition matrix)
- docs/planning/inspector-deploy/v2/phases/state-machine.md
  (admin diagram + state-preserving actions)
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

from scripts.lib.schemas import (
    Actor,
    ReciterRow,
    ReciterState,
    ReciterStateFile,
    RevisionContext,
    Visibility,
)

from . import audit
from services.auth import permissions
from services import db as _db
from services.db import _serde, repo_access, repo_claims, repo_state, repo_transitions
from services.db import sync as _sync

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------


class StateError(Exception):
    pass


class UnknownReciter(StateError):
    pass


class UnknownEvent(StateError):
    pass


class InvalidTransition(StateError):
    """Raised when the matrix rejects a transition.

    The database is unchanged; no transition row is written. Callers should
    surface HTTP 400 with the message.

    Optional ``details`` carry structured context the FE can render (e.g.
    the offending category counts for a mark-ready submission). The app-
    level error handler at ``app.py`` includes them in the JSON envelope.
    """

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.details = details or None


class NotAuthorizedForTransition(StateError):
    pass


# ----------------------------------------------------------------------
# Per-event payload shapes
# ----------------------------------------------------------------------


class ClaimedPayload(TypedDict):
    assignee_hf_id: str
    assignee_login: str


class ReassignedPayload(TypedDict):
    new_assignee_hf_id: str
    new_assignee_login: str
    previous_assignee_hf_id: str


class MergeRejectedPayload(TypedDict, total=False):
    pass  # ``reason`` is on the audit record, not the payload


class PublishedPayload(TypedDict, total=False):
    pass


class TimestampsCompletedPayload(TypedDict):
    job_id: str


class UnlockedForRevisionPayload(TypedDict):
    pass


class UnpublishedPayload(TypedDict):
    pass


class DiscardedPayload(TypedDict, total=False):
    pass


# ----------------------------------------------------------------------
# Reads (assembled from the SQLite substrate via repo_state)
# ----------------------------------------------------------------------


def hydrate() -> None:
    """No-op under the SQLite substrate (the DB is the source of truth, loaded
    at boot by ``db.sync.pull`` + ``init_db``). Kept so legacy boot/test call
    sites don't churn."""
    return None


def is_hydrated() -> bool:
    """True if the DB is open + migrated (``/healthz`` reads this)."""
    return bool(_db.healthcheck().get("open"))


def snapshot() -> ReciterStateFile:
    """Reassemble the legacy whole-store view (parity for the few readers that
    expect a ``ReciterStateFile``)."""
    return ReciterStateFile(reciters=repo_state.all_rows())


def get_row(slug: str) -> ReciterRow | None:
    return repo_state.get_row(slug)


def all_rows() -> list[ReciterRow]:
    return repo_state.all_rows()


# ----------------------------------------------------------------------
# Authorization helpers
# ----------------------------------------------------------------------


def _is_maintainer(actor: Actor) -> bool:
    return permissions.is_maintainer(actor)


def _is_owner(actor: Actor) -> bool:
    return permissions.is_owner(actor)


def _require_maintainer(actor: Actor) -> None:
    if not permissions.is_maintainer(actor):
        raise NotAuthorizedForTransition(
            f"actor role {actor.role!r} requires MAINTAINER or OWNER"
        )


def _require_owner(actor: Actor) -> None:
    if not permissions.is_owner(actor):
        raise NotAuthorizedForTransition(
            f"actor role {actor.role!r} requires OWNER"
        )


def _require_contributor_or_higher(actor: Actor) -> None:
    if not permissions.is_contributor_or_higher(actor):
        raise NotAuthorizedForTransition(
            f"actor role {actor.role!r} is not a recognized role"
        )


def _require_claim_holder_or_maintainer(actor: Actor, row: ReciterRow) -> None:
    if not permissions.is_claim_holder_or_maintainer(actor, row):
        raise NotAuthorizedForTransition(
            "only the current assignee or a maintainer may release this reciter"
        )


def _require_claim_holder(actor: Actor, row: ReciterRow) -> None:
    if not permissions.is_claim_holder(actor, row):
        raise NotAuthorizedForTransition(
            "only the current assignee may perform this action"
        )


def _require_reason(reason: str | None, event: str) -> str:
    """Coerce ``reason`` to a non-empty trimmed string or raise.

    Used by handlers whose audit-log entry must carry a human-readable
    justification (force-release, reassign, force-set, send-back, etc.).
    """
    norm = permissions.normalize_reason(reason)
    if norm is None:
        raise InvalidTransition(
            f"{event} requires reason ≥ {permissions.MIN_REASON_CHARS} chars"
        )
    return norm


# ----------------------------------------------------------------------
# Dispatch — one durable transaction per event
# ----------------------------------------------------------------------


def transition(
    slug: str,
    event: str,
    *,
    actor: Actor,
    payload: dict[str, Any] | None = None,
    reason: str | None = None,
) -> ReciterRow:
    """Apply a slug-bound transition in ONE durable transaction. Returns the
    new row.

    The handler + the ``transitions`` row + the ``delivery_states``/``claims``
    writes (and any folded auto-claim) commit atomically; the commit is then
    uploaded to the bucket before this returns (``durable_transaction``) so a
    write is never acked without a durable bucket copy. No per-slug lock: the
    single serialized writer + ``BEGIN IMMEDIATE`` already serializes same-slug
    writes (and a per-slug lock taken before the write lock would deadlock the
    revoke cascade, which holds the write lock then closes per-slug claims).
    """
    payload = payload or {}
    if event not in _HANDLERS:
        raise UnknownEvent(f"unknown slug-bound event {event!r}")
    with _sync.durable_transaction() as conn:
        new_row = _apply_event(conn, slug, event, actor=actor, payload=payload, reason=reason)
    # The TS manifest (services/reference/timestamps.py) is a process-cached
    # projection of which slugs are released, with no other
    # invalidation hook — without this it stays frozen at boot-state until the
    # next restart. Drop it AFTER commit (a pre-commit drop could let a
    # concurrent manifest read re-cache the old state). Unconditional rather
    # than enumerating publish-affecting events: the rebuild is cheap + lazy
    # (next manifest request, warm sidecar caches) and transitions are
    # admin/edit-frequency, not request-frequency.
    from services.reference import timestamps as _ts_manifest
    _ts_manifest.invalidate()
    return new_row


def _apply_event(
    conn: sqlite3.Connection,
    slug: str,
    event: str,
    *,
    actor: Actor,
    payload: dict[str, Any],
    reason: str | None,
) -> ReciterRow:
    """Apply one event on the active transaction connection (NON-locking).

    Used by ``transition()`` and — for the cascading ``reciter.released`` on
    role revoke — by ``services.auth.access.revoke``. FK ordering: the
    ``transitions`` row is written FIRST (``delivery_states``/``claims``
    reference it), then the state + claim diffs, then any folded auto-claim.
    """
    handler = _HANDLERS.get(event)
    if handler is None:
        raise UnknownEvent(f"unknown slug-bound event {event!r}")

    before = repo_state.get_row(slug)

    # Actor must exist for the transitions.actor_id FK BEFORE the handler runs —
    # some handlers (alignment_completed → apply_and_archive_completed) append
    # their own transition rows (catalog.edited) mid-handler.
    repo_access.ensure_user(actor.hf_user_id, login=actor.login_at_time)

    # Capture auto-claim intent BEFORE the handler resolves (clears) the pending
    # request via apply_and_archive_completed.
    auto_claim_requester: Actor | None = None
    if event == "reciter.alignment_completed":
        from . import pending_requests as _pending_requests
        pending = _pending_requests.get(slug)
        if pending is not None and pending.auto_claim:
            auto_claim_requester = pending.requester

    new_row = handler(slug, before, actor, payload, reason)

    # Transition row FIRST (delivery_states/claims reference its id).
    tid = repo_transitions.append(
        event=event,
        actor=actor,
        slug=slug,
        from_state=before.state.value if before is not None else None,
        to_state=new_row.state.value,
        payload=payload,
        reason=reason,
    ).request_id
    _persist_state(before, new_row, tid=tid)
    _persist_claim_diff(before, new_row, tid=tid, event=event, payload=payload)

    if auto_claim_requester is not None:
        _maybe_auto_claim(conn, slug, auto_claim_requester)

    return new_row


def _persist_state(before: ReciterRow | None, new_row: ReciterRow, *, tid: str) -> None:
    """Insert (new row) or update the changed ``delivery_states`` columns."""
    if before is None:
        repo_state.upsert_state(
            new_row.slug,
            state=new_row.state,
            state_since=new_row.state_since,
            visibility=new_row.visibility,
            visibility_reason=new_row.visibility_reason,
            last_save_at=new_row.last_save_at,
            created_by_transition_id=tid,
            timestamps_job_ids=list(new_row.timestamps_job_ids),
            prefetch_purge_at=new_row.prefetch_purge_at,
            revision_in_progress=new_row.revision_in_progress,
        )
        return
    updates: dict[str, Any] = {}
    for col in (
        "state", "state_since", "visibility", "visibility_reason",
        "last_save_at", "timestamps_job_ids", "prefetch_purge_at",
        "revision_in_progress",
    ):
        if getattr(new_row, col) != getattr(before, col):
            updates[col] = getattr(new_row, col)
    if updates:
        repo_state.update_state(new_row.slug, **updates)


def _persist_claim_diff(
    before: ReciterRow | None,
    new_row: ReciterRow,
    *,
    tid: str,
    event: str,
    payload: dict[str, Any],
) -> None:
    """Derive claim operations from the assignee/marked_ready delta. The open
    claim is the source of truth for ``assignee_*`` + ``marked_ready`` on the
    assembled ``ReciterRow`` (only populated on UNDER_REVIEW rows).

    For ``reciter.marked_ready`` events, ``payload`` is the validated
    ``MarkReadyRequest`` shape — the checklist + two comment boxes are
    persisted onto the open claim alongside ``marked_ready_at``."""
    before_assignee = before.assignee_hf_id if before is not None else None
    new_assignee = new_row.assignee_hf_id
    before_ready = before.marked_ready if before is not None else False

    if new_assignee and not before_assignee:
        repo_access.ensure_user(new_assignee, login=new_row.assignee_login)
        repo_claims.open_claim(
            slug=new_row.slug,
            assignee_id=new_assignee,
            assignee_login=new_row.assignee_login,
            claimed_at=new_row.assignee_since,
            opened_by_transition_id=tid,
        )
    elif before_assignee and new_assignee and new_assignee != before_assignee:
        repo_access.ensure_user(new_assignee, login=new_row.assignee_login)
        repo_claims.reassign(
            slug=new_row.slug,
            new_assignee_id=new_assignee,
            new_assignee_login=new_row.assignee_login,
            at=new_row.assignee_since,
            closed_by_transition_id=tid,
            opened_by_transition_id=tid,
        )
    elif before_assignee and not new_assignee:
        repo_claims.close_claim(
            slug=new_row.slug, close_reason=event, closed_by_transition_id=tid
        )

    # marked_ready toggle on a still-held claim (same assignee).
    if new_assignee and before_assignee == new_assignee and new_row.marked_ready != before_ready:
        if new_row.marked_ready:
            # mark-ready: payload is a validated MarkReadyRequest shape
            # (the handler raises before reaching this point if not). Pull
            # checklist + comments onto the open-claim row.
            checklist = payload.get("checklist") or {}
            checklist_json = _serde.json_dumps(checklist)
            repo_claims.set_marked_ready(
                new_row.slug,
                ready=True,
                checklist_json=checklist_json,
                comment_checks=str(payload.get("comment_checks") or ""),
                comment_issues=str(payload.get("comment_issues") or ""),
            )
        else:
            # unmark-ready: clears marked_ready_at + the three submission
            # columns on the open claim. A subsequent re-mark writes fresh
            # values; the prior cycle's submission lives on the closed
            # history row (set_marked_ready only touches the OPEN claim).
            repo_claims.set_marked_ready(new_row.slug, ready=False)


def _maybe_auto_claim(conn: sqlite3.Connection, slug: str, requester: Actor) -> None:
    """Fold ``reciter.claimed`` into the alignment txn for an ``auto_claim``
    request. Owners are exempt from the one-claim check; a non-owner already
    holding another claim gets an in-txn ``reciter.auto_claim_skipped`` audit."""
    repo_access.ensure_user(requester.hf_user_id, login=requester.login_at_time)
    if not permissions.is_owner(requester):
        held = repo_claims.open_claim_for_user(requester.hf_user_id)
        if held is not None and held != slug:
            logger.info(
                "auto_claim: %s already holds claim on %s; skipping %s",
                requester.hf_user_id, held, slug,
            )
            repo_transitions.append(
                event="reciter.auto_claim_skipped",
                actor=requester,
                slug=slug,
                payload={"reason": "other_active_claim", "existing_claim_slug": held},
            )
            return
    _apply_event(
        conn,
        slug,
        "reciter.claimed",
        actor=requester,
        payload={
            "assignee_hf_id": requester.hf_user_id,
            "assignee_login": requester.login_at_time,
        },
        reason=None,
    )


# ----------------------------------------------------------------------
# Per-event handlers
# ----------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Each handler:
# - validates (state, role, payload)
# - returns the new ReciterRow
# - never persists itself — the dispatcher does


def _h_catalog_added(slug, before, actor, payload, reason):
    """Catalog admin added a reciter; insert a state row in CATALOGUED."""
    if before is not None:
        raise InvalidTransition(f"slug {slug!r} already has a state row")
    _require_maintainer(actor)
    return ReciterRow(
        slug=slug,
        state=ReciterState.CATALOGUED,
        state_since=_now(),
    )


def _h_catalog_edited(slug, before, actor, payload, reason):
    """No-op on the state row; audit-only. The dispatcher still records it."""
    if before is None:
        raise UnknownReciter(slug)
    _require_maintainer(actor)
    return before  # unchanged


def _h_alignment_completed(slug, before, actor, payload, reason):
    """Server-side or admin-triggered acceptance: the alignment pipeline has
    produced files under ``reciters/<slug>/`` and the row is ready for human
    review.

    Side effect: if a pending user request exists for this slug, applies the
    proposed catalog edits (riwayah/style/recording_*/names/country) at the
    same time so the catalog reflects whatever the requester proposed before
    the row leaves AWAITING_ALIGNMENT. See ``services.pending_requests``.
    The pending entry is cleared regardless of whether edits applied
    cleanly — catalog failures are logged but don't block the transition.

    If the pending request carried ``auto_claim=True``, ``_apply_event`` folds
    a follow-up ``reciter.claimed`` into THIS transaction on the requester's
    behalf (skipping, with an audit, if a non-owner already holds a claim).
    """
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.AWAITING_ALIGNMENT:
        raise InvalidTransition(
            f"alignment_completed requires AWAITING_ALIGNMENT, got {before.state.value}"
        )

    # The auto_claim requester is captured by ``_apply_event`` BEFORE this
    # handler resolves the pending request; the follow-up ``reciter.claimed``
    # is folded into the same transaction post-persist (no recursion through
    # ``transition()``, no post-commit queue).
    # Imported here (not at module top) to avoid a circular import.
    from . import pending_requests as _pending_requests
    _pending_requests.apply_and_archive_completed(slug, actor=actor)

    return _replace(
        before,
        state=ReciterState.AWAITING_REVIEW,
        state_since=_now(),
        prefetch_purge_at=None,
    )


def _h_requested(slug, before, actor, payload, reason):
    """User-submitted request to align this reciter combination.

    Any signed-in user (contributor or above) can fire this. Accepts two
    source shapes — both map to the same "available for request" public
    bucket and both land in ``AWAITING_ALIGNMENT``:

    - No state row exists yet (``before is None``). The dispatcher inserts
      a fresh row. This is the common case: catalog deliveries don't get a
      state row until a lifecycle event fires.
    - A row exists in ``CATALOGUED``. Transition in place. This is the
      post-soft-reject re-request path: ``reciter.request_rejected_soft``
      drops the row back to CATALOGUED, and the next request transitions
      it forward again.

    Stores the proposed catalog edits + free-form comments in the
    ``pending_requests`` bucket store. Acceptance is implicit and
    server-side (see ``_h_alignment_completed``); admins can reject
    pre-acceptance via ``reciter.request_rejected_*``.
    """
    _require_contributor_or_higher(actor)

    if before is not None:
        if before.state != ReciterState.CATALOGUED:
            raise InvalidTransition(
                f"requested requires CATALOGUED or no row, got {before.state.value}"
            )
        if before.visibility != Visibility.PUBLIC:
            raise InvalidTransition(
                f"cannot request a {before.visibility.value!r} reciter"
            )

    # Defense-in-depth: also checked by the route layer.
    from . import pending_requests as _pending_requests
    if _pending_requests.get(slug) is not None:
        raise InvalidTransition(
            f"slug {slug!r} already has a pending request"
        )

    from scripts.lib.schemas import ProposedEdits as _ProposedEdits
    edits_raw = payload.get("proposed_edits") or {}
    try:
        edits = _ProposedEdits.model_validate(edits_raw)
    except Exception as e:  # noqa: BLE001
        raise InvalidTransition(f"invalid proposed_edits: {e}") from e
    comments = payload.get("comments")
    if comments is not None and not isinstance(comments, str):
        raise InvalidTransition("comments must be a string or null")
    if comments is not None and len(comments) > 1000:
        raise InvalidTransition("comments exceeds 1000 chars")

    auto_claim = bool(payload.get("auto_claim", False))

    # Persist the pending entry inside the same transaction as the state row;
    # the partial-unique index + the get() check above reject a duplicate, and
    # a downstream failure rolls the whole event back atomically.
    _pending_requests.submit(
        slug,
        requester=actor,
        edits=edits,
        comments=comments,
        auto_claim=auto_claim,
    )

    now = _now()
    if before is None:
        return ReciterRow(
            slug=slug,
            state=ReciterState.AWAITING_ALIGNMENT,
            state_since=now,
        )
    return _replace(
        before,
        state=ReciterState.AWAITING_ALIGNMENT,
        state_since=now,
    )


def _h_request_rejected_soft(slug, before, actor, payload, reason):
    """Admin sends a pending request back. Row returns to CATALOGUED.

    The pending entry moves to ``requests/returned.json`` (with the
    admin's reason) so the requester can recover what they originally
    asked for and resubmit a corrected version. Reason is required and
    also lands in the audit record for accountability.
    """
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.AWAITING_ALIGNMENT:
        raise InvalidTransition(
            f"request_rejected_soft requires AWAITING_ALIGNMENT, got {before.state.value}"
        )
    _require_owner(actor)
    norm_reason = _require_reason(reason, "request_rejected_soft")

    from . import pending_requests as _pending_requests
    _pending_requests.archive_returned(slug, reason=norm_reason, by_actor=actor)

    return _replace(
        before,
        state=ReciterState.CATALOGUED,
        state_since=_now(),
    )


def _h_request_rejected_hard(slug, before, actor, payload, reason):
    """Admin rejects a pending request and discards the combination.

    Row returns to CATALOGUED with ``visibility=DISCARDED`` so the public
    dashboard hides it. Admins can still view discarded rows in the modal's
    separate discarded section; owners can un-discard via ``reciter.undiscarded``.
    """
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.AWAITING_ALIGNMENT:
        raise InvalidTransition(
            f"request_rejected_hard requires AWAITING_ALIGNMENT, got {before.state.value}"
        )
    _require_owner(actor)
    norm_reason = _require_reason(reason, "request_rejected_hard")

    from . import pending_requests as _pending_requests
    _pending_requests.archive_discarded(slug, reason=norm_reason, by_actor=actor)

    return _replace(
        before,
        state=ReciterState.CATALOGUED,
        state_since=_now(),
        visibility=Visibility.DISCARDED,
        visibility_reason=norm_reason,
    )


def _h_claimed(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    _require_contributor_or_higher(actor)
    if before.state != ReciterState.AWAITING_REVIEW:
        raise InvalidTransition(
            f"claimed requires AWAITING_REVIEW, got {before.state.value}"
        )
    if before.visibility != Visibility.PUBLIC:
        raise InvalidTransition(
            f"cannot claim a {before.visibility.value!r} reciter"
        )

    # Payload contributes assignee_login at write time (display cache).
    login = payload.get("assignee_login") or actor.login_at_time
    now = _now()
    return _replace(
        before,
        state=ReciterState.UNDER_REVIEW,
        state_since=now,
        assignee_hf_id=actor.hf_user_id,
        assignee_login=login,
        assignee_since=now,
        marked_ready=False,
    )


def _h_released(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.UNDER_REVIEW:
        raise InvalidTransition(
            f"released requires UNDER_REVIEW, got {before.state.value}"
        )
    # A reviewer who has already marked ready must unmark first (or an
    # admin must force-release / send-back). Self-release on a marked
    # row would silently drop the submission and leave a half-finished
    # cycle behind. Maintainers are routed through ``claim.force_released``
    # for that case (different audit reason). The route still uses this
    # handler for the maintainer-self-release-of-own-claim edge case, so
    # the gate fires only when the claim holder owns the marked row.
    if before.marked_ready and permissions.is_claim_holder(actor, before):
        raise InvalidTransition(
            "release blocked: unmark ready first, or ask an admin to send back"
        )
    _require_claim_holder_or_maintainer(actor, before)
    return _replace(
        before,
        state=ReciterState.AWAITING_REVIEW,
        state_since=_now(),
        assignee_hf_id=None,
        assignee_login=None,
        assignee_since=None,
        marked_ready=False,
        prefetch_purge_at=None,
    )


def _h_marked_ready(slug, before, actor, payload, reason):
    """Reviewer mark-ready handler.

    Validates the submission payload (well-formed ``MarkReadyRequest`` with
    all five checklist values True) and re-computes the five gated
    validation category counts against the on-disk segs. Either gate
    raises ``InvalidTransition`` so the reviewer sees a structured 400.

    The submission lives on the open claim row (persisted by
    ``_persist_claim_diff`` via the payload it threads through).
    """
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.UNDER_REVIEW:
        raise InvalidTransition(
            f"marked_ready requires UNDER_REVIEW, got {before.state.value}"
        )
    _require_claim_holder(actor, before)
    if before.marked_ready:
        raise InvalidTransition("already marked_ready")

    # Lazy import: scripts.lib.schemas is a sibling import (already used
    # elsewhere in this module), but the validation module pulls heavy
    # bucket loaders — keep it off the top-level state.py import graph.
    from scripts.lib.schemas import BLOCKING_COUNT_KEYS, MarkReadyRequest
    from pydantic import ValidationError

    try:
        submission = MarkReadyRequest.model_validate(payload)
    except ValidationError as e:
        raise InvalidTransition(
            "marked_ready payload invalid",
            details={"validation_errors": e.errors()},
        ) from e

    unchecked = [
        k for k, v in submission.checklist.model_dump().items() if not v
    ]
    if unchecked:
        raise InvalidTransition(
            "checklist incomplete: all attestations must be checked",
            details={"unchecked": unchecked},
        )

    # Authoritative: re-compute live category counts against on-disk segs.
    # The FE applies the same gate as a UX layer, but the server is the
    # source of truth — a race against unsaved edits or a stale snapshot
    # in the browser can mean the FE's view diverges.
    from services.validation import validate_reciter_segments

    result = validate_reciter_segments(slug)
    if result is None:
        raise InvalidTransition(
            "marked_ready blocked: no segments found on bucket"
        )
    counts = result.get("category_counts") or {}
    nonzero = {
        k: int(counts.get(k, 0))
        for k in BLOCKING_COUNT_KEYS
        if int(counts.get(k, 0)) > 0
    }
    if nonzero:
        raise InvalidTransition(
            "blocking validation counts must be zero before mark-ready",
            details={"blocking_counts": nonzero},
        )

    return _replace(before, marked_ready=True)


def _h_unmarked_ready(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.UNDER_REVIEW:
        raise InvalidTransition(
            f"unmarked_ready requires UNDER_REVIEW, got {before.state.value}"
        )
    _require_claim_holder(actor, before)
    if not before.marked_ready:
        raise InvalidTransition("not currently marked_ready")
    return _replace(before, marked_ready=False)


def _h_merge_rejected(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.UNDER_REVIEW or not before.marked_ready:
        raise InvalidTransition(
            "merge_rejected requires UNDER_REVIEW + marked_ready=true"
        )
    _require_maintainer(actor)
    _require_reason(reason, "merge_rejected")
    return _replace(before, marked_ready=False)


def _h_published(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.UNDER_REVIEW or not before.marked_ready:
        raise InvalidTransition(
            "published requires UNDER_REVIEW + marked_ready=true"
        )
    _require_maintainer(actor)
    # Side effects (bucket move, dispatch, TS job enqueue) are Phase 5+; here
    # we just write the state transition. revision_in_progress is cleared on
    # publish (if it was set by admin.unlocked_for_revision).
    return _replace(
        before,
        state=ReciterState.AWAITING_TIMESTAMPS,
        state_since=_now(),
        assignee_hf_id=None,
        assignee_login=None,
        assignee_since=None,
        marked_ready=False,
        revision_in_progress=None,
    )


def _h_timestamps_completed(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.AWAITING_TIMESTAMPS:
        raise InvalidTransition(
            f"timestamps_completed requires AWAITING_TIMESTAMPS, got {before.state.value}"
        )
    job_id = payload.get("job_id")
    job_ids = list(before.timestamps_job_ids)
    if job_id and job_id not in job_ids:
        job_ids.append(job_id)
    return _replace(
        before,
        state=ReciterState.RELEASED,
        state_since=_now(),
        timestamps_job_ids=job_ids,
        prefetch_purge_at=_now() + timedelta(days=7),
    )


def _h_unpublished(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.RELEASED:
        raise InvalidTransition(
            f"unpublished requires RELEASED, got {before.state.value}"
        )
    _require_maintainer(actor)
    _require_reason(reason, "unpublished")
    return _replace(
        before,
        state=ReciterState.AWAITING_REVIEW,
        state_since=_now(),
        revision_in_progress=None,
        prefetch_purge_at=None,
    )


def _h_unlocked_for_revision(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.RELEASED:
        raise InvalidTransition(
            f"unlocked_for_revision requires RELEASED, got {before.state.value}"
        )
    _require_maintainer(actor)
    context = RevisionContext(
        unlocked_from_state="released",
        unlocked_at=_now(),
        unlocked_by_hf_id=actor.hf_user_id,
        original_assignee_hf_id=None,
    )
    return _replace(
        before,
        state=ReciterState.AWAITING_REVIEW,
        state_since=_now(),
        revision_in_progress=context,
        prefetch_purge_at=None,
    )


def _h_discarded(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    _require_maintainer(actor)
    if before.visibility == Visibility.DISCARDED:
        raise InvalidTransition("already discarded")
    reason = _require_reason(reason, "discarded")
    return _replace(before, visibility=Visibility.DISCARDED, visibility_reason=reason)


def _h_undiscarded(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    _require_maintainer(actor)
    if before.visibility != Visibility.DISCARDED:
        raise InvalidTransition("not currently discarded")
    return _replace(before, visibility=Visibility.PUBLIC, visibility_reason=None)


def _h_force_released(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.UNDER_REVIEW:
        raise InvalidTransition(
            f"claim.force_released requires UNDER_REVIEW, got {before.state.value}"
        )
    # Owner-only: claim-mutation surfaces (force-release + reassign) are
    # an owner privilege; maintainers gate quality (send-back-to-UR) but
    # don't manage who reviews. See Reviews-tab plan §"Reassign popover".
    _require_owner(actor)
    # Reason is optional — the actor + slug + transition row already make
    # the action auditable. The route layer normalizes empty/short strings
    # to "" via validate_reason(required=False).
    return _replace(
        before,
        state=ReciterState.AWAITING_REVIEW,
        state_since=_now(),
        assignee_hf_id=None,
        assignee_login=None,
        assignee_since=None,
        marked_ready=False,
    )


def _h_reassigned(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.UNDER_REVIEW:
        raise InvalidTransition(
            f"claim.reassigned requires UNDER_REVIEW, got {before.state.value}"
        )
    # Owner-only — pairs with _h_force_released (see comment there).
    _require_owner(actor)
    new_hf = payload.get("new_assignee_hf_id")
    new_login = payload.get("new_assignee_login")
    if not new_hf or not new_login:
        raise InvalidTransition(
            "claim.reassigned requires payload "
            "{new_assignee_hf_id, new_assignee_login}"
        )
    # Reason is optional — pairs with _h_force_released (see comment there).
    return _replace(
        before,
        assignee_hf_id=new_hf,
        assignee_login=new_login,
        assignee_since=_now(),
        marked_ready=False,
    )


def _h_clear_prefetch_purge_at(slug, before, actor, payload, reason):
    """Sweeper-only event. Clears ``prefetch_purge_at`` after the audio +
    peaks directories are deleted, so the same row doesn't re-trigger on the
    next hourly tick. State-preserving."""
    if before is None:
        raise UnknownReciter(slug)
    if before.prefetch_purge_at is None:
        return before
    return _replace(before, prefetch_purge_at=None)


_HANDLERS: dict[str, Any] = {
    "catalog.added": _h_catalog_added,
    "catalog.edited": _h_catalog_edited,
    "reciter.requested": _h_requested,
    "reciter.request_rejected_soft": _h_request_rejected_soft,
    "reciter.request_rejected_hard": _h_request_rejected_hard,
    "reciter.alignment_completed": _h_alignment_completed,
    "reciter.claimed": _h_claimed,
    "reciter.released": _h_released,
    "reciter.marked_ready": _h_marked_ready,
    "reciter.unmarked_ready": _h_unmarked_ready,
    "reciter.merge_rejected": _h_merge_rejected,
    "reciter.published": _h_published,
    "reciter.timestamps_completed": _h_timestamps_completed,
    "reciter.unpublished": _h_unpublished,
    "reciter.discarded": _h_discarded,
    "reciter.undiscarded": _h_undiscarded,
    "claim.force_released": _h_force_released,
    "claim.reassigned": _h_reassigned,
    "admin.unlocked_for_revision": _h_unlocked_for_revision,
    "admin.clear_prefetch_purge_at": _h_clear_prefetch_purge_at,
}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _replace(row: ReciterRow, **changes: Any) -> ReciterRow:
    """Return a new ``ReciterRow`` with ``changes`` applied. Validates."""
    data = row.model_dump()
    data.update(changes)
    return ReciterRow.model_validate(data)


def has_other_active_claim(hf_user_id: str, *, except_slug: str | None = None) -> bool:
    """True if ``hf_user_id`` holds an open claim (other than ``except_slug``).
    Used to enforce one-claim-per-user — an O(1) index lookup on ``claims``."""
    held = repo_claims.open_claim_for_user(hf_user_id)
    if held is None:
        return False
    return held != except_slug
