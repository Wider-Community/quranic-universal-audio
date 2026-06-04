"""Parametrized behavioral tests: registry → consequences.

For every category, assert that the runtime behavior (save serialization,
auto-suppress on edit, no-op for chapter-scope, etc.) is driven by the
registry, not by hard-coded category checks.
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "services.validation.registry",
    reason="phase-1 — IssueRegistry module not yet introduced",
)

from tests.conftest import (
    ALL_CATEGORIES,
    PER_CHAPTER_CATEGORIES,
    PER_SEGMENT_CATEGORIES,
    PER_VERSE_CATEGORIES,
)


def _registry():
    from services.validation.registry import IssueRegistry  # type: ignore

    return IssueRegistry


@pytest.mark.parametrize("category", ALL_CATEGORIES, ids=ALL_CATEGORIES)
def test_can_ignore_drives_save_serialization(category):
    """For category C, save serializes ignored_categories iff registry[C].persists_ignore."""
    reg = _registry()
    row = reg[category]
    persists = getattr(row, "persists_ignore", None)
    if persists is None:
        persists = row["persists_ignore"]

    from services.save import _make_seg

    seg_input = {
        "time_start": 0,
        "time_end": 1000,
        "matched_ref": "1:1:1-1:1:1",
        "confidence": 1.0,
        "segment_uid": "test-uid",
        "ignored_categories": [category],
    }
    out = _make_seg(seg_input, {}, {})
    serialized = out.get("ignored_categories", [])
    if persists:
        assert category in serialized, (
            f"category {category} has persists_ignore=True but was not serialized"
        )
    else:
        assert category not in serialized, (
            f"category {category} has persists_ignore=False but was serialized"
        )


def test_apply_auto_suppress_helper_is_gone():
    """The backend ``apply_auto_suppress`` helper has been removed.

    Editing no longer mutates ``ignored_categories`` -- that contract is
    reserved for explicit Ignore actions. Card dismissal for soft-rule
    categories is handled by the frontend session-resolved store.
    """
    from services.validation import registry as reg_mod  # type: ignore

    assert not hasattr(reg_mod, "apply_auto_suppress"), (
        "apply_auto_suppress must not exist: edits no longer mutate "
        "ignored_categories. Soft-rule card dismissal is a frontend-only concern."
    )


def test_view_only_was_dropped():
    """Registry has no view_only field; only can_ignore controls Ignore button visibility."""
    reg = _registry()
    for cat in ALL_CATEGORIES:
        row = reg[cat]
        assert not hasattr(row, "view_only"), (
            f"{cat}: view_only field should not exist on registry rows (dropped per Stage 0 Q10)"
        )
        if isinstance(row, dict):
            assert "view_only" not in row, (
                f"{cat}: view_only key should not exist (dropped per Stage 0 Q10)"
            )
