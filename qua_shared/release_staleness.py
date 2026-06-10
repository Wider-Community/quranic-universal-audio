"""Release-staleness severity + reason→suggested-action registry.

The wire-facing types (``StaleReason``, ``SuggestedAction``) live in
``qua_shared/schemas/release.py`` (codegen'd to the FE). This module owns the
*logic* over them: how severe each reason is (used to pick a winner when a row
qualifies for staleness under more than one cause) and which remediation each
``(reason, track)`` maps to.

Extending the model is two edits: add a ``StaleReason`` member (+ its severity
here) and one ``_SUGGESTIONS`` row. The status route serializes the resolved
``SuggestedAction`` per stale row so the FE never reimplements the mapping.
"""

from __future__ import annotations

from .schemas.wire.release import StaleReason, SuggestedAction

# Higher wins when a row qualifies under multiple reasons. A ``ts_regen`` needs
# a full republish (which also refreshes the catalog), so it dominates a
# ``catalog_edit``; the catalog-refresh clear path relies on this ordering so it
# never clears a row that still needs a republish. ``segments_edited`` outranks
# both (regenerating timestamps subsumes a republish) — it lives on the ``ts``
# track and is computed, not stamped, so it never competes on a stamped row, but
# the ordering keeps the model coherent.
_SEVERITY: dict[StaleReason, int] = {
    StaleReason.CATALOG_EDIT: 1,
    StaleReason.TS_REGEN: 2,
    StaleReason.SEGMENTS_EDITED: 3,
}


def severity(reason: StaleReason | str | None) -> int:
    """Severity rank of a reason; 0 for unknown / None (never wins an upgrade)."""
    if reason is None:
        return 0
    try:
        return _SEVERITY[StaleReason(reason)]
    except (ValueError, KeyError):
        return 0


def more_severe(current: StaleReason | str | None, incoming: StaleReason) -> bool:
    """True iff ``incoming`` outranks ``current`` (so a stamp should upgrade)."""
    return severity(incoming) > severity(current)


def _actionable(action: str, label: str, capability: str | None) -> SuggestedAction:
    return SuggestedAction(action=action, kind="actionable", label=label, capability=capability)


def _informational(action: str, label: str) -> SuggestedAction:
    return SuggestedAction(action=action, kind="informational", label=label, capability=None)


# (reason, track) → remediation. ``hf`` catalog drift has a cheap dedicated
# action; everything GH is informational because cuts are immutable snapshots —
# the next cut reflects the change with no special operation.
_SUGGESTIONS: dict[tuple[StaleReason, str], SuggestedAction] = {
    (StaleReason.TS_REGEN, "hf"): _actionable(
        "republish_hf", "Republish to HF", "release.publish_hf"
    ),
    (StaleReason.TS_REGEN, "gh"): _informational("recut_gh", "Reflected on next cut"),
    (StaleReason.CATALOG_EDIT, "hf"): _actionable(
        "refresh_hf_catalog", "Refresh dataset catalog", "release.publish_hf"
    ),
    (StaleReason.CATALOG_EDIT, "gh"): _informational("recut_gh", "Reflected on next cut"),
    # ts-track only: the generated timestamps are behind the segments. Slug-scoped
    # remediation (the FE launcher passes the row's slug).
    (StaleReason.SEGMENTS_EDITED, "ts"): _actionable(
        "regenerate_ts", "Regenerate timestamps", "reviews.generate_timestamps"
    ),
}


def suggested_action(reason: StaleReason | str | None, track: str) -> SuggestedAction | None:
    """Resolve the remediation for a stale ``(reason, track)`` pair, or None."""
    if reason is None:
        return None
    try:
        return _SUGGESTIONS.get((StaleReason(reason), track))
    except ValueError:
        return None
