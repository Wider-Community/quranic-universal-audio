"""Tests for cross-word tajweed bridge detection + tagging.

The pure re-slice/stamp core (``_apply_to_words``) is tested deterministically;
the phonemizer-backed detection is exercised when ``quranic_phonemizer`` present.
"""

from __future__ import annotations

import pytest

from qua_shared.timestamps_bridges import (
    BRIDGE_RULES,
    _apply_to_words,
    _looks_like_merger,
    detect_segment_bridges,
    tag_segment_words,
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


def test_apply_refuses_non_merger_index():
    # A drifted index pointing at a vowel must NOT be stamped.
    words = [_word(1, ["a", "b"])]
    assert _apply_to_words(words, [(0, "idgham_shafawi")], [2]) == 0
    assert words[0][4][0] == ["a", 0, 1]


def test_apply_noop_on_shape_mismatch():
    # Phonemizer count total != shard flat count → skip, no mutation.
    words = [_word(1, ["a", "m̃"])]
    before = [list(p) for p in words[0][4]]
    assert _apply_to_words(words, [(1, "idgham_shafawi")], [5]) == 0
    assert words[0][4] == before


def test_tag_segment_words_skips_non_contiguous():
    # Repeat / out-of-order word indices can't be range-phonemized → no tag.
    words = [_word(3, ["m̃"]), _word(1, ["a"])]
    assert tag_segment_words(object(), "2:5", words) == 0


# --- phonemizer-backed detection -------------------------------------------

pytestmark_pm = pytest.importorskip("quranic_phonemizer", reason="phonemizer not installed")


@pytest.fixture(scope="module")
def pm():
    from quranic_phonemizer import Phonemizer

    return Phonemizer()


def _flat(pm, ref):
    gm = pm.phonemize(ref=ref).get_mapping()
    return [p for w in gm.words for p in w.phonemes if p and p != "Q"]


def test_detect_known_bridges(pm):
    # 2:5 ...هُدࣰى مِّن رَّبِّهِمْ : tanween→meem (m̃) then noon→raa (rˤrˤ).
    flat = _flat(pm, "2:5")
    bridges = detect_segment_bridges(pm, "2:5")
    rules = {r for _, r in bridges}
    assert "idgham_ghunnah_tanween" in rules
    assert "idgham_bila_ghunnah_noon" in rules
    # every detected index lands on a real merger phone in the flat sequence
    for idx, rule in bridges:
        assert rule in BRIDGE_RULES
        assert _looks_like_merger(flat[idx])


def test_detect_shafawi_on_prev_tail(pm):
    # 2:10 ...فِی قُلُوبِهِم مَّرَضٌ : idgham shafawi, merger m̃ on prev tail.
    bridges = detect_segment_bridges(pm, "2:10")
    assert any(r == "idgham_shafawi" for _, r in bridges)
    flat = _flat(pm, "2:10")
    for idx, _rule in bridges:
        assert _looks_like_merger(flat[idx])
