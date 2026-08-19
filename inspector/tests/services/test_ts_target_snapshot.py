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
            ["ب", "base", "present", [0], 0, ["qalqala_sughra"], None],
            ["َ", "haraka", "present", [1], 1, [], None],
        ],
    ]
    return {
        "_meta": {"schema_version": 11, "chapter": 2, "audio_category": "by_ayah_audio"},
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


def test_resolve_cell_and_phoneme():
    doc = _doc()
    cell = snap.resolve_target(doc, "2:45", {"kind": "cell", "word_index": 0, "cell_index": 0})
    assert cell is not None and cell["chars"] == "ب" and cell["tag"] == "qalqala_sughra"
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
    changed["segments"][0]["words"][0][5][0][5] = []  # drop the qalqala rule
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


def test_phonemes_stale_when_phone_identity_changes():
    doc = _doc()
    target = {"kind": "phoneme", "word_index": 0, "phoneme_flat_index": 1}
    report = _report("phonemes", target, doc)
    assert snap.is_stale_after_restamp(report, doc) is False
    changed = copy.deepcopy(doc)
    changed["segments"][0]["words"][0][4][1][0] = "i"  # phone a -> i
    assert snap.is_stale_after_restamp(report, changed) is True


def _bridge_doc() -> dict:
    # word 0 "نْ" whose tail phone merges (idgham) into word 1 — the merger phone
    # carries a bridge rule (row slot 5) and renders before word 1 (k>0 → target=1).
    w0 = [
        0,
        0,
        10,
        [["ن", 0, 5]],
        [["n", 0, 5], ["m̃", 5, 10, False, False, "idgham_ghunnah"]],
        [["ن", "base", "present", [0], 0, [], None]],
    ]
    w1 = [
        1,
        10,
        20,
        [["م", 10, 20]],
        [["m", 10, 20]],
        [["م", "base", "present", [0], 0, [], None]],
    ]
    return {
        "_meta": {"schema_version": 11, "chapter": 2, "audio_category": "by_ayah_audio"},
        "segments": [{"ref": "2:45", "t": [0, 20], "words": [w0, w1]}],
    }


def test_resolve_bridge_phoneme_targets_following_word():
    doc = _bridge_doc()
    target = {"kind": "phoneme", "word_index": 1, "phoneme_flat_index": -1}
    s = snap.resolve_target(doc, "2:45", target)
    assert s is not None and s["chars"] == "m̃" and s["tag"] == "idgham_ghunnah"


def test_phonemes_bridge_stale_when_merger_rule_changes_or_vanishes():
    doc = _bridge_doc()
    target = {"kind": "phoneme", "word_index": 1, "phoneme_flat_index": -1}
    report = _report("phonemes", target, doc)
    assert snap.is_stale_after_restamp(report, doc) is False
    rule_changed = copy.deepcopy(doc)
    rule_changed["segments"][0]["words"][0][4][1][5] = "idgham_no_ghunnah"
    assert snap.is_stale_after_restamp(report, rule_changed) is True
    vanished = copy.deepcopy(doc)
    vanished["segments"][0]["words"][0][4] = [["n", 0, 5]]  # merger phone gone
    assert snap.is_stale_after_restamp(report, vanished) is True


def test_other_stale_when_verse_text_changes():
    doc = _doc()
    report = _report("other", {"kind": "verse"}, doc)
    changed = copy.deepcopy(doc)
    changed["segments"][0]["words"][0][3][0][0] = "ت"  # letter changed
    assert snap.is_stale_after_restamp(report, changed) is True


# --- silence (gap) reports: resolution + auto-resolve decision matrix --------

_GAP_TARGET = {"kind": "gap", "word_index": 0}


def _two_word_doc(*, gap: bool) -> dict:
    """Two words "بَ" / "تَ"; the second starts at 30 (a gap after word 0) or at 20
    (contiguous, no gap)."""
    w0 = [0, 0, 20, [["ب", 0, 20]], [["b", 0, 20]], [["ب", "base", "present", [0], 0, [], None]]]
    s1 = 30 if gap else 20
    w1 = [
        1,
        s1,
        s1 + 20,
        [["ت", s1, s1 + 20]],
        [["t", s1, s1 + 20]],
        [["ت", "base", "present", [0], 0, [], None]],
    ]
    return {
        "_meta": {"schema_version": 11, "chapter": 2, "audio_category": "by_ayah_audio"},
        "segments": [{"ref": "2:45", "t": [0, s1 + 20], "words": [w0, w1]}],
    }


def _silence_report(subtype: str, create_doc: dict, *, onset=None, offset=None) -> dict:
    return {
        "category": "silence",
        "verse_key": "2:45",
        "subtype": subtype,
        "target": _GAP_TARGET,
        "onset": onset,
        "offset": offset,
        "snapshot": snap.resolve_target(create_doc, "2:45", _GAP_TARGET),
    }


def test_resolve_gap_bounds_and_presence():
    g = snap.resolve_target(_two_word_doc(gap=True), "2:45", _GAP_TARGET)
    assert g is not None and g["onset_ms"] == 20 and g["offset_ms"] == 30
    assert snap._gap_present(g) is True
    contiguous = snap.resolve_target(_two_word_doc(gap=False), "2:45", _GAP_TARGET)
    assert contiguous is not None and snap._gap_present(contiguous) is False


def test_silence_missed_auto_resolves_when_gap_appears():
    r = _silence_report("pause_missed", _two_word_doc(gap=False))
    assert snap._silence_action(r, _two_word_doc(gap=True)) == (
        "resolve",
        "A pause now appears here on the latest timestamps.",
    )
    assert snap._silence_action(r, _two_word_doc(gap=False)) == ("none", None)


def test_silence_wasl_auto_resolves_when_gap_removed():
    r = _silence_report("pause_wasl", _two_word_doc(gap=True))
    assert snap._silence_action(r, _two_word_doc(gap=False)) == (
        "resolve",
        "This pause is gone on the latest timestamps.",
    )
    assert snap._silence_action(r, _two_word_doc(gap=True)) == ("none", None)


def test_silence_boundary_stales_on_flagged_shift_and_resolves_when_gap_gone():
    create = _two_word_doc(gap=True)
    r = _silence_report("pause_boundary", create, offset="late")  # flags the gap END
    shifted = copy.deepcopy(create)
    shifted["segments"][0]["words"][1][1] = 200  # word1 start 30 -> 200 (gap end moves > thr)
    shifted["segments"][0]["words"][1][2] = 220
    assert snap._silence_action(r, shifted) == ("stale", None)
    # gap removed entirely → the boundary correction is moot → auto-resolve
    assert snap._silence_action(r, _two_word_doc(gap=False))[0] == "resolve"


def test_silence_stale_when_boundary_vanishes():
    r = _silence_report("pause_missed", _two_word_doc(gap=False))
    one_word = _two_word_doc(gap=False)
    one_word["segments"][0]["words"] = one_word["segments"][0]["words"][:1]
    assert snap._silence_action(r, one_word) == ("stale", None)
