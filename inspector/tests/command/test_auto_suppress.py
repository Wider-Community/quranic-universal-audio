"""Auto-suppress tests parametrized over per-segment categories (Phase 3 — backend persistence side)."""
from __future__ import annotations

import json

import pytest

from tests.conftest import PER_SEGMENT_CATEGORIES, AUTO_SUPPRESS_CATEGORIES


@pytest.mark.parametrize("category", PER_SEGMENT_CATEGORIES, ids=PER_SEGMENT_CATEGORIES)
def test_edit_from_card_records_suppression_per_registry(
    category, flask_client, tmp_reciter_dir, load_fixture
):
    """The save handler derives auto-suppression from the registry, not the payload.

    When the frontend dispatches an "edit-from-card" command, the backend
    looks up the registry's ``auto_suppress`` flag for the given category
    and writes (or skips writing) ``ignored_categories`` accordingly.
    A payload that omits ``ignored_categories`` must still produce the
    correct on-disk value, driven entirely by the registry.
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112
    fixture = load_fixture("112-ikhlas")
    target_uid = fixture["entries"][0]["segments"][0]["segment_uid"]

    seg_payload = []
    for s in fixture["entries"][0]["segments"]:
        seg_payload.append({
            "time_start": s["time_start"],
            "time_end": s["time_end"],
            "matched_ref": s["matched_ref"],
            "matched_text": s["matched_text"],
            "confidence": s["confidence"],
            "phonemes_asr": s.get("phonemes_asr", ""),
            "segment_uid": s["segment_uid"],
        })

    payload = {
        "full_replace": True,
        "segments": seg_payload,
        "operations": [
            {
                "op_id": f"op-edit-{category}",
                "type": "editReference",
                "command": {
                    "type": "editReference",
                    "segmentUid": target_uid,
                    "matched_ref": fixture["entries"][0]["segments"][0]["matched_ref"],
                    "matched_text": "x",
                    "sourceCategory": category,
                },
            }
        ],
    }

    flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        content_type="application/json",
    )

    saved = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    target = next(s for s in saved["entries"][0]["segments"] if s["segment_uid"] == target_uid)
    persisted_ic = target.get("ignored_categories") or []

    persists_ignore = category in {
        "low_confidence", "repetitions", "audio_bleeding",
        "boundary_adj", "cross_verse", "qalqala",
    }
    if persists_ignore and category in AUTO_SUPPRESS_CATEGORIES:
        assert category in persisted_ic, (
            f"{category}: registry's auto_suppress should drive backend write — got {persisted_ic!r}"
        )
    else:
        assert category not in persisted_ic, (
            f"{category}: should NOT auto-suppress (registry says no); got {persisted_ic!r}"
        )
