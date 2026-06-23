"""Tests for cross-word tajweed bridge detection + tagging.

The pure re-slice/stamp core (``_apply_to_words``) is tested deterministically;
the phonemizer-backed detection is exercised when ``quranic_phonemizer`` present.
"""

from __future__ import annotations

import pytest

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


def test_apply_reattributes_shafawi_kasra_to_next_word():
    # Aligner parked مِّن's kasra "i" on شهداءكم after the merged meem (m̃);
    # canonical counts put شهداءكم=[k,u,m̃], مِّن=[i,ŋ]. Flat: k u m̃ | i ŋ.
    words = [_word(14, ["k", "u", "m̃", "i"]), _word(15, ["ŋ"], t0=4)]
    n = _apply_to_words(words, [(2, "idgham_shafawi")], [3, 2])
    assert n == 1
    # شهداءكم keeps k u m̃ (m̃ tagged); the stranded kasra moved to مِّن's head.
    assert [p[0] for p in words[0][4]] == ["k", "u", "m̃"]
    assert words[0][4][2] == ["m̃", 2, 3, None, None, "idgham_shafawi"]
    assert [p[0] for p in words[1][4]] == ["i", "ŋ"]
    # word start/end re-timed from the new phone slices.
    assert words[0][1] == 0 and words[0][2] == 3  # k.start .. m̃.end
    assert words[1][1] == 3 and words[1][2] == 5  # i.start .. ŋ.end


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
    # along on its word. (Pre-fix this counted Q in `flat`, tripped the guard, and
    # dropped EVERY bridge in the segment — the 37.6% prod regression.)
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
    # Shafawi merger on prev tail + a trailing Q on the second word.
    words = [_word(14, ["k", "u", "m̃", "i"]), _word(15, ["ŋ", "Q"], t0=4)]
    n = _apply_to_words(words, [(2, "idgham_shafawi")], [3, 2])
    assert n == 1
    assert [p[0] for p in words[0][4]] == ["k", "u", "m̃"]
    assert words[0][4][2][_BRIDGE_SLOT] == "idgham_shafawi"
    assert [p[0] for p in words[1][4]] == ["i", "ŋ", "Q"]  # kasra re-attributed, Q kept


# --- phonemizer-backed detection -------------------------------------------

pytestmark_pm = pytest.importorskip("quranic_phonemizer", reason="phonemizer not installed")


@pytest.fixture(scope="module")
def pm():
    from quranic_phonemizer import Phonemizer

    return Phonemizer()


def test_annotate_segment_words_skips_non_contiguous():
    # Repeat / out-of-order word indices can't be range-phonemized → no bridge tag
    # (silent-stamping still no-ops here: these words carry no letters). The SDK
    # annotator reaches the phonemizer via its domain layer (no pm handle).
    words = [_word(3, ["m̃"]), _word(1, ["a"])]
    assert annotate_segment_words("2:5", words) == 0


def _flat(pm, ref):
    gm = pm.phonemize(ref=ref).get_mapping()
    return [p for w in gm.words for p in w.phonemes if p and p != "Q"]


def test_detect_known_bridges(pm):
    # 2:5 ...هُدࣰى مِّن رَّبِّهِمْ : tanween→meem (m̃) then noon→raa (rˤrˤ).
    flat = _flat(pm, "2:5")
    bridges = detect_segment_bridges("2:5")
    rules = {r for _, r in bridges}
    assert "idgham_ghunnah_tanween" in rules
    assert "idgham_bila_ghunnah_noon" in rules
    # every detected index lands on a real merger phone in the flat sequence
    for idx, rule in bridges:
        assert rule in BRIDGE_RULES
        assert _looks_like_merger(flat[idx])


def test_detect_shafawi_on_prev_tail(pm):
    # 2:10 ...فِی قُلُوبِهِم مَّرَضٌ : idgham shafawi, merger m̃ on prev tail.
    bridges = detect_segment_bridges("2:10")
    assert any(r == "idgham_shafawi" for _, r in bridges)
    flat = _flat(pm, "2:10")
    for idx, _rule in bridges:
        assert _looks_like_merger(flat[idx])


_SPLIT_EXT = {"ٰ", "ۥ", "ۦ"}


def _shard_word(widx, word_mapping):
    """A minimal shard word with contiguous word timing (no internal gap → one
    run) whose letters use the shard's written-grapheme tokenization: split the
    standalone extensions (dagger/mini), merge every other combining mark (the
    maddah) onto the grapheme it follows — so a madd-silah is one ``ۦٓ`` token."""
    ws, we = (widx - 1) * 100, widx * 100
    letters: list = []
    for lm in word_mapping.letter_mappings:
        tokens: list = []
        for ch in lm.char + "".join(e.char for e in lm.extensions if e.char):
            if not tokens or ch in _SPLIT_EXT:
                tokens.append(ch)
            else:
                tokens[-1] += ch
        letters.extend([tok, ws, we] for tok in tokens)
    return [widx, ws, we, letters, [["x", ws, we]]]


def test_tag_stamps_silent_flags_matching_phonemizer(pm):
    # بِسْمِ ٱللَّهِ continuing: the hamza wasl + first lam of ٱللَّهِ are silent.
    res = pm.phonemize(ref="1:1:1-1:1:2")
    words = [_shard_word(i + 1, w) for i, w in enumerate(res.get_mapping().words)]

    annotate_segment_words("1:1", words)

    stamped = [(lt[0], lt[3]) for wd in words for lt in wd[3]]
    assert all(len(lt) == 4 for wd in words for lt in wd[3])
    # char carries any silence mark folded on; silent matches the phonemizer.
    assert stamped == [(c + m, s) for c, s, m in res.silent_flags()]
    assert ("ٱ", True) in stamped  # hamza wasl silent when continuing
    assert ("ب", False) in stamped  # sounding consonant kept


def test_tag_folds_silence_mark_onto_char(pm):
    # 6:99 ٱنظُرُوٓا۟ : the otiose jama'a alef is silent AND its char carries the
    # SILENT_ALWAYS mark folded on (which get_full_char alone drops).
    res = pm.phonemize(ref="6:99")
    words = [_shard_word(i + 1, w) for i, w in enumerate(res.get_mapping().words)]
    annotate_segment_words("6:99", words)
    stamped = [(lt[0], lt[3]) for wd in words for lt in wd[3]]
    assert ("ا۟", True) in stamped  # alef + ۟ (U+06DF), silent


def test_tag_silah_silent_only_when_word_stops(pm):
    # فَضْلِهِۦ : the silah drops at a stop (gap-terminated run) and sounds when the
    # run continues to a following word.
    res = pm.phonemize(ref="2:90:15")
    stop = [_shard_word(15, res.get_mapping().words[0])]
    annotate_segment_words("2:90", stop)
    assert ("ۦ", True) in [(lt[0], lt[3]) for lt in stop[0][3]]

    res2 = pm.phonemize(ref="2:90:15-2:90:17")
    cont = [_shard_word(15 + i, w) for i, w in enumerate(res2.get_mapping().words)]
    annotate_segment_words("2:90", cont)
    assert ("ۦ", False) in [(lt[0], lt[3]) for lt in cont[0][3]]


def test_tag_stamps_silah_maddah_word(pm):
    # 2:90 بِهِۦٓ — the madd-silah ۦٓ is one grapheme; the segment must stamp (not
    # NO-SLOT) — guards the maddah-after-split tokenization match.
    res = pm.phonemize(ref="2:90:1-2:90:3")
    words = [_shard_word(i + 1, w) for i, w in enumerate(res.get_mapping().words)]
    annotate_segment_words("2:90", words)
    assert all(len(lt) == 4 for wd in words for lt in wd[3])  # every letter stamped
    assert "ۦٓ" in [lt[0] for wd in words for lt in wd[3]]  # silah+maddah one token


def test_stamp_silent_flags_noop_on_char_mismatch(pm):
    # Letters that don't match the canonical text must be left untouched.
    word = [1, 0, 10, [["z", 0, 10], ["q", 0, 10]], [["x", 0, 10]]]
    annotate_segment_words("1:1", [word])
    assert word[3] == [["z", 0, 10], ["q", 0, 10]]  # unchanged, no 4th slot
