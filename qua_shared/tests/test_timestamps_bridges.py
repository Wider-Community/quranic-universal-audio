"""Tests for cross-word tajweed bridge detection + tagging.

The pure stamping logic (``_apply_bridge_tags``) is tested deterministically; the
phonemizer-backed detection is exercised when ``quranic_phonemizer`` is present.
"""
from __future__ import annotations

import pytest

from qua_shared.timestamps_bridges import (
    BRIDGE_RULES,
    _apply_bridge_tags,
    _looks_like_merger,
    detect_segment_bridges,
    tag_segment_words,
)


def _word(widx, phones):
    """Minimal compact word: [widx, start, end, letters, [[phone,s,e], ...]]."""
    return [widx, 0, 0, [], [[p, 0, 0] for p in phones]]


def test_looks_like_merger():
    assert _looks_like_merger("m̃")
    assert _looks_like_merger("ñ")
    assert _looks_like_merger("ll")
    assert _looks_like_merger("rˤrˤ")  # pharyngeal-insensitive doubled
    assert _looks_like_merger("ww")
    assert not _looks_like_merger("a")
    assert not _looks_like_merger("rˤ")  # single emphatic, not doubled
    assert not _looks_like_merger("")


def test_apply_bridge_tags_stamps_slot5():
    # flat phones: a(0) m̃(1) | i(2) rˤrˤ(3)
    words = [_word(1, ["a", "m̃"]), _word(2, ["i", "rˤrˤ"])]
    n = _apply_bridge_tags(words, {1: "idgham_shafawi", 3: "idgham_bila_ghunnah_noon"})
    assert n == 2
    assert words[0][4][1] == ["m̃", 0, 0, None, None, "idgham_shafawi"]
    assert words[1][4][1] == ["rˤrˤ", 0, 0, None, None, "idgham_bila_ghunnah_noon"]
    # untagged phones stay length-3
    assert words[0][4][0] == ["a", 0, 0]


def test_apply_bridge_tags_refuses_non_merger():
    # A drifted index pointing at a vowel must NOT be stamped.
    words = [_word(1, ["a", "b"])]
    assert _apply_bridge_tags(words, {0: "idgham_shafawi"}) == 0
    assert words[0][4][0] == ["a", 0, 0]


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
    for idx, rule in bridges:
        assert _looks_like_merger(flat[idx])
