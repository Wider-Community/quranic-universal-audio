"""detailed.json on-disk schema tests (MUST-2 — additive only)."""
from __future__ import annotations

import json

import pytest


KNOWN_SEGMENT_FIELDS = {
    "segment_uid",
    "time_start",
    "time_end",
    "matched_ref",
    "matched_text",
    "confidence",
    "phonemes_asr",
    "wrap_word_ranges",
    "has_repeated_words",
    "ignored_categories",
    "ignored",
    "audio_url",
}


def _segments(detailed: dict) -> list[dict]:
    out = []
    for entry in detailed.get("entries", []):
        for s in entry.get("segments", []):
            out.append(s)
    return out


def test_detailed_json_round_trip_preserves_known_fields(load_fixture, tmp_reciter_dir, flask_client):
    """Load fixture → save back → load → known fields equal."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    fixture = load_fixture("112-ikhlas")
    chapter = 112

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
    payload = {"full_replace": True, "segments": seg_payload, "operations": []}

    res = flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert res.status_code == 200

    out_path = tmp_reciter_dir.root / reciter / "detailed.json"
    saved = json.loads(out_path.read_text(encoding="utf-8"))

    saved_segs = saved["entries"][0]["segments"]
    assert len(saved_segs) == len(seg_payload)
    for orig, saved_seg in zip(fixture["entries"][0]["segments"], saved_segs):
        for key in ("segment_uid", "time_start", "time_end", "matched_ref"):
            assert saved_seg.get(key) == orig.get(key), (
                f"field {key} drifted across save: orig={orig.get(key)!r} saved={saved_seg.get(key)!r}"
            )


def test_detailed_json_no_field_removed(load_fixture):
    """Every field in the baseline fixture is recognized by KNOWN_SEGMENT_FIELDS."""
    fixture = load_fixture("112-ikhlas")
    for seg in _segments(fixture):
        unknown = set(seg.keys()) - KNOWN_SEGMENT_FIELDS
        assert not unknown, (
            f"unknown segment fields in fixture: {unknown}; update KNOWN_SEGMENT_FIELDS or "
            "remove them from the fixture"
        )


@pytest.mark.xfail(reason="phase-2", strict=False)
def test_detailed_json_additive_only_classified_issues_optional(load_fixture, tmp_reciter_dir, flask_client):
    """Phase 2: validation responses carry classified_issues — but it must NOT be persisted to detailed.json (MAY-10)."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    res = flask_client.get(f"/api/seg/validate/{reciter}")
    assert res.status_code == 200

    on_disk = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    for seg in _segments(on_disk):
        assert "classified_issues" not in seg, (
            "MUST-2 violation: classified_issues should never be persisted into detailed.json — "
            "it lives only on validation responses + history snapshots (MAY-10)."
        )
