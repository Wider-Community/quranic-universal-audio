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
    assert resolve_pseudo_chapter(a) == 2
    a["chapter"] = 36
    assert resolve_pseudo_chapter(a) == 36
    assert resolve_pseudo_chapter({"segments": [_seg(0, 0, 1, None)]}) == 1


def test_import_converts_seconds_and_wraps_and_drops_non_live():
    doc, sidecar = alignment_to_detailed(_alignment(), pseudo_chapter=2)
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
        alignment_to_detailed(bad, pseudo_chapter=1)
    with pytest.raises(SampleConvertError):
        alignment_to_detailed({"segments": []}, pseudo_chapter=1)


def test_roundtrip_is_identity_when_unedited():
    original = {"alignment_id": "aln_1", "alignment": _alignment(), "links": {"self": "/x"}}
    doc, sidecar = alignment_to_detailed(original["alignment"], pseudo_chapter=2)
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
    doc, sidecar = alignment_to_detailed(original, pseudo_chapter=2)
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
