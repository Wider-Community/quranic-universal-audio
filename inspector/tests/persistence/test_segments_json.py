"""segments.json rebuild tests (MUST-3)."""
from __future__ import annotations

import json


def test_segments_json_rebuild_parity(load_fixture, tmp_reciter_dir, flask_client):
    """Load detailed.json → save → segments.json key set + tuples match expected."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112

    fixture = load_fixture("112-ikhlas")
    seg_payload = [
        {
            "time_start": s["time_start"],
            "time_end": s["time_end"],
            "matched_ref": s["matched_ref"],
            "matched_text": s["matched_text"],
            "confidence": s["confidence"],
            "phonemes_asr": s.get("phonemes_asr", ""),
            "segment_uid": s["segment_uid"],
        }
        for s in fixture["entries"][0]["segments"]
    ]
    payload = {"full_replace": True, "segments": seg_payload, "operations": []}

    res = flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert res.status_code == 200

    seg_path = tmp_reciter_dir.root / reciter / "segments.json"
    seg_doc = json.loads(seg_path.read_text(encoding="utf-8"))
    assert "_meta" in seg_doc, "segments.json must contain _meta"

    expected_keys = {"112:1", "112:2", "112:3", "112:4"}
    actual_keys = set(seg_doc.keys()) - {"_meta"}
    assert expected_keys.issubset(actual_keys), (
        f"missing verse keys after rebuild: {expected_keys - actual_keys}"
    )

    for k in actual_keys:
        for tup in seg_doc[k]:
            assert isinstance(tup, list) and len(tup) == 4, (
                f"segments.json tuple for {k} not 4-element: {tup}"
            )


def test_segments_json_meta_preserved(tmp_reciter_dir, flask_client, load_fixture):
    """The _meta block on segments.json survives a save round-trip."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112

    seg_path = tmp_reciter_dir.root / reciter / "segments.json"
    seg_path.write_text(
        json.dumps({"_meta": {"audio_source": "by_surah/fixture", "extra": "value"}}),
        encoding="utf-8",
    )

    fixture = load_fixture("112-ikhlas")
    payload = {
        "full_replace": True,
        "segments": [
            {
                "time_start": s["time_start"],
                "time_end": s["time_end"],
                "matched_ref": s["matched_ref"],
                "matched_text": s["matched_text"],
                "confidence": s["confidence"],
                "phonemes_asr": s.get("phonemes_asr", ""),
                "segment_uid": s["segment_uid"],
            }
            for s in fixture["entries"][0]["segments"]
        ],
        "operations": [],
    }
    res = flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert res.status_code == 200

    after = json.loads(seg_path.read_text(encoding="utf-8"))
    assert after["_meta"].get("audio_source") == "by_surah/fixture"
    assert after["_meta"].get("extra") == "value"
