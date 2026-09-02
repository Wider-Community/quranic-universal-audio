"""Aligner Alignment <-> detailed.json conversion for uploaded samples."""

from __future__ import annotations

import pytest

from services.samples.convert import (
    SampleConvertError,
    alignment_to_detailed,
    detailed_to_alignment,
    resolve_pseudo_chapter,
    sniff_envelope,
)


def _seg(i: int, start: float, end: float, ref: str | None, **extra) -> dict:
    return {
        "id": i,
        "region": {"start_s": start, "end_s": end},
        "kind": "quran" if ref else None,
        "matched_ref": ref,
        "matched_text": "x",
        "confidence": 0.9,
        "findings": [],
        **extra,
    }


def _alignment() -> dict:
    return {
        "segments": [
            _seg(0, 0.5, 2.0, "2:1:1-2:2:3"),
            _seg(
                1,
                2.0,
                3.25,
                "2:2:4-2:3:1",
                wrap_ranges=[{"jump_to": "2:2:4", "jump_from": "2:2:6", "repeat_end": "2:3:1"}],
            ),
            _seg(2, 3.3, 4.0, None, filtered=True),
            _seg(3, 4.0, 5.0, "2:3:2-2:3:5", merged_into=1),
        ],
        "chapter": None,
        "inventory_mode": "full",
        "riwayah": "hafs",
    }


def test_sniff_bare_and_resource_envelopes():
    bare = _alignment()
    assert sniff_envelope(bare)[0] == "alignment"
    wrapped = {"alignment_id": "aln_1", "alignment": bare}
    kind, inner = sniff_envelope(wrapped)
    assert kind == "alignment_resource" and inner is bare
    with pytest.raises(SampleConvertError):
        sniff_envelope({"nope": 1})


def test_pseudo_chapter_prefers_explicit_then_first_ref():
    a = _alignment()
    assert resolve_pseudo_chapter("alignment", a) == 2
    a["chapter"] = 36
    assert resolve_pseudo_chapter("alignment", a) == 36
    assert resolve_pseudo_chapter("alignment", {"segments": [_seg(0, 0, 1, None)]}) == 1


def test_import_converts_seconds_and_wraps_and_drops_non_live():
    doc, sidecar = alignment_to_detailed("alignment", _alignment(), pseudo_chapter=2)
    entry = doc["entries"][0]
    assert entry["ref"] == "2"
    segs = entry["segments"]
    assert [s["time_start"] for s in segs] == [500, 2000]
    assert segs[1]["time_end"] == 3250
    assert segs[1]["wrap_word_ranges"] == [["2:2:4", "2:2:6", "2:3:1"]]
    assert "wrap_word_ranges" not in segs[0]
    assert all(s["segment_uid"] for s in segs)
    assert len(sidecar["dropped"]) == 2
    assert set(sidecar["originals"]) == {s["segment_uid"] for s in segs}
    assert doc["_meta"]["audio_source"] == "sample"


def test_import_rejects_inverted_region_and_empty_alignment():
    bad = {"segments": [_seg(0, 2.0, 1.0, "1:1:1-1:1:2")]}
    with pytest.raises(SampleConvertError):
        alignment_to_detailed("alignment", bad, pseudo_chapter=1)
    with pytest.raises(SampleConvertError):
        alignment_to_detailed("alignment", {"segments": []}, pseudo_chapter=1)


def test_roundtrip_is_identity_when_unedited():
    original = {"alignment_id": "aln_1", "alignment": _alignment(), "links": {"self": "/x"}}
    doc, sidecar = alignment_to_detailed(
        "alignment_resource", original["alignment"], pseudo_chapter=2
    )
    back = detailed_to_alignment(doc["entries"], sidecar, original)
    assert back["alignment_id"] == "aln_1" and back["links"] == original["links"]
    assert back["alignment"]["chapter"] == 2
    assert [s["id"] for s in back["alignment"]["segments"]] == [0, 1, 2, 3]
    assert (
        back["alignment"]["segments"][1]["wrap_ranges"]
        == original["alignment"]["segments"][1]["wrap_ranges"]
    )
    assert back["alignment"]["segments"][0]["region"] == {"start_s": 0.5, "end_s": 2.0}


def test_export_carries_edits_and_allocates_ids_for_new_segments():
    original = _alignment()
    doc, sidecar = alignment_to_detailed("alignment", original, pseudo_chapter=2)
    segs = doc["entries"][0]["segments"]
    segs[0]["time_end"] = 1500
    segs[0]["matched_ref"] = ""
    segs.append(
        {"time_start": 1500, "time_end": 2000, "matched_ref": "2:2:1-2:2:3", "confidence": 0.4}
    )
    back = detailed_to_alignment(doc["entries"], sidecar, original)
    by_id = {s["id"]: s for s in back["segments"]}
    assert by_id[0]["region"]["end_s"] == 1.5 and by_id[0]["matched_ref"] is None
    new = by_id[4]
    assert new["kind"] == "quran" and new["region"] == {"start_s": 1.5, "end_s": 2.0}
    assert [s["id"] for s in back["segments"]] == [0, 4, 1, 2, 3]


def _legacy() -> dict:
    return {
        "_meta": {"schema_version": 1},
        "segments": [
            {
                "segment": 1,
                "time_from": 0.98,
                "time_to": 4.84,
                "ref_from": "",
                "ref_to": "",
                "matched_text": "b",
                "confidence": 0.9,
                "has_missing_words": False,
                "has_repeated_words": False,
                "special_type": "Basmala",
                "error": None,
                "kind": "special",
                "confidence_band": "high",
            },
            {
                "segment": 2,
                "time_from": 5.78,
                "time_to": 22.295,
                "ref_from": "84:1:1",
                "ref_to": "84:5:3",
                "matched_text": "x",
                "confidence": 1.0,
                "has_missing_words": False,
                "has_repeated_words": False,
                "special_type": None,
                "error": None,
                "kind": "quran",
                "confidence_band": "high",
            },
        ],
    }


def test_legacy_export_is_sniffed_imported_and_round_tripped():
    original = _legacy()
    kind, container = sniff_envelope(original)
    assert kind == "legacy"
    assert resolve_pseudo_chapter(kind, container) == 84
    doc, sidecar = alignment_to_detailed(kind, container, pseudo_chapter=84)
    segs = doc["entries"][0]["segments"]
    assert [(s["time_start"], s["time_end"], s["matched_ref"]) for s in segs] == [
        (980, 4840, "Basmala"),
        (5780, 22295, "84:1:1-84:5:3"),
    ]

    back = detailed_to_alignment(doc["entries"], sidecar, original)
    assert back == original

    segs[1]["time_end"] = 20000
    segs[1]["matched_ref"] = "84:1:1-84:4:2"
    segs.append(
        {"time_start": 22300, "time_end": 25000, "matched_ref": "84:5:4-84:5:6", "confidence": 0.5}
    )
    back = detailed_to_alignment(doc["entries"], sidecar, original)
    by_id = {s["segment"]: s for s in back["segments"]}
    assert by_id[2]["time_to"] == 20.0 and by_id[2]["ref_to"] == "84:4:2"
    assert by_id[3]["ref_from"] == "84:5:4" and by_id[3]["kind"] == "quran"
    assert back["_meta"] == {"schema_version": 1}


def test_word_timings_ride_on_the_segment_and_export_back_relative():
    original = _legacy()
    original["segments"][1]["words"] = [
        {"word": "إِذَا", "location": "84:1:1", "start": 0.4, "end": 1.2},
        {"word": "ٱلسَّمَآءُ", "location": "84:1:2", "start": 1.2, "end": 2.75},
        {"word": "bad", "location": "84:1:3", "start": None, "end": 3.0},
    ]
    kind, container = sniff_envelope(original)
    doc, sidecar = alignment_to_detailed(kind, container, pseudo_chapter=84)
    segs = doc["entries"][0]["segments"]
    assert "word_timings" not in segs[0]
    assert segs[1]["word_timings"] == [
        {"word": "إِذَا", "location": "84:1:1", "start_ms": 6180, "end_ms": 6980},
        {"word": "ٱلسَّمَآءُ", "location": "84:1:2", "start_ms": 6980, "end_ms": 8530},
    ]

    back = detailed_to_alignment(doc["entries"], sidecar, original)
    assert back["segments"][1]["words"] == [
        {"word": "إِذَا", "location": "84:1:1", "start": 0.4, "end": 1.2},
        {"word": "ٱلسَّمَآءُ", "location": "84:1:2", "start": 1.2, "end": 2.75},
    ]

    # A trim moves the origin: exported times shift; dropping the timings
    # removes the stale upload list.
    segs[1]["time_start"] = 6000
    back = detailed_to_alignment(doc["entries"], sidecar, original)
    assert back["segments"][1]["words"][0]["start"] == 0.18
    segs[1].pop("word_timings")
    back = detailed_to_alignment(doc["entries"], sidecar, original)
    assert "words" not in back["segments"][1]
