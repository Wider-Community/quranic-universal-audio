"""Tests for cross-word tajweed bridge detection + tagging.

The pure re-slice/stamp core (``_apply_to_words``) is tested deterministically;
the producer-backed detection is exercised when ``quranic_phonemizer`` is present.
"""

from __future__ import annotations

import pytest

pytest.importorskip("qua_sdk.components.timing.lib.cells", reason="qua_sdk not installed")

from qua_sdk.components.timing.lib.cells import (
    _BRIDGE_SLOT,
    BRIDGE_RULES,
    _apply_to_words,
    _looks_like_merger,
    annotate_segment_words,
    detect_segment_bridges,
)


def _word(widx, phones, t0=0):
    """Minimal compact word: [widx, start, end, letters, [[phone, s, e], ...]].
    Phone times are globally monotonic from ``t0`` so re-time is observable:
    phone i → [p, t0+i, t0+i+1]."""
    return [widx, 0, 0, [], [[p, t0 + i, t0 + i + 1] for i, p in enumerate(phones)]]


def test_looks_like_merger():
    assert _looks_like_merger("m̃")
    assert _looks_like_merger("ñ")
    assert _looks_like_merger("ll")
    assert _looks_like_merger("rˤrˤ")  # pharyngeal-insensitive doubled
    assert _looks_like_merger("ww")
    assert not _looks_like_merger("a")
    assert not _looks_like_merger("rˤ")  # single emphatic, not doubled
    assert not _looks_like_merger("")


def test_apply_reattributes_shafawi_merger_to_next_word():
    # قُلُوبِهِم مَّرَضٌ: the meem sakinah merges into the following meem, and the
    # merged m̃ belongs to the word whose letter hosts it — the SECOND. The aligner
    # parked it on the first word's tail; re-attribution moves it back.
    # Canonical counts: قلوبهم=[u], مرض=[m̃,a,n]. Flat: u m̃ | a n.
    words = [_word(14, ["u", "m̃"]), _word(15, ["a", "n"], t0=2)]
    n = _apply_to_words(words, [(1, "idgham_shafawi")], [1, 3])
    assert n == 1
    assert [p[0] for p in words[0][4]] == ["u"]
    assert [p[0] for p in words[1][4]] == ["m̃", "a", "n"]
    assert words[1][4][0] == ["m̃", 1, 2, None, None, "idgham_shafawi"]
    # first word holds through the ghunnah; the second starts past the merger.
    assert words[0][1] == 0 and words[0][2] == 2
    assert words[1][1] == 2 and words[1][2] == 4


def test_apply_first_word_owns_head_merger_duration():
    # idgham ghunnah noon: مَن + يَ… , merger ñ/m̃ at the curr word's head.
    # Flat: m i m̃ a n. The first word must hold through the merger so word
    # highlighting stays on it during the ghunnah; the curr word starts after.
    words = [_word(7, ["m", "i"]), _word(8, ["m̃", "a", "n"], t0=2)]
    n = _apply_to_words(words, [(2, "idgham_ghunnah_noon")], [2, 3])
    assert n == 1
    # Phone attribution unchanged: the merger still lives on the curr word
    # (lifted to the bridge tile by the FE) and carries its rule tag.
    assert [p[0] for p in words[1][4]] == ["m̃", "a", "n"]
    assert words[1][4][0][_BRIDGE_SLOT] == "idgham_ghunnah_noon"
    # First word owns the merger duration: its envelope ends at the merger end.
    assert words[0][1] == 0 and words[0][2] == 3  # m.start .. m̃.end
    # Second word's envelope begins at its next phone, past the merger.
    assert words[1][1] == 3 and words[1][2] == 5  # a.start .. n.end


def test_apply_refuses_non_merger_index():
    # A drifted index pointing at a vowel must NOT be stamped.
    words = [_word(1, ["a", "b"])]
    assert _apply_to_words(words, [(0, "idgham_shafawi")], [2]) == 0
    assert words[0][4][0] == ["a", 0, 1]


def test_apply_noop_on_shape_mismatch():
    # Phonemizer count total != shard indexable-unit count → skip, no mutation.
    words = [_word(1, ["a", "m̃"])]
    before = [list(p) for p in words[0][4]]
    assert _apply_to_words(words, [(1, "idgham_shafawi")], [5]) == 0
    assert words[0][4] == before


def test_apply_rides_qalqala_marker_without_dropping_bridge():
    # A shard stores a render-only qalqala "Q" the phonemizer never emits. It must
    # NOT skew the index or trip the guard: the bridge still tags and the Q rides
    # along on its word.
    # idgham ghunnah noon مَن + يَ…; word 8 ends in a qalqala consonant + Q.
    words = [_word(7, ["m", "i"]), _word(8, ["m̃", "a", "d", "Q"], t0=2)]
    n = _apply_to_words(words, [(2, "idgham_ghunnah_noon")], [2, 3])
    assert n == 1
    # Q is preserved in order on its word; the merger phone carries the rule tag.
    assert [p[0] for p in words[1][4]] == ["m̃", "a", "d", "Q"]
    assert words[1][4][0][_BRIDGE_SLOT] == "idgham_ghunnah_noon"
    # No phone lost from either word.
    assert [p[0] for p in words[0][4]] == ["m", "i"]


def test_apply_qalqala_marker_in_excluded_count_space():
    # The phonemizer's `counts` exclude Q, so a segment whose only shape diff from
    # the phonemizer is a stored Q must MATCH (units == sum(counts)) and tag, where
    # naively counting Q-included phones would mismatch by one and skip.
    words = [_word(14, ["u", "m̃"]), _word(15, ["a", "d", "Q"], t0=2)]
    n = _apply_to_words(words, [(1, "idgham_shafawi")], [1, 3])
    assert n == 1
    assert [p[0] for p in words[0][4]] == ["u"]
    assert words[1][4][0][_BRIDGE_SLOT] == "idgham_shafawi"
    assert [p[0] for p in words[1][4]] == ["m̃", "a", "d", "Q"]  # merger moved, Q kept


# --- producer-backed detection ---------------------------------------------

pytestmark_pm = pytest.importorskip("quranic_phonemizer", reason="phonemizer not installed")

from qua_sdk.integrations.cellrows import letter_rows
from qua_sdk.integrations.phonemizer import result_for_ref
from qua_sdk.integrations.projection import words as phon_words
from qua_sdk.integrations.tokens import is_indexable


def _flat(ref):
    """The ref's phones in the coordinate space a bridge index counts."""
    return [p for w in phon_words(result_for_ref(ref)) for p in w.phonemes if is_indexable(p)]


def _shard_words(verse_key, lo, hi):
    """Shard words for a word range, lettered as the producer writes them.

    The letter row IS the producer's, so what these tests assert is the reading:
    which grapheme falls silent, which mark rides a letter and which does not.
    Word timings are contiguous so the whole range is one gap-bounded run, and
    the ref they imply is the one ``annotate_segment_words`` re-derives against.
    """
    ref = f"{verse_key}:{lo}" if lo == hi else f"{verse_key}:{lo}-{verse_key}:{hi}"
    out = []
    for i, rows in enumerate(letter_rows(result_for_ref(ref))):
        widx = lo + i
        ws, we = (widx - 1) * 100, widx * 100
        out.append([widx, ws, we, [[c, ws, we] for c, _silent in rows], [["x", ws, we]]])
    return out


def _stamped(words):
    return [(lt[0], lt[3]) for wd in words for lt in wd[3]]


def test_annotate_segment_words_skips_non_contiguous():
    # Repeat / out-of-order word indices can't be range-phonemized → no bridge tag
    # (silent-stamping still no-ops here: these words carry no letters).
    words = [_word(3, ["m̃"]), _word(1, ["a"])]
    assert annotate_segment_words("2:5", words) == 0


def test_detect_known_bridges():
    # 2:5 ...هُدࣰى مِّن رَّبِّهِمْ : tanween→meem (m̃) then noon→raa (rˤrˤ).
    flat = _flat("2:5")
    bridges = detect_segment_bridges("2:5")
    rules = {r for _, r in bridges}
    assert "idgham_ghunnah_tanween" in rules
    assert "idgham_bila_ghunnah_noon" in rules
    # every detected index lands on a real merger phone in the flat sequence
    for idx, rule in bridges:
        assert rule in BRIDGE_RULES
        assert _looks_like_merger(flat[idx])


def test_detect_shafawi():
    # 2:10 ...فِی قُلُوبِهِم مَّرَضٌ : idgham shafawi.
    bridges = detect_segment_bridges("2:10")
    assert any(r == "idgham_shafawi" for _, r in bridges)
    flat = _flat("2:10")
    for idx, _rule in bridges:
        assert _looks_like_merger(flat[idx])


def test_tag_stamps_silent_flags():
    # بِسْمِ ٱللَّهِ continuing: the hamza wasl + first lam of ٱللَّهِ are silent.
    words = _shard_words("1:1", 1, 2)

    annotate_segment_words("1:1", words)

    assert all(len(lt) == 4 for wd in words for lt in wd[3])
    stamped = _stamped(words)
    assert ("ٱ", True) in stamped  # hamza wasl silent when continuing
    assert ("ب", False) in stamped  # sounding consonant kept
    # Idempotent: a second pass overwrites slot 3 rather than growing the row.
    annotate_segment_words("1:1", words)
    assert _stamped(words) == stamped
    assert all(len(lt) == 4 for wd in words for lt in wd[3])


def test_tag_folds_silence_mark_onto_char():
    # 6:99 ٱنظُرُوٓا۟ : the otiose jama'a alef is silent AND its char carries the
    # silence mark folded on.
    n = len(letter_rows(result_for_ref("6:99")))
    words = _shard_words("6:99", 1, n)
    annotate_segment_words("6:99", words)
    assert ("ا۟", True) in _stamped(words)  # alef + ۟ (U+06DF), silent


def test_tag_silah_silent_only_when_word_stops():
    # فَضْلِهِۦ : the silah drops at a stop (gap-terminated run) and sounds when the
    # run continues to a following word.
    stop = _shard_words("2:90", 15, 15)
    annotate_segment_words("2:90", stop)
    assert ("ۦ", True) in _stamped(stop)

    cont = _shard_words("2:90", 15, 17)
    annotate_segment_words("2:90", cont)
    assert ("ۦ", False) in _stamped(cont)


def test_tag_stamps_silah_word():
    # 2:90 بِهِۦٓ — the stretch mark rides the mini-yaa it lengthens, so the two
    # are one letter row, as every shard in the bucket writes them. The run must
    # still stamp every letter (not NO-SLOT).
    words = _shard_words("2:90", 1, 3)
    annotate_segment_words("2:90", words)
    assert all(len(lt) == 4 for wd in words for lt in wd[3])  # every letter stamped
    chars = [lt[0] for wd in words for lt in wd[3]]
    assert "ۦٓ" in chars and "ۦ" not in chars


def test_stamp_silent_flags_noop_on_char_mismatch():
    # Letters that don't match the canonical text must be left untouched.
    word = [1, 0, 10, [["z", 0, 10], ["q", 0, 10]], [["x", 0, 10]]]
    annotate_segment_words("1:1", [word])
    assert word[3] == [["z", 0, 10], ["q", 0, 10]]  # unchanged, no 4th slot
