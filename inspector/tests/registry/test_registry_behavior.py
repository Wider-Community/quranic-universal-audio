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
    PER_SEGMENT_CATEGORIES,
    PER_VERSE_CATEGORIES,
    PER_CHAPTER_CATEGORIES,
)


def _registry():
    from services.validation.registry import IssueRegistry  # type: ignore
    return IssueRegistry


@pytest.mark.parametrize("category", ALL_CATEGORIES, ids=ALL_CATEGORIES)
@pytest.mark.xfail(reason="phase-1", strict=False)
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
        "matched_text": "x",
        "phonemes_asr": "",
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


@pytest.mark.parametrize("category", PER_SEGMENT_CATEGORIES, ids=PER_SEGMENT_CATEGORIES)
@pytest.mark.xfail(reason="phase-1", strict=False)
def test_auto_suppress_on_edit_per_segment_categories(category):
    """For per_segment C with auto_suppress=Y, an edit-from-card op writes C to seg.ignored_categories."""
    reg = _registry()
    row = reg[category]
    auto = getattr(row, "auto_suppress", None) or row["auto_suppress"]
    scope = getattr(row, "scope", None) or row["scope"]
    if scope != "per_segment":
        pytest.skip(f"{category} is not per_segment")

    from services.validation.registry import apply_auto_suppress  # type: ignore

    seg = {"ignored_categories": []}
    new = apply_auto_suppress(seg, category, edit_origin="card")
    if auto:
        assert category in (new.get("ignored_categories") or [])
    else:
        assert category not in (new.get("ignored_categories") or [])


@pytest.mark.parametrize(
    "category", PER_VERSE_CATEGORIES + PER_CHAPTER_CATEGORIES,
    ids=PER_VERSE_CATEGORIES + PER_CHAPTER_CATEGORIES,
)
@pytest.mark.xfail(reason="phase-1", strict=False)
def test_auto_suppress_is_noop_for_chapter_scope_categories(category):
    """For per_verse / per_chapter C, edit-from-card does NOT write to any ignored_categories.

    Re-validation on the next save cycle is the source of truth for whether the
    issue resolved.
    """
    from services.validation.registry import apply_auto_suppress  # type: ignore

    seg = {"ignored_categories": []}
    new = apply_auto_suppress(seg, category, edit_origin="card")
    assert (new.get("ignored_categories") or []) == [], (
        f"{category} is chapter-scope but auto_suppress wrote to ignored_categories"
    )


@pytest.mark.xfail(reason="phase-1", strict=False)
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
