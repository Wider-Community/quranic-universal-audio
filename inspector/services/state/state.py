"""Reciter state service: ``<bucket>/state/reciter_state.json``.

Single source of truth for reciter lifecycle + assignee. Inspector backend
is sole writer. Per-slug ``threading.Lock`` serializes concurrent writes
against the same slug; different slugs run independently.

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
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, TypedDict

from pydantic import ValidationError

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
from services.storage import storage_paths
from services.storage.hf_bucket import StorageNotFound, get_backend

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

    The in-memory store and on-bucket file are unchanged; no audit entry is
    written. Callers should surface HTTP 400 with the message.
    """


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


class BatchTimestampsRefreshPayload(TypedDict):
    job_id: str


class PublishedEditedPayload(TypedDict, total=False):
    batch_id: str


class DiscardedPayload(TypedDict, total=False):
    pass


class ForceSetStatePayload(TypedDict):
    to_state: str


class SeededPayload(TypedDict, total=False):
    pass


# ----------------------------------------------------------------------
# Allowed pairs for admin.force_set_state
# ----------------------------------------------------------------------


# Per state-mgmt outcomes log (Phase 1 reconciliation): the canonical
# allowed-pair set.
_FORCE_SET_STATE_ALLOWED: frozenset[tuple[str, str]] = frozenset(
    {
        # bidirectional
        (ReciterState.CATALOGUED.value, ReciterState.AWAITING_ALIGNMENT.value),
        (ReciterState.AWAITING_ALIGNMENT.value, ReciterState.CATALOGUED.value),
        (
            ReciterState.AWAITING_ALIGNMENT.value,
            ReciterState.AWAITING_REVIEW.value,
        ),
        (
            ReciterState.AWAITING_REVIEW.value,
            ReciterState.AWAITING_ALIGNMENT.value,
        ),
        (
            ReciterState.AWAITING_TIMESTAMPS.value,
            ReciterState.RELEASED.value,
        ),
        (
            ReciterState.RELEASED.value,
            ReciterState.AWAITING_TIMESTAMPS.value,
        ),
        (ReciterState.RELEASED.value, ReciterState.COMPLETED.value),
        (ReciterState.COMPLETED.value, ReciterState.RELEASED.value),
        # one-directional
        (ReciterState.UNDER_REVIEW.value, ReciterState.AWAITING_REVIEW.value),
    }
)


# ----------------------------------------------------------------------
# In-memory store
# ----------------------------------------------------------------------


_state_file: ReciterStateFile = ReciterStateFile()
_state_lock = threading.Lock()  # guards _state_file replacement
_slug_locks: dict[str, threading.Lock] = {}
_slug_locks_lock = threading.Lock()  # guards _slug_locks dict mutation
_hydrated = False  # flips True on first successful hydrate(); /healthz reads this


def _get_slug_lock(slug: str) -> threading.Lock:
    with _slug_locks_lock:
        lock = _slug_locks.get(slug)
        if lock is None:
            lock = threading.Lock()
            _slug_locks[slug] = lock
        return lock


def hydrate() -> None:
    """Load or initialize the state file from the bucket. Idempotent."""
    global _state_file, _hydrated
    backend = get_backend()
    try:
        raw = backend.read_json(storage_paths.state_path())
        loaded = ReciterStateFile.model_validate(raw)
    except StorageNotFound:
        logger.warning(
            "state: state file missing on bucket; initializing empty in-memory "
            "store. Seed via `.local/inspector-deploy/v2/seed_state.py`."
        )
        loaded = ReciterStateFile()
    except ValidationError as e:
        logger.exception("state: invalid bucket state file — refusing to hydrate")
        raise InvalidTransition(str(e)) from e
    with _state_lock:
        _state_file = loaded
        _hydrated = True


def is_hydrated() -> bool:
    """Return True if the state file was loaded from (or initialized against) the bucket."""
    with _state_lock:
        return _hydrated


def snapshot() -> ReciterStateFile:
    with _state_lock:
        return _state_file.model_copy(deep=True)


def get_row(slug: str) -> ReciterRow | None:
    with _state_lock:
        return _state_file.find(slug)


def kind_for(slug: str) -> str | None:
    """Return ``"wip"`` or ``"published"`` for ``slug`` based on its lifecycle.

    Returns ``None`` if the slug isn't tracked. Used by routes that need to
    pick a bucket subtree at runtime without hard-coding state knowledge.
    """
    row = get_row(slug)
    if row is None:
        return None
    if row.state in (
        ReciterState.RELEASED,
        ReciterState.COMPLETED,
    ):
        return "published"
    return "wip"


def all_rows() -> list[ReciterRow]:
    with _state_lock:
        return list(_state_file.reciters)


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
# Dispatch
# ----------------------------------------------------------------------


# Post-transition observer registry. Hooks fire AFTER the row is persisted
# and the audit record is appended; they receive ``(before, after, event,
# actor)``. Used by ``services.audio_prefetch`` to enqueue prefetch jobs and
# similar lifecycle reactions. Failures in hooks are logged but never raised
# back to the caller — the transition itself already committed.
TransitionHook = Callable[[ReciterRow | None, ReciterRow, str, Actor], None]
_TRANSITION_HOOKS: list[TransitionHook] = []


def register_transition_hook(fn: TransitionHook) -> None:
    """Register a post-transition observer. Idempotent on identity."""
    if fn not in _TRANSITION_HOOKS:
        _TRANSITION_HOOKS.append(fn)


def clear_transition_hooks() -> None:
    """Drop all registered hooks. For tests."""
    _TRANSITION_HOOKS.clear()


# ----------------------------------------------------------------------
# Auto-claim queue — stashed in `_h_alignment_completed` and consumed by
# the post-transition hook so the second `reciter.claimed` transition can
# acquire the slug lock fresh (the handler ran inside it).
# ----------------------------------------------------------------------


_AUTO_CLAIM_QUEUE: dict[str, Actor] = {}
_auto_claim_lock = threading.Lock()


def _auto_claim_hook(
    before: ReciterRow | None,
    new_row: ReciterRow,
    event: str,
    actor: Actor,  # noqa: ARG001 — unused; system actor fired alignment_completed
) -> None:
    """When ``reciter.alignment_completed`` fires for a slug whose pending
    request was submitted with ``auto_claim=True``, fire a follow-up
    ``reciter.claimed`` on the requester's behalf.

    Owner exemption: owners may hold multiple simultaneous claims (matches
    the policy gate in ``services.auth.predicates.can_claim`` and the
    manual ``/api/claim/<slug>`` route), so the one-claim check below is
    skipped for them.

    For non-owners holding another active claim, an audit record
    (``reciter.auto_claim_skipped``) is appended so the skip is
    inspectable later instead of being a silent INFO log only.
    """
    if event != "reciter.alignment_completed":
        return
    with _auto_claim_lock:
        requester = _AUTO_CLAIM_QUEUE.pop(new_row.slug, None)
    if requester is None:
        return

    existing_claim_slug: str | None = None
    if not permissions.is_owner(requester):
        existing_claim_slug = next(
            (
                r.slug for r in all_rows()
                if r.state == ReciterState.UNDER_REVIEW
                and r.assignee_hf_id == requester.hf_user_id
                and r.slug != new_row.slug
            ),
            None,
        )
    if existing_claim_slug is not None:
        logger.info(
            "auto_claim: %s already holds claim on %s; skipping auto-claim of %s",
            requester.hf_user_id,
            existing_claim_slug,
            new_row.slug,
        )
        try:
            audit.append(
                event="reciter.auto_claim_skipped",
                actor=requester,
                slug=new_row.slug,
                payload={
                    "reason": "other_active_claim",
                    "existing_claim_slug": existing_claim_slug,
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "auto_claim: failed to write skip audit for slug=%s",
                new_row.slug,
            )
        return
    try:
        transition(
            new_row.slug,
            "reciter.claimed",
            actor=requester,
            payload={
                "assignee_hf_id": requester.hf_user_id,
                "assignee_login": requester.login_at_time,
            },
        )
    except StateError:
        logger.exception(
            "auto_claim: claim transition failed for slug=%s requester=%s",
            new_row.slug,
            requester.hf_user_id,
        )


_TRANSITION_HOOKS.append(_auto_claim_hook)


def transition(
    slug: str,
    event: str,
    *,
    actor: Actor,
    payload: dict[str, Any] | None = None,
    reason: str | None = None,
) -> ReciterRow:
    """Apply a slug-bound transition. Returns the new row.

    For non-slug-bound events (access.*, catalog.audio_source_added) callers
    should use the relevant service module instead — those don't touch the
    state file.
    """
    payload = payload or {}
    handler = _HANDLERS.get(event)
    if handler is None:
        raise UnknownEvent(f"unknown slug-bound event {event!r}")

    slug_lock = _get_slug_lock(slug)
    with slug_lock:
        before = get_row(slug)
        new_row = handler(slug, before, actor, payload, reason)
        _persist_row(new_row, replace_existing=before is not None)

    audit.append(
        event=event,
        actor=actor,
        slug=slug,
        from_state=before.state.value if before is not None else None,
        to_state=new_row.state.value,
        payload=payload,
        reason=reason,
    )

    for hook in _TRANSITION_HOOKS:
        try:
            hook(before, new_row, event, actor)
        except Exception:  # noqa: BLE001
            logger.exception(
                "post-transition hook %r failed for slug=%s event=%s",
                getattr(hook, "__name__", hook),
                slug,
                event,
            )

    return new_row


def _persist_row(row: ReciterRow, *, replace_existing: bool) -> None:
    """Replace (or insert) a row, persist + replace in-memory model atomically."""
    global _state_file
    with _state_lock:
        new_file = _state_file.model_copy(deep=True)
        if replace_existing:
            for i, existing in enumerate(new_file.reciters):
                if existing.slug == row.slug:
                    new_file.reciters[i] = row
                    break
        else:
            new_file.reciters.append(row)

        try:
            new_file = ReciterStateFile.model_validate(new_file.model_dump(mode="json"))
        except ValidationError as e:
            raise InvalidTransition(str(e)) from e

        backend = get_backend()
        backend.write_json_atomic(
            storage_paths.state_path(),
            new_file.model_dump(mode="json"),
        )
        _state_file = new_file


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
    produced files under ``wip/<slug>/`` and the row is ready for human
    review.

    Side effect: if a pending user request exists for this slug, applies the
    proposed catalog edits (riwayah/style/recording_*/names/country) at the
    same time so the catalog reflects whatever the requester proposed before
    the row leaves AWAITING_ALIGNMENT. See ``services.pending_requests``.
    The pending entry is cleared regardless of whether edits applied
    cleanly — catalog failures are logged but don't block the transition.

    If the pending request carried ``auto_claim=True``, the requester is
    stashed in ``_AUTO_CLAIM_QUEUE`` keyed by slug — the post-transition
    hook ``_auto_claim_hook`` then fires ``reciter.claimed`` on the
    requester's behalf once this transition has fully persisted. Skipping
    silently if they already hold another active claim.
    """
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.AWAITING_ALIGNMENT:
        raise InvalidTransition(
            f"alignment_completed requires AWAITING_ALIGNMENT, got {before.state.value}"
        )

    # Capture the auto_claim requester (if any) BEFORE apply_and_archive_completed
    # archives + clears the pending entry.
    # Imported here (not at module top) to avoid a circular import:
    # pending_requests → catalog → audit; audit doesn't touch state.
    from . import pending_requests as _pending_requests
    pending = _pending_requests.get(slug)
    if pending is not None and pending.auto_claim:
        with _auto_claim_lock:
            _AUTO_CLAIM_QUEUE[slug] = pending.requester

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

    # Persist the pending entry *inside* the slug lock so a second concurrent
    # request fails the get() check above. If _persist_row fails downstream,
    # the entry will be cleaned up the next time the slug is rejected — or
    # rebuildable from the audit log.
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
    _require_maintainer(actor)
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
    _require_maintainer(actor)
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
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.UNDER_REVIEW:
        raise InvalidTransition(
            f"marked_ready requires UNDER_REVIEW, got {before.state.value}"
        )
    _require_claim_holder(actor, before)
    if before.marked_ready:
        raise InvalidTransition("already marked_ready")
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


def _h_dataset_published(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.RELEASED:
        raise InvalidTransition(
            f"dataset_published requires RELEASED, got {before.state.value}"
        )
    _require_maintainer(actor)
    return _replace(before, state=ReciterState.COMPLETED, state_since=_now())


def _h_removed_from_dataset(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state != ReciterState.COMPLETED:
        raise InvalidTransition(
            f"removed_from_dataset requires COMPLETED, got {before.state.value}"
        )
    _require_maintainer(actor)
    _require_reason(reason, "removed_from_dataset")
    return _replace(before, state=ReciterState.RELEASED, state_since=_now())


def _h_unpublished(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state not in (ReciterState.RELEASED, ReciterState.COMPLETED):
        raise InvalidTransition(
            f"unpublished requires RELEASED or COMPLETED, got {before.state.value}"
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
    if before.state not in (ReciterState.RELEASED, ReciterState.COMPLETED):
        raise InvalidTransition(
            f"unlocked_for_revision requires RELEASED or COMPLETED, got "
            f"{before.state.value}"
        )
    _require_maintainer(actor)
    context = RevisionContext(
        unlocked_from_state="completed"
        if before.state == ReciterState.COMPLETED
        else "released",
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


def _h_seeded(slug, before, actor, payload, reason):
    """One-shot cutover seed event. Allows any state; emitted by the seed
    script with ``actor.role = OWNER``. Does not change state.
    """
    if before is None:
        raise UnknownReciter(slug)
    _require_maintainer(actor)
    return before


def _h_published_edited(slug, before, actor, payload, reason):
    """Maintainer direct-edit save on a released/completed reciter. State-
    preserving — audit-only. Inspector save flow fires this event per batch.
    """
    if before is None:
        raise UnknownReciter(slug)
    if before.state not in (ReciterState.RELEASED, ReciterState.COMPLETED):
        raise InvalidTransition(
            "published.edited requires RELEASED or COMPLETED"
        )
    _require_maintainer(actor)
    return _replace(before, last_save_at=_now())


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
    _require_maintainer(actor)
    _require_reason(reason, "claim.force_released")
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
    _require_maintainer(actor)
    new_hf = payload.get("new_assignee_hf_id")
    new_login = payload.get("new_assignee_login")
    if not new_hf or not new_login:
        raise InvalidTransition(
            "claim.reassigned requires payload "
            "{new_assignee_hf_id, new_assignee_login}"
        )
    _require_reason(reason, "claim.reassigned")
    return _replace(
        before,
        assignee_hf_id=new_hf,
        assignee_login=new_login,
        assignee_since=_now(),
        marked_ready=False,
    )


def _h_force_set_state(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    _require_maintainer(actor)
    target = payload.get("to_state")
    if not target:
        raise InvalidTransition("force_set_state requires payload.to_state")
    pair = (before.state.value, target)
    if pair not in _FORCE_SET_STATE_ALLOWED:
        raise InvalidTransition(
            f"force_set_state pair {pair} not in allowed set"
        )
    _require_reason(reason, "force_set_state")
    return _replace(
        before,
        state=ReciterState(target),
        state_since=_now(),
        # Clear assignee fields when leaving under_review to avoid invariant
        # violations on the resulting row.
        **(
            {
                "assignee_hf_id": None,
                "assignee_login": None,
                "assignee_since": None,
                "marked_ready": False,
            }
            if before.state == ReciterState.UNDER_REVIEW
            else {}
        ),
    )


def _h_batch_timestamps_refresh(slug, before, actor, payload, reason):
    if before is None:
        raise UnknownReciter(slug)
    if before.state not in (ReciterState.RELEASED, ReciterState.COMPLETED):
        raise InvalidTransition(
            "batch_timestamps_refresh requires RELEASED or COMPLETED"
        )
    _require_maintainer(actor)
    job_id = payload.get("job_id")
    if not job_id:
        raise InvalidTransition("batch_timestamps_refresh requires payload.job_id")
    job_ids = list(before.timestamps_job_ids)
    if job_id not in job_ids:
        job_ids.append(job_id)
    return _replace(before, timestamps_job_ids=job_ids)


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
    "reciter.dataset_published": _h_dataset_published,
    "reciter.removed_from_dataset": _h_removed_from_dataset,
    "reciter.unpublished": _h_unpublished,
    "reciter.seeded": _h_seeded,
    "reciter.discarded": _h_discarded,
    "reciter.undiscarded": _h_undiscarded,
    "published.edited": _h_published_edited,
    "claim.force_released": _h_force_released,
    "claim.reassigned": _h_reassigned,
    "admin.force_set_state": _h_force_set_state,
    "admin.unlocked_for_revision": _h_unlocked_for_revision,
    "admin.batch_timestamps_refresh": _h_batch_timestamps_refresh,
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
    """True if ``hf_user_id`` is assignee on any UNDER_REVIEW row (other than
    ``except_slug``). Used to enforce one-claim-per-user.
    """
    for row in all_rows():
        if row.state != ReciterState.UNDER_REVIEW:
            continue
        if row.slug == except_slug:
            continue
        if row.assignee_hf_id == hf_user_id:
            return True
    return False
