"""Human-readable labels for the internal ``ReciterState`` lifecycle enum.

Used to build friendly denial messages + an ``error.context.state_label`` field
the frontend renders verbatim, so the FE never has to mirror the internal enum
vocabulary (its ``PUBLIC_BUCKET_LABELS`` is keyed on the *public* projection,
not these raw states). Cold-path only — built when a transition is rejected.
"""

from __future__ import annotations

from scripts.lib.schemas import ReciterState

STATE_LABELS: dict[ReciterState, str] = {
    ReciterState.CATALOGUED: "catalogued",
    ReciterState.AWAITING_ALIGNMENT: "awaiting alignment",
    ReciterState.AWAITING_REVIEW: "available for review",
    ReciterState.UNDER_REVIEW: "under review",
    ReciterState.RELEASED: "published",
}


def humanize_state(state: ReciterState | str | None) -> str:
    """Plain-language label for a state. Falls back to the raw value (with
    underscores spaced) for any unmapped/coerced input, never raising."""
    if state is None:
        return "unknown"
    if isinstance(state, ReciterState):
        return STATE_LABELS.get(state, state.value.replace("_", " "))
    # Tolerate a raw enum value string.
    try:
        return STATE_LABELS.get(ReciterState(state), str(state).replace("_", " "))
    except ValueError:
        return str(state).replace("_", " ")
