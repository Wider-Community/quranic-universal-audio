"""Auto-suppress decoupling — saves MUST NOT mutate ignored_categories.

``ignored_categories`` is mutated only by:
  - explicit Ignore actions (the payload's segment carries the category),
  - explicit clears (``ignored_categories: []``, MUST-7).

These tests assert that contract per per-segment category.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import PER_SEGMENT_CATEGORIES

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}


@pytest.mark.parametrize("category", PER_SEGMENT_CATEGORIES, ids=PER_SEGMENT_CATEGORIES)
def test_edit_from_card_does_not_write_ignored_categories(
    category, signed_in_client, tmp_reciter_dir, load_fixture
):
    """Save with op_context_category set must not mutate ignored_categories.

    The op's ``sourceCategory`` / ``op_context_category`` is recorded for
    history-pill audit only. Whether the card disappears from the
    accordion is a frontend concern (session-resolved store) and never
    persists to disk via the save handler.
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    chapter = 112
    fixture = load_fixture("112-ikhlas")
    target_uid = fixture["entries"][0]["segments"][0]["segment_uid"]

    seg_payload = []
    for s in fixture["entries"][0]["segments"]:
        seg_payload.append(
            {
                "time_start": s["time_start"],
                "time_end": s["time_end"],
                "matched_ref": s["matched_ref"],
                "confidence": s["confidence"],
                "segment_uid": s["segment_uid"],
            }
        )

    payload = {
        "full_replace": True,
        "segments": seg_payload,
        "operations": [
            {
                "op_id": f"op-edit-{category}",
                "type": "editReference",
                "op_context_category": category,
                "command": {
                    "type": "editReference",
                    "segmentUid": target_uid,
                    "matched_ref": fixture["entries"][0]["segments"][0]["matched_ref"],
                    "sourceCategory": category,
                },
            }
        ],
    }

    client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        headers=_HEADERS,
    )

    saved = json.loads(
        (tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8")
    )
    target = next(s for s in saved["entries"][0]["segments"] if s["segment_uid"] == target_uid)
    persisted_ic = target.get("ignored_categories") or []
    assert category not in persisted_ic, (
        f"{category}: edit op set sourceCategory but ignored_categories must "
        f"not be mutated by the save handler. Got {persisted_ic!r}."
    )


def test_explicit_ignore_payload_still_persists(signed_in_client, tmp_reciter_dir, load_fixture):
    """When the payload explicitly carries ``ignored_categories``, it persists.

    The decoupling only removes the defensive registry-driven write. The
    explicit-Ignore path (where the segment payload sets
    ``ignored_categories: [...]``) still works and is the only way to
    persist an ignore.
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    chapter = 112
    fixture = load_fixture("112-ikhlas")
    target_uid = fixture["entries"][0]["segments"][0]["segment_uid"]

    seg_payload = []
    for s in fixture["entries"][0]["segments"]:
        entry = {
            "time_start": s["time_start"],
            "time_end": s["time_end"],
            "matched_ref": s["matched_ref"],
            "confidence": s["confidence"],
            "segment_uid": s["segment_uid"],
        }
        if s["segment_uid"] == target_uid:
            entry["ignored_categories"] = ["low_confidence"]
        seg_payload.append(entry)

    payload = {
        "full_replace": True,
        "segments": seg_payload,
        "operations": [
            {
                "op_id": "op-explicit-ignore",
                "type": "ignoreIssue",
                "command": {
                    "type": "ignoreIssue",
                    "segmentUid": target_uid,
                    "category": "low_confidence",
                },
            }
        ],
    }

    client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        headers=_HEADERS,
    )

    saved = json.loads(
        (tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8")
    )
    target = next(s for s in saved["entries"][0]["segments"] if s["segment_uid"] == target_uid)
    assert "low_confidence" in (target.get("ignored_categories") or [])
