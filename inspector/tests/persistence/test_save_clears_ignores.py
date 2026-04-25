"""save → ignored_categories semantics tests (MUST-7)."""
from __future__ import annotations

import json


def _segments_with_uid(detailed: dict, uid: str) -> list[dict]:
    return [
        s for e in detailed["entries"] for s in e["segments"]
        if s.get("segment_uid") == uid
    ]


def _seg_payload_from_fixture(fixture: dict, uid: str, **overrides) -> dict:
    src = next(s for e in fixture["entries"] for s in e["segments"] if s["segment_uid"] == uid)
    base = {
        "time_start": src["time_start"],
        "time_end": src["time_end"],
        "matched_ref": src["matched_ref"],
        "matched_text": src["matched_text"],
        "confidence": src["confidence"],
        "phonemes_asr": src.get("phonemes_asr", ""),
        "segment_uid": src["segment_uid"],
    }
    base.update(overrides)
    return base


def test_empty_ignored_categories_clears_persisted_ignores(load_fixture, tmp_reciter_dir, flask_client):
    """Segment had ['low_confidence']; save with []; reload; field is absent or []."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112
    fixture = load_fixture("112-ikhlas")
    target_uid = fixture["entries"][0]["segments"][0]["segment_uid"]

    seg_payload = []
    for s in fixture["entries"][0]["segments"]:
        seg_payload.append(_seg_payload_from_fixture(fixture, s["segment_uid"]))
    seg_payload[0]["ignored_categories"] = ["low_confidence"]

    flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps({"full_replace": True, "segments": seg_payload, "operations": []}),
        content_type="application/json",
    )

    saved = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    target = _segments_with_uid(saved, target_uid)[0]
    assert target.get("ignored_categories") == ["low_confidence"]

    seg_payload[0]["ignored_categories"] = []
    flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps({"full_replace": True, "segments": seg_payload, "operations": []}),
        content_type="application/json",
    )

    saved2 = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    target2 = _segments_with_uid(saved2, target_uid)[0]
    ic = target2.get("ignored_categories", [])
    assert ic == [] or "ignored_categories" not in target2, (
        f"empty ignored_categories did not clear persisted state — got {ic!r}"
    )


def test_omitted_ignored_categories_preserves_existing(load_fixture, tmp_reciter_dir, flask_client):
    """Segment had ['low_confidence']; save without the key (patch mode); reload; field still present."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112
    fixture = load_fixture("112-ikhlas")
    target_uid = fixture["entries"][0]["segments"][0]["segment_uid"]

    seg_payload = [
        _seg_payload_from_fixture(fixture, s["segment_uid"])
        for s in fixture["entries"][0]["segments"]
    ]
    seg_payload[0]["ignored_categories"] = ["low_confidence"]
    flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps({"full_replace": True, "segments": seg_payload, "operations": []}),
        content_type="application/json",
    )

    patch_payload = {"segments": [{"index": 0, "matched_ref": fixture["entries"][0]["segments"][0]["matched_ref"], "matched_text": fixture["entries"][0]["segments"][0]["matched_text"]}], "operations": []}
    flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(patch_payload),
        content_type="application/json",
    )

    saved = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    target = _segments_with_uid(saved, target_uid)[0]
    assert target.get("ignored_categories") == ["low_confidence"], (
        f"patch save dropped ignored_categories — got {target.get('ignored_categories')!r}"
    )


def test_all_marker_preserved(load_fixture, tmp_reciter_dir, flask_client):
    """A segment with ['_all'] survives a save/reload unchanged."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112
    fixture = load_fixture("112-ikhlas")
    target_uid = fixture["entries"][0]["segments"][0]["segment_uid"]

    seg_payload = [
        _seg_payload_from_fixture(fixture, s["segment_uid"])
        for s in fixture["entries"][0]["segments"]
    ]
    seg_payload[0]["ignored_categories"] = ["_all"]
    flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps({"full_replace": True, "segments": seg_payload, "operations": []}),
        content_type="application/json",
    )

    saved = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    target = _segments_with_uid(saved, target_uid)[0]
    assert target.get("ignored_categories") == ["_all"]


def test_legacy_ignored_boolean_migrates_to_all(tmp_reciter_dir, flask_client):
    """A segment with ignored=true (no ignored_categories) becomes ['_all'] on save."""
    reciter = "fixture_reciter"
    legacy_path = tmp_reciter_dir.root / reciter / "detailed.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_doc = {
        "_meta": {"audio_source": "by_surah/fixture"},
        "entries": [
            {
                "ref": "112",
                "audio": "https://fixture.local/audio/112.mp3",
                "segments": [
                    {
                        "time_start": 1000, "time_end": 2000,
                        "matched_ref": "112:1:1-112:1:1",
                        "matched_text": "x",
                        "confidence": 1.0,
                        "segment_uid": "uid-1",
                        "ignored": True,
                    }
                ],
            }
        ],
    }
    legacy_path.write_text(json.dumps(legacy_doc), encoding="utf-8")

    payload = {
        "full_replace": True,
        "segments": [
            {
                "time_start": 1000, "time_end": 2000,
                "matched_ref": "112:1:1-112:1:1", "matched_text": "x",
                "confidence": 1.0, "phonemes_asr": "",
                "segment_uid": "uid-1",
            }
        ],
        "operations": [],
    }
    flask_client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps(payload),
        content_type="application/json",
    )

    saved = json.loads(legacy_path.read_text(encoding="utf-8"))
    seg = saved["entries"][0]["segments"][0]
    assert seg.get("ignored_categories") == ["_all"], (
        f"legacy ignored=true must migrate to ['_all'] on save; got {seg.get('ignored_categories')!r}"
    )
