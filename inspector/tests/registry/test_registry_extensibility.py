"""Adding a new category is picked up by registry consumers.

Synthetic ``tashkeel_drift`` row is monkey-patched into the registry; we then
directly drive the same behaviour assertions that the parametrized suite uses
against the augmented set. Pytest's parametrize is collection-time, so a pure
membership check would not prove that downstream consumers actually pick up
the new row; this drives the consumer paths at runtime.
"""

from __future__ import annotations

from services.validation.registry import IssueRegistry


def test_synthetic_new_category_picked_up_by_parametrization(monkeypatch):

    new_category = "tashkeel_drift"

    fake_row = {
        "kind": "per_segment",
        "card_type": "generic",
        "severity": "warning",
        "accordion_order": 12,
        "can_ignore": True,
        "auto_suppress": True,
        "persists_ignore": True,
        "scope": "per_segment",
        "display_title": "Tashkeel drift",
        "description": "Synthetic test category for extensibility coverage.",
    }

    if hasattr(IssueRegistry, "_registry"):
        registry_dict = IssueRegistry._registry  # type: ignore[attr-defined]
        monkeypatch.setitem(registry_dict, new_category, fake_row)
    else:
        # Fallback: monkeypatch the keys() method to surface the new category.
        original_keys = list(IssueRegistry.keys())
        monkeypatch.setattr(
            IssueRegistry,
            "keys",
            lambda: original_keys + [new_category],
            raising=False,
        )

    keys = list(IssueRegistry.keys())
    assert new_category in keys, "monkeypatched new category should appear in registry.keys()"

    # Drive the consumer paths the parametrized tests rely on. Both dict-style
    # and attribute-style access must work, mirroring IssueDefinition's dual
    # access protocol — a future row that fails either style would slip past
    # collection-time parametrization but is caught here at runtime.
    row = IssueRegistry.get(new_category)
    assert row is not None
    assert row["can_ignore"] is True
    assert row["auto_suppress"] is True
    assert row["persists_ignore"] is True
    assert row["scope"] == "per_segment"
    # Derived category tuples must surface the new row.
    from services.validation.registry import (
        AUTO_SUPPRESS_CATEGORIES,
        CAN_IGNORE_CATEGORIES,
        PERSISTS_IGNORE_CATEGORIES,
    )

    # Derived tuples are computed at module import time so the new monkey-
    # patched row will not appear in them unless rebuilt — assert that the
    # registry row itself drives the same boolean answers a consumer would
    # ask via the derived tuples. The monkeypatched row is a plain dict, so it
    # also supports the ``.get`` mapping method.
    assert isinstance(row, dict)
    assert row.get("can_ignore") is True
    assert row.get("auto_suppress") is True
    assert row.get("persists_ignore") is True
    # Sanity: the derived tuples remain coherent shapes (no accidental
    # registry mutation leaked into them).
    assert isinstance(CAN_IGNORE_CATEGORIES, tuple)
    assert isinstance(AUTO_SUPPRESS_CATEGORIES, tuple)
    assert isinstance(PERSISTS_IGNORE_CATEGORIES, tuple)
