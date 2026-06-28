"""ts_target_snapshot: target resolution + per-category staleness diff.

Drives the pure resolver/diff with synthetic shard docs (no bucket I/O)."""

from __future__ import annotations

import copy

from services.ts_reports import ts_target_snapshot as snap


def _doc() -> dict:
    # One verse "2:45", one word "بَ": base ب (qalqala) + haraka fatha.
    word = [
        1,
        0,
        20,
        [["ب", 0, 10], ["َ", 10, 20]],
        [["b", 0, 10], ["a", 10, 20]],
        [
            ["ب", "base", "present", [0], 0, "qalqala_sughra", None],
            ["َ", "haraka", "present", [1], 1, None, None],
        ],
    ]
    return {
        "_meta": {"schema_version": 9, "chapter": 2, "audio_category": "by_ayah_audio"},
        "segments": [{"ref": "2:45", "t": [0, 20], "words": [word]}],
    }


def _report(category: str, target: dict, doc: dict, *, onset=None, offset=None) -> dict:
    return {
        "category": category,
        "verse_key": "2:45",
        "target": target,
        "onset": onset,
        "offset": offset,
        "snapshot": snap.resolve_target(doc, "2:45", target),
    }


def test_resolve_verse_and_word():
    doc = _doc()
    vsnap = snap.resolve_target(doc, "2:45", {"kind": "verse"})
    assert vsnap is not None and vsnap["verse_text"] == "بَ"
    wsnap = snap.resolve_target(doc, "2:45", {"kind": "word", "word_index": 0})
    assert wsnap is not None and wsnap["word_text"] == "بَ"


def test_resolve_cell_and_column_and_phoneme():
    doc = _doc()
    cell = snap.resolve_target(doc, "2:45", {"kind": "cell", "word_index": 0, "cell_index": 0})
    assert cell is not None and cell["chars"] == "ب" and cell["tag"] == "qalqala_sughra"
    col = snap.resolve_target(
        doc, "2:45", {"kind": "column", "word_index": 0, "source_letter_index": 0}
    )
    assert col is not None and col["chars"] == "ب" and col["phones"] == ["b"]
    ph = snap.resolve_target(
        doc, "2:45", {"kind": "phoneme", "word_index": 0, "phoneme_flat_index": 1}
    )
    assert ph is not None and ph["chars"] == "a"


def test_missing_verse_returns_none():
    assert snap.resolve_target(_doc(), "9:9", {"kind": "verse"}) is None


def test_audio_never_stale():
    doc = _doc()
    report = _report("audio", {"kind": "verse"}, doc)
    assert snap.is_stale_after_restamp(report, doc) is False


def test_tajweed_stale_when_rule_changes():
    doc = _doc()
    target = {"kind": "cell", "word_index": 0, "cell_index": 0}
    report = _report("tajweed", target, doc)
    assert snap.is_stale_after_restamp(report, doc) is False
    changed = copy.deepcopy(doc)
    changed["segments"][0]["words"][0][5][0][5] = None  # drop the qalqala tag
    assert snap.is_stale_after_restamp(report, changed) is True


def test_timing_stale_on_identity_change_and_flagged_onset_shift():
    doc = _doc()
    target = {"kind": "cell", "word_index": 0, "cell_index": 0}
    report = _report("timing", target, doc, onset="early")  # flags the START only

    # the unflagged offset moving does NOT stale
    off_shift = copy.deepcopy(doc)
    off_shift["segments"][0]["words"][0][3][0][2] = 500  # letter end 10 -> 500
    assert snap.is_stale_after_restamp(report, off_shift) is False

    # a small onset shift (< 100ms threshold) does NOT stale
    small = copy.deepcopy(doc)
    small["segments"][0]["words"][0][3][0][1] = 50  # letter start 0 -> 50
    assert snap.is_stale_after_restamp(report, small) is False

    # a large onset shift (> threshold) stales
    big = copy.deepcopy(doc)
    big["segments"][0]["words"][0][3][0][1] = 300  # letter start 0 -> 300
    assert snap.is_stale_after_restamp(report, big) is True

    # identity change (cell removed) always stales
    removed = copy.deepcopy(doc)
    removed["segments"][0]["words"][0][5] = []
    assert snap.is_stale_after_restamp(report, removed) is True


def test_timing_offset_only_report_ignores_onset_shift():
    doc = _doc()
    target = {"kind": "cell", "word_index": 0, "cell_index": 0}
    report = _report("timing", target, doc, offset="late")  # flags the END only

    big_offset = copy.deepcopy(doc)
    big_offset["segments"][0]["words"][0][3][0][2] = 300  # letter end 10 -> 300
    assert snap.is_stale_after_restamp(report, big_offset) is True

    onset_only = copy.deepcopy(doc)
    onset_only["segments"][0]["words"][0][3][0][1] = 300  # letter start moves, end unchanged
    assert snap.is_stale_after_restamp(report, onset_only) is False


def test_mapping_stale_when_binding_changes():
    doc = _doc()
    target = {"kind": "column", "word_index": 0, "source_letter_index": 0}
    report = _report("mapping", target, doc)
    assert snap.is_stale_after_restamp(report, doc) is False
    changed = copy.deepcopy(doc)
    changed["segments"][0]["words"][0][4][0][0] = "p"  # remapped phone
    assert snap.is_stale_after_restamp(report, changed) is True


def test_other_stale_when_verse_text_changes():
    doc = _doc()
    report = _report("other", {"kind": "verse"}, doc)
    changed = copy.deepcopy(doc)
    changed["segments"][0]["words"][0][3][0][0] = "ت"  # letter changed
    assert snap.is_stale_after_restamp(report, changed) is True
