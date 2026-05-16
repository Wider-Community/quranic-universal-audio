"""Pure authorization predicates — single source for role + reason checks.

This module owns the *data-level* questions ("does this actor have role X?",
"is this reason long enough?", "does this actor own this row's claim?") and
deliberately does NOT own error contracts. Callers translate predicate
results into the error shape their layer needs:

- ``services/state.py`` raises ``NotAuthorizedForTransition`` / ``InvalidTransition``.
- ``routes/_admin_helpers.py`` returns Flask ``(jsonify, 403/400)`` tuples.
- ``utils/decorators.py`` calls ``flask.abort(403)``.

No Flask imports here. No exceptions raised for domain conditions — only for
programmer errors (a malformed role string is a bug, not a 403).
"""

from __future__ import annotations

from typing import Any

from scripts.lib.schemas import Role


MIN_REASON_CHARS = 10


def role_of(obj: Any) -> Role:
    """Return the ``Role`` enum for ``obj.role`` regardless of how it arrives.

    ``Actor`` from pydantic gives us a string (str-Enum value); ``User`` from
    the auth dataclass may give us a string or a ``Role``. Normalize once
    here so every other predicate can compare against ``Role.*`` directly.

    Raises ``ValueError`` if ``obj.role`` can't be coerced — that's a
    programmer error (malformed input from a caller), not a domain refusal.
    """
    raw = getattr(obj, "role", None)
    if raw is None:
        raise ValueError(f"{obj!r} has no .role attribute")
    if isinstance(raw, Role):
        return raw
    # Role is a str-Enum, so Role(string_value) is the canonical constructor.
    return Role(raw)


def is_owner(obj: Any) -> bool:
    return role_of(obj) == Role.OWNER


def is_maintainer(obj: Any) -> bool:
    """True for MAINTAINER or OWNER — the elevated-action tier."""
    return role_of(obj) in (Role.MAINTAINER, Role.OWNER)


def is_contributor_or_higher(obj: Any) -> bool:
    """True for any recognized role. Useful only as a sanity check that the
    actor isn't anonymous — auth gates already enforce signed-in at the
    HTTP edge.
    """
    return role_of(obj) in (Role.CONTRIBUTOR, Role.MAINTAINER, Role.OWNER)


def has_role(obj: Any, *allowed: Role) -> bool:
    """Generic membership test. ``allowed`` is a Role-tuple."""
    return role_of(obj) in allowed


def is_claim_holder(obj: Any, row: Any) -> bool:
    """True iff ``row.assignee_hf_id`` matches ``obj.hf_user_id``.

    Compares ``hf_user_id`` (canonical, immutable) — never ``login`` (mutable
    on HF). Returns False when the row has no assignee.
    """
    assignee = getattr(row, "assignee_hf_id", None)
    caller_id = getattr(obj, "hf_user_id", None)
    if assignee is None or caller_id is None:
        return False
    return assignee == caller_id


def is_claim_holder_or_maintainer(obj: Any, row: Any) -> bool:
    return is_maintainer(obj) or is_claim_holder(obj, row)


def normalize_reason(
    raw: str | None,
    *,
    min_chars: int = MIN_REASON_CHARS,
) -> str | None:
    """Trim ``raw`` and return it if it meets ``min_chars``; else None.

    Callers decide what ``None`` means in their context — HTTP 400, a domain
    exception, or "skip the optional reason."
    """
    if raw is None:
        return None
    trimmed = raw.strip()
    if len(trimmed) < min_chars:
        return None
    return trimmed
