"""segments.json rebuild tests (MUST-3)."""

from __future__ import annotations

import json

from adapters.segments_json import build_segments_doc

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}

# Transcribed from one offline-writer run:
# qua-aligner-offline/work/sweepout/mohammed_siddiq_al_minshawi_1967_drive/
#   detailed__sil600.json  (the segment below, entry ref "106")
#   segments__sil600.json  (the expected row under key "106:1:1-106:2:4")
_WRAPPED_ENTRY = {
    "ref": "106",
    "segments": [
        {
            "time_start": 0,
            "time_end": 15880,
            "matched_ref": "106:1:1-106:2:4",
            "confidence": 0.69,
            "wrap_word_ranges": [["106:1:1", "106:1:2", "106:2:4"]],
        }
    ],
}
_WRAPPED_KEY = "106:1:1-106:2:4"
_EXPECTED_ROW = [1, 4, 0, 15880, {"repeated": [[1, 2], [1, 4]]}]


def test_segments_doc_omits_repeated_by_default():
    """Without the flag a wrapped segment still produces a 4-element row."""
    doc = build_segments_doc([_WRAPPED_ENTRY])
    assert doc[_WRAPPED_KEY] == [_EXPECTED_ROW[:4]]


def test_segments_doc_repeated_matches_offline_writer():
    """With the flag on, the fifth element matches the published offline row."""
    doc = build_segments_doc([_WRAPPED_ENTRY], with_repeated=True)
    assert doc[_WRAPPED_KEY] == [_EXPECTED_ROW]


def test_segments_json_rebuild_parity(load_fixture, tmp_reciter_dir, signed_in_client):
    """Load detailed.json → save → segments.json key set + tuples match expected."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    chapter = 112

    fixture = load_fixture("112-ikhlas")
    seg_payload = [
        {
            "time_start": s["time_start"],
            "time_end": s["time_end"],
            "matched_ref": s["matched_ref"],
            "confidence": s["confidence"],
            "segment_uid": s["segment_uid"],
        }
        for s in fixture["entries"][0]["segments"]
    ]
    payload = {"full_replace": True, "segments": seg_payload, "operations": []}

    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        headers=_HEADERS,
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


def test_segments_json_meta_preserved(tmp_reciter_dir, signed_in_client, load_fixture):
    """The _meta block on segments.json survives a save round-trip."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
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
                "confidence": s["confidence"],
                "segment_uid": s["segment_uid"],
            }
            for s in fixture["entries"][0]["segments"]
        ],
        "operations": [],
    }
    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        headers=_HEADERS,
    )
    assert res.status_code == 200

    after = json.loads(seg_path.read_text(encoding="utf-8"))
    assert after["_meta"].get("audio_source") == "by_surah/fixture"
    assert after["_meta"].get("extra") == "value"
