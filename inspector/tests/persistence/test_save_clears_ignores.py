"""save → ignored_categories semantics tests (MUST-7)."""
from __future__ import annotations

import json


_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}

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
        "confidence": src["confidence"],
        "segment_uid": src["segment_uid"],
    }
    base.update(overrides)
    return base


def test_empty_ignored_categories_clears_persisted_ignores(load_fixture, tmp_reciter_dir, signed_in_client):
    """Segment had ['low_confidence']; save with []; reload; field is absent or []."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    chapter = 112
    fixture = load_fixture("112-ikhlas")
    target_uid = fixture["entries"][0]["segments"][0]["segment_uid"]

    seg_payload = []
    for s in fixture["entries"][0]["segments"]:
        seg_payload.append(_seg_payload_from_fixture(fixture, s["segment_uid"]))
    seg_payload[0]["ignored_categories"] = ["low_confidence"]

    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps({"full_replace": True, "segments": seg_payload, "operations": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()

    saved = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    target = _segments_with_uid(saved, target_uid)[0]
    assert target.get("ignored_categories") == ["low_confidence"]

    seg_payload[0]["ignored_categories"] = []
    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps({"full_replace": True, "segments": seg_payload, "operations": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()

    saved2 = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    target2 = _segments_with_uid(saved2, target_uid)[0]
    ic = target2.get("ignored_categories", [])
    assert ic == [] or "ignored_categories" not in target2, (
        f"empty ignored_categories did not clear persisted state — got {ic!r}"
    )


def test_omitted_ignored_categories_preserves_existing(load_fixture, tmp_reciter_dir, signed_in_client):
    """Segment had ['low_confidence']; save without the key (patch mode); reload; field still present."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    chapter = 112
    fixture = load_fixture("112-ikhlas")
    target_uid = fixture["entries"][0]["segments"][0]["segment_uid"]

    seg_payload = [
        _seg_payload_from_fixture(fixture, s["segment_uid"])
        for s in fixture["entries"][0]["segments"]
    ]
    seg_payload[0]["ignored_categories"] = ["low_confidence"]
    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps({"full_replace": True, "segments": seg_payload, "operations": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()

    patch_payload = {"segments": [{"index": 0, "matched_ref": fixture["entries"][0]["segments"][0]["matched_ref"]}], "operations": []}
    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(patch_payload),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()

    saved = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    target = _segments_with_uid(saved, target_uid)[0]
    assert target.get("ignored_categories") == ["low_confidence"], (
        f"patch save dropped ignored_categories — got {target.get('ignored_categories')!r}"
    )


def test_all_marker_preserved(load_fixture, tmp_reciter_dir, signed_in_client):
    """A segment with ['_all'] survives a save/reload unchanged."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    chapter = 112
    fixture = load_fixture("112-ikhlas")
    target_uid = fixture["entries"][0]["segments"][0]["segment_uid"]

    seg_payload = [
        _seg_payload_from_fixture(fixture, s["segment_uid"])
        for s in fixture["entries"][0]["segments"]
    ]
    seg_payload[0]["ignored_categories"] = ["_all"]
    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps({"full_replace": True, "segments": seg_payload, "operations": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()

    saved = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    target = _segments_with_uid(saved, target_uid)[0]
    assert target.get("ignored_categories") == ["_all"]


def test_save_drops_wrap_when_fe_omits_it(tmp_reciter_dir, signed_in_client):
    """Regression: a parent repetition seg used to leak wrap onto split children
    because save_payload fell back to ``existing.get('wrap_word_ranges')`` when
    the FE payload omitted the field. Now FE is authoritative — omit means drop.
    """
    reciter = "fixture_reciter"
    legacy_path = tmp_reciter_dir.root / reciter / "detailed.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_doc = {
        "_meta": {"audio_source": "by_surah/fixture"},
        "entries": [
            {
                "ref": "112",
                "segments": [
                    {
                        "time_start": 1000, "time_end": 5000,
                        "matched_ref": "112:1:1-112:1:4",
                        "confidence": 1.0,
                        "segment_uid": "uid-rep",
                        "wrap_word_ranges": [["112:1:2", "112:1:2", "112:1:4"]],
                        "has_repeated_words": True,
                    }
                ],
            }
        ],
    }
    legacy_path.write_text(json.dumps(legacy_doc), encoding="utf-8")
    tmp_reciter_dir.seed_under_review(reciter, "test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")

    # FE re-saves the same seg but, simulating a post-split child, omits wrap.
    payload = {
        "full_replace": True,
        "segments": [{
            "segment_uid": "uid-rep",
            "time_start": 1000, "time_end": 5000,
            "matched_ref": "112:1:1-112:1:4",
            "confidence": 1.0,
            "audio_url": "https://fixture.local/audio/112.mp3",
            # wrap_word_ranges + has_repeated_words intentionally omitted
        }],
        "operations": [],
    }
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps(payload),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()
    saved = json.loads(legacy_path.read_text(encoding="utf-8"))
    seg = saved["entries"][0]["segments"][0]
    assert "wrap_word_ranges" not in seg, (
        f"omitted wrap should drop on save — got {seg.get('wrap_word_ranges')!r}"
    )
    assert "has_repeated_words" not in seg, (
        f"omitted has_repeated_words should drop on save — got {seg.get('has_repeated_words')!r}"
    )


def test_save_drops_geometrically_invalid_wrap(tmp_reciter_dir, signed_in_client):
    """Defense-in-depth: BE rejects a wrap whose geometry doesn't fit
    matched_ref (stale-from-inheritance shape). A buggy or malicious client
    can't poison detailed.json with wraps that would feed wrong refs to MFA.
    """
    reciter = "fixture_reciter"
    legacy_path = tmp_reciter_dir.root / reciter / "detailed.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_doc = {
        "_meta": {"audio_source": "by_surah/fixture"},
        "entries": [{
            "ref": "112",
            "segments": [{
                "time_start": 1000, "time_end": 5000,
                "matched_ref": "112:1:1-112:1:2",
                "confidence": 1.0,
                "segment_uid": "uid-rep",
            }],
        }],
    }
    legacy_path.write_text(json.dumps(legacy_doc), encoding="utf-8")
    tmp_reciter_dir.seed_under_review(reciter, "test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")

    # Send a wrap whose word range (3-4) lies outside matched_ref (1-2).
    payload = {
        "full_replace": True,
        "segments": [{
            "segment_uid": "uid-rep",
            "time_start": 1000, "time_end": 5000,
            "matched_ref": "112:1:1-112:1:2",
            "confidence": 1.0,
            "audio_url": "https://fixture.local/audio/112.mp3",
            "wrap_word_ranges": [["112:1:3", "112:1:3", "112:1:4"]],
            "has_repeated_words": True,
        }],
        "operations": [],
    }
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps(payload),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()
    saved = json.loads(legacy_path.read_text(encoding="utf-8"))
    seg = saved["entries"][0]["segments"][0]
    assert "wrap_word_ranges" not in seg, (
        f"BE should drop geometrically invalid wrap — got {seg.get('wrap_word_ranges')!r}"
    )
    assert "has_repeated_words" not in seg, (
        "BE should drop has_repeated_words when wrap is rejected"
    )


def test_save_preserves_wrap_when_fe_sends_it(tmp_reciter_dir, signed_in_client):
    """Sanity: a real repetition seg whose FE payload includes wrap keeps it."""
    reciter = "fixture_reciter"
    legacy_path = tmp_reciter_dir.root / reciter / "detailed.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_doc = {
        "_meta": {"audio_source": "by_surah/fixture"},
        "entries": [{
            "ref": "112",
            "segments": [{
                "time_start": 1000, "time_end": 5000,
                "matched_ref": "112:1:1-112:1:4",
                "confidence": 1.0,
                "segment_uid": "uid-rep",
            }],
        }],
    }
    legacy_path.write_text(json.dumps(legacy_doc), encoding="utf-8")
    tmp_reciter_dir.seed_under_review(reciter, "test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")

    payload = {
        "full_replace": True,
        "segments": [{
            "segment_uid": "uid-rep",
            "time_start": 1000, "time_end": 5000,
            "matched_ref": "112:1:1-112:1:4",
            "confidence": 1.0,
            "audio_url": "https://fixture.local/audio/112.mp3",
            "wrap_word_ranges": [["112:1:2", "112:1:2", "112:1:4"]],
        }],
        "operations": [],
    }
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps(payload),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()
    saved = json.loads(legacy_path.read_text(encoding="utf-8"))
    seg = saved["entries"][0]["segments"][0]
    assert seg.get("wrap_word_ranges") == [["112:1:2", "112:1:2", "112:1:4"]]
    # Migration #5: has_repeated_words is no longer persisted — it was a
    # boolean tautology of bool(wrap_word_ranges). The classifier only
    # reads wrap_word_ranges. Assert it's absent.
    assert "has_repeated_words" not in seg


def test_legacy_ignored_boolean_migrates_to_all(tmp_reciter_dir, signed_in_client):
    """A segment with ignored=true (no ignored_categories) becomes ['_all'] on save."""
    reciter = "fixture_reciter"
    legacy_path = tmp_reciter_dir.root / reciter / "detailed.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_doc = {
        "_meta": {"audio_source": "by_surah/fixture"},
        "entries": [
            {
                "ref": "112",
                "segments": [
                    {
                        "time_start": 1000, "time_end": 2000,
                        "matched_ref": "112:1:1-112:1:1",
                        "confidence": 1.0,
                        "segment_uid": "uid-1",
                        "ignored": True,
                    }
                ],
            }
        ],
    }
    legacy_path.write_text(json.dumps(legacy_doc), encoding="utf-8")
    tmp_reciter_dir.seed_under_review(reciter, "test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")

    payload = {
        "full_replace": True,
        "segments": [
            {
                "time_start": 1000, "time_end": 2000,
                "matched_ref": "112:1:1-112:1:1",
                "confidence": 1.0,
                "segment_uid": "uid-1",
            }
        ],
        "operations": [],
    }
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps(payload),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()

    saved = json.loads(legacy_path.read_text(encoding="utf-8"))
    seg = saved["entries"][0]["segments"][0]
    assert seg.get("ignored_categories") == ["_all"], (
        f"legacy ignored=true must migrate to ['_all'] on save; got {seg.get('ignored_categories')!r}"
    )


def test_save_drops_matched_text_from_disk(tmp_reciter_dir, signed_in_client):
    """Migration #5: save must NOT persist matched_text into detailed.json.

    Inspector consumers derive verse text from matched_ref via
    services/reference/quran_refs.py::dk_text_for_ref. If a regression
    were to re-emit the field at save, the slim-shape contract breaks
    and disk bytes grow unnecessarily. This test catches that.
    """
    reciter = "fixture_reciter"
    legacy_path = tmp_reciter_dir.root / reciter / "detailed.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    # On-disk fixture already carries matched_text (pre-migration data) —
    # we want to assert it gets STRIPPED on save, not preserved.
    legacy_doc = {
        "_meta": {"audio_source": "by_surah/fixture"},
        "entries": [{
            "ref": "112",
            "segments": [{
                "segment_uid": "uid-mt",
                "time_start": 1000, "time_end": 5000,
                "matched_ref": "112:1:1-112:1:4",
                "confidence": 1.0,
            }],
        }],
    }
    legacy_path.write_text(json.dumps(legacy_doc), encoding="utf-8")
    tmp_reciter_dir.seed_under_review(reciter, "test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")

    # FE payload does NOT carry matched_text (Migration #5 contract).
    payload = {
        "full_replace": True,
        "segments": [{
            "segment_uid": "uid-mt",
            "time_start": 1000, "time_end": 5000,
            "matched_ref": "112:1:1-112:1:4",
            "confidence": 1.0,
            "audio_url": "https://fixture.local/audio/112.mp3",
        }],
        "operations": [],
    }
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps(payload),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()
    saved = json.loads(legacy_path.read_text(encoding="utf-8"))
    seg = saved["entries"][0]["segments"][0]
    assert "matched_text" not in seg, (
        f"Migration #5 contract violation: matched_text persisted on save "
        f"(got {seg.get('matched_text')!r}). Inspector consumers derive it "
        f"from matched_ref via dk_text_for_ref."
    )
