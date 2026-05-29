"""Server-side predicates for the ``/api/reciter-task/<slug>`` response.

Mirror of the spec in inspector-state-management.md §8 plus
``can_edit_as_admin`` (maintainer/owner override on UNDER_REVIEW rows) and
``can_edit_as_owner`` (owner editing any public row regardless of state or
marked_ready freeze — owner override is total).

Pure functions: each takes the row + optional ``User`` and returns ``bool``.
Anonymous (``user is None``) always yields ``False`` for any contribution
predicate. The frontend trusts these predicates to drive visibility but the
backend is authoritative — every mutating route re-checks state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.lib.schemas import ReciterState, Visibility

from . import permissions

if TYPE_CHECKING:  # pragma: no cover
    from scripts.lib.schemas import ReciterRow

    from .auth import User


def _is_admin(user) -> bool:
    if user is None or getattr(user, "role", None) is None:
        return False
    return permissions.is_maintainer(user)


def can_claim(row, user, *, has_other_active_claim: bool = False) -> bool:
    """``awaiting_review`` + ``public`` + signed in + (owner or no other active claim)."""
    if user is None or row is None:
        return False
    if row.state != ReciterState.AWAITING_REVIEW:
        return False
    if row.visibility != Visibility.PUBLIC:
        return False
    if permissions.is_owner(user):
        return True  # owners exempt from one-claim-per-user rule
    return not has_other_active_claim


def can_edit(row, user) -> bool:
    """Active reviewer of the ``under_review`` row, not yet ``marked_ready``."""
    if user is None or row is None:
        return False
    return (
        row.state == ReciterState.UNDER_REVIEW
        and not row.marked_ready
        and row.visibility == Visibility.PUBLIC
        and permissions.is_claim_holder(user, row)
    )


def can_edit_as_admin(row, user) -> bool:
    """Maintainer / owner editing any active claim row (admin override)."""
    if not _is_admin(user) or row is None:
        return False
    return (
        row.state == ReciterState.UNDER_REVIEW
        and not row.marked_ready
        and row.visibility == Visibility.PUBLIC
    )


def can_edit_as_owner(row, user) -> bool:
    """Owner editing any public reciter, regardless of state or marked_ready."""
    if user is None or row is None or not permissions.is_owner(user):
        return False
    return row.visibility == Visibility.PUBLIC


def can_mark_ready(row, user) -> bool:
    """Same gate as can_edit + the row isn't already marked."""
    if not can_edit(row, user):
        return False
    return not row.marked_ready


def can_unmark_ready(row, user) -> bool:
    """Reviewer can flip ready=False back to make edits."""
    if user is None or row is None:
        return False
    return (
        row.state == ReciterState.UNDER_REVIEW
        and row.marked_ready
        and permissions.is_claim_holder(user, row)
    )


def can_release(row, user) -> bool:
    """Reviewer can release their own claim BEFORE they mark it ready.

    Once marked_ready is True the row is in a terminal-for-reviewer state:
    only ``can_unmark_ready`` (back out) or an admin force-release moves it.
    Surfacing Unclaim here would let a reviewer skip the unmark step and
    leave a stale ``marked_ready_at`` on a closed claim history row.
    """
    if user is None or row is None:
        return False
    return (
        row.state == ReciterState.UNDER_REVIEW
        and not row.marked_ready
        and permissions.is_claim_holder(user, row)
    )


def build_predicates(row, user, *, has_other_active_claim: bool) -> dict:
    """Return a JSON-serialisable map of every predicate for the response.

    Centralizes the predicate set so route handlers don't drift.
    """
    return {
        "can_claim": can_claim(row, user, has_other_active_claim=has_other_active_claim),
        "can_edit": can_edit(row, user),
        "can_edit_as_admin": can_edit_as_admin(row, user),
        "can_edit_as_owner": can_edit_as_owner(row, user),
        "can_mark_ready": can_mark_ready(row, user),
        "can_unmark_ready": can_unmark_ready(row, user),
        "can_release": can_release(row, user),
    }
