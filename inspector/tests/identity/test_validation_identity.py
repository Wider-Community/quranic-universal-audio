"""Validation issue identity tests (IS-10, IS-11, MUST-9)."""
from __future__ import annotations

from pathlib import Path

from services.validation.detail import (
    filter_stale_issues,
    resolve_segment_by_uid,
    resolve_segment_for_issue,
)


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


def test_validation_response_carries_segment_uid(flask_client, tmp_reciter_dir):
    """Every issue item carries a segment_uid (or null for chapter-level)."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "synthetic-classifier")

    res = flask_client.get(f"/api/seg/validate/{reciter}")
    assert res.status_code == 200
    body = res.get_json()
    items = _issue_items(body)
    assert items, "no issue items returned by validate route"
    for item in items:
        assert "segment_uid" in item, f"issue item missing segment_uid: {item}"


def test_resolve_issue_uses_uid_first(flask_client, tmp_reciter_dir):
    """Backend exposes a uid-first resolver helper that returns the live segment for a given uid."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    fixture_uid = "019d5c88-f55f-7ee0-81d1-d99f423e8dd5"
    seg = resolve_segment_by_uid(reciter, fixture_uid)
    assert seg is not None
    assert seg.get("segment_uid") == fixture_uid


def test_resolve_issue_falls_back_to_seg_index_for_legacy_issues(flask_client, tmp_reciter_dir):
    """Issues without segment_uid still resolve via seg_index."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    legacy_issue = {"seg_index": 0, "chapter": 112}
    seg = resolve_segment_for_issue(reciter, legacy_issue)
    assert seg is not None


def test_stale_issue_filtered_after_split(flask_client, tmp_reciter_dir):
    """After a structural edit (split) the original-uid issue is filtered out."""
    issues = [{"segment_uid": "old", "category": "qalqala"}]
    live_uids = {"new-a", "new-b"}
    filtered = filter_stale_issues(issues, live_uids)
    assert filtered == [], "stale uid issue should be filtered out"


def test_stale_issue_filtered_after_delete(flask_client, tmp_reciter_dir):
    issues = [
        {"segment_uid": "deleted", "category": "qalqala"},
        {"segment_uid": "alive", "category": "low_confidence"},
    ]
    live_uids = {"alive"}
    filtered = filter_stale_issues(issues, live_uids)
    assert len(filtered) == 1
    assert filtered[0]["segment_uid"] == "alive"


def test_no_index_fixups_in_frontend_edit_utils():
    """The frontend's edit-utility tree must not reference any
    ``_fixupValIndicesFor*`` helper (they would re-introduce index-based
    issue resolution, which uid-first resolution replaces)."""
    repo_root = Path(__file__).resolve().parents[3]
    edit_dir = repo_root / "inspector" / "frontend" / "src" / "tabs" / "segments" / "utils" / "edit"
    leaks = []
    for path in edit_dir.rglob("*.ts"):
        text = path.read_text(encoding="utf-8")
        if "_fixupValIndicesFor" in text:
            leaks.append(str(path))
    assert not leaks, f"_fixupValIndicesFor* still referenced: {leaks}"
