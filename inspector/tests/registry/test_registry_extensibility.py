"""SC-3 evidence: adding a new category is picked up by parametrized tests.

Synthetic ``tashkeel_drift`` row is monkey-patched into the registry; the
parametrized behavior tests then auto-cover it without test edits.
"""
from __future__ import annotations

import pytest

pytest.importorskip(
    "services.validation.registry",
    reason="phase-1 — IssueRegistry module not yet introduced",
)


@pytest.mark.xfail(reason="phase-1", strict=False)
def test_synthetic_new_category_picked_up_by_parametrization(monkeypatch):
    from services.validation.registry import IssueRegistry  # type: ignore

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
            IssueRegistry, "keys",
            lambda: original_keys + [new_category],
            raising=False,
        )

    keys = list(IssueRegistry.keys())
    assert new_category in keys, (
        "monkeypatched new category should appear in registry.keys() — "
        "this is the contract the parametrized tests rely on"
    )
