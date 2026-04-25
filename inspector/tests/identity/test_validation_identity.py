"""Validation issue identity tests (IS-10, IS-11, MUST-9)."""
from __future__ import annotations

import json

import pytest


def _issue_items(body) -> list[dict]:
    items: list[dict] = []
    if isinstance(body, dict):
        for v in body.values():
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        items.append(item)
            elif isinstance(v, dict):
                items.extend(_issue_items(v))
    return items


@pytest.mark.xfail(reason="phase-6", strict=False)
def test_validation_response_carries_segment_uid(flask_client, tmp_reciter_dir):
    """Phase 6: every issue item carries a segment_uid (or null for chapter-level)."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "synthetic-classifier")

    res = flask_client.get(f"/api/seg/validate/{reciter}")
    assert res.status_code == 200
    body = res.get_json()
    items = _issue_items(body)
    assert items, "no issue items returned by validate route"
    for item in items:
        assert "segment_uid" in item, f"issue item missing segment_uid: {item}"


@pytest.mark.xfail(reason="phase-6", strict=False)
def test_resolve_issue_uses_uid_first(flask_client, tmp_reciter_dir):
    """Backend exposes a uid-first resolver helper that returns the live segment for a given uid."""
    pytest.importorskip(
        "services.validation.detail",
        reason="phase-6 — Phase 6 introduces uid resolution surface",
    )
    from services.validation.detail import resolve_segment_by_uid  # type: ignore
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    fixture_uid = "019d5c88-f55f-7ee0-81d1-d99f423e8dd5"
    seg = resolve_segment_by_uid(reciter, fixture_uid)
    assert seg is not None
    assert seg.get("segment_uid") == fixture_uid


@pytest.mark.xfail(reason="phase-6", strict=False)
def test_resolve_issue_falls_back_to_seg_index_for_legacy_issues(flask_client, tmp_reciter_dir):
    """Issues without segment_uid (legacy response shape) still resolve via seg_index."""
    pytest.importorskip(
        "services.validation.detail",
        reason="phase-6 — uid resolution surface not yet present",
    )
    from services.validation.detail import resolve_segment_for_issue  # type: ignore
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    legacy_issue = {"seg_index": 0, "chapter": 112}
    seg = resolve_segment_for_issue(reciter, legacy_issue)
    assert seg is not None


@pytest.mark.xfail(reason="phase-6", strict=False)
def test_stale_issue_filtered_after_split(flask_client, tmp_reciter_dir):
    """After a structural edit (split) the original-uid issue is filtered, not rendered."""
    pytest.importorskip(
        "services.validation.detail",
        reason="phase-6 — stale-filter surface not yet present",
    )
    from services.validation.detail import filter_stale_issues  # type: ignore

    issues = [{"segment_uid": "old", "category": "qalqala"}]
    live_uids = {"new-a", "new-b"}
    filtered = filter_stale_issues(issues, live_uids)
    assert filtered == [], "stale uid issue should be filtered out"


@pytest.mark.xfail(reason="phase-6", strict=False)
def test_stale_issue_filtered_after_delete(flask_client, tmp_reciter_dir):
    pytest.importorskip(
        "services.validation.detail",
        reason="phase-6 — stale-filter surface not yet present",
    )
    from services.validation.detail import filter_stale_issues  # type: ignore

    issues = [
        {"segment_uid": "deleted", "category": "qalqala"},
        {"segment_uid": "alive", "category": "low_confidence"},
    ]
    live_uids = {"alive"}
    filtered = filter_stale_issues(issues, live_uids)
    assert len(filtered) == 1
    assert filtered[0]["segment_uid"] == "alive"


@pytest.mark.xfail(reason="phase-6", strict=False)
def test_no_index_fixups_after_phase_6():
    """Phase 6 deletes _fixupValIndicesFor* helpers; they must not be referenced."""
    repo_root = __file__
    import os
    while os.path.basename(repo_root) != "inspiring-ramanujan-2d4e7e" and len(repo_root) > 3:
        repo_root = os.path.dirname(repo_root)
    edit_dir = os.path.join(
        repo_root, "inspector", "frontend", "src", "tabs", "segments", "utils", "edit"
    )
    leaks = []
    for root, _, files in os.walk(edit_dir):
        for fn in files:
            if not fn.endswith(".ts"):
                continue
            text = open(os.path.join(root, fn), encoding="utf-8").read()
            if "_fixupValIndicesFor" in text:
                leaks.append(os.path.join(root, fn))
    assert not leaks, f"_fixupValIndicesFor* still referenced: {leaks}"
