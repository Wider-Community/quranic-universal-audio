"""Word-by-word coverage rule behind the sample's "WBW Timestamps" tag."""

from __future__ import annotations

from services.samples.coverage import is_wbw_complete, segment_covered

WC = {(2, 1): 3, (2, 2): 2}


def _seg(ref: str, locations: list[str]) -> dict:
    return {
        "matched_ref": ref,
        "word_timings": [
            {"word": "w", "location": loc, "start_ms": 0, "end_ms": 1} for loc in locations
        ],
    }


def test_segment_covered_counts_distinct_locations_inside_the_ref():
    assert segment_covered(_seg("2:1:1-2:1:3", ["2:1:1", "2:1:2", "2:1:3"]), WC) is True
    assert segment_covered(_seg("2:1:1-2:1:3", ["2:1:1", "2:1:2"]), WC) is False
    # Duplicates (a repetition wrap) and out-of-ref words don't pad the count.
    assert segment_covered(_seg("2:1:1-2:1:2", ["2:1:1", "2:1:1", "2:2:1"]), WC) is False
    # Cross-verse spans walk the word counts.
    assert segment_covered(_seg("2:1:2-2:2:1", ["2:1:2", "2:1:3", "2:2:1"]), WC) is True


def test_specials_and_malformed_refs_are_not_applicable():
    assert segment_covered(_seg("Basmala", []), WC) is None
    assert segment_covered(_seg("", []), WC) is None
    assert segment_covered(_seg("2:1:x-2:1:3", []), WC) is None


def test_wbw_complete_needs_every_quran_segment_and_at_least_one():
    entries = [{"segments": [_seg("Basmala", []), _seg("2:1:1-2:1:3", ["2:1:1", "2:1:2", "2:1:3"])]}]
    assert is_wbw_complete(entries, WC) is True
    entries[0]["segments"].append(_seg("2:2:1-2:2:2", ["2:2:1"]))
    assert is_wbw_complete(entries, WC) is False
    assert is_wbw_complete([{"segments": [_seg("Basmala", [])]}], WC) is False
    assert is_wbw_complete([], WC) is False
