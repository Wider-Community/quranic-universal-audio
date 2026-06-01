"""Tests for cross-word tajweed bridge detection.

The service is pure (phonemizer in, BridgeInfo out — no DB, no bucket I/O),
so tests just exercise known idgham cases against real Hafs text and verify:

- Idgham ghunnah noon fires on ``man yaqūlu`` (2:8 wd3->wd4) as side="curr".
- A stop before that boundary suppresses the rule.
- Idgham shafawi fires on ``lahum mā`` (39:34 wd1->wd2) as side="prev".
- Within-word firings (e.g. ``bismi llāh`` 1:1 mutamathilayn) are NOT bridges.
- Mixed verse (11:42) returns the right rules in word-index order.
- Compound verse refs work.
- The lru_cache hits on a repeat call.
"""

from __future__ import annotations

import pytest

from services.reference.tajweed import bridges_for_verse


def _by_word(bridges):
    return {b.before_word_idx: (b.rule, b.side) for b in bridges}


def test_idgham_ghunnah_noon_man_yaqulu():
    """2:8 ``min an-nāsi man yaqūlu`` — cross-word noon idgham on word 4."""
    out = bridges_for_verse("2:8", ())
    assert _by_word(out) == {4: ("idgham_ghunnah_noon", "curr")}


def test_stop_kills_cross_word_idgham():
    """Passing a stop at word 3 makes the phonemizer treat ``man`` as a waqf,
    so the cross-word ghunnah disappears."""
    out = bridges_for_verse("2:8", ("2:8:3",))
    assert out == ()


def test_idgham_shafawi_lahum_ma():
    """39:34 ``lahum mā`` — meem-meem shafawi; the merged ``m̃`` lives at
    PREV-word's tail (the source meem)."""
    out = bridges_for_verse("39:34", ())
    assert _by_word(out) == {2: ("idgham_shafawi", "prev")}


def test_within_word_rules_are_not_bridges():
    """1:1 ``bismi llāhi r-raḥmāni r-raḥīm`` — every idgham here is
    within-word (``ٱللَّه``, ``ٱلرَّحْمَن``, ``ٱلرَّحِيم``); the bridge list is empty.
    lam_shamsiyah is intentionally NOT in scope either."""
    assert bridges_for_verse("1:1", ()) == ()


def test_mixed_verse_returns_in_word_order():
    """11:42 ``yā bunayya … wa-lā takun maʿa l-kāfirīn`` carries three
    in-scope cross-word firings in order: idgham_ghunnah_tanween at
    boundary 12->13, idgham_mutajanisayn_kamil at 14->15, idgham_ghunnah_noon
    at 17->18. All three target the next word's first phoneme."""
    out = bridges_for_verse("11:42", ())
    assert [(b.before_word_idx, b.rule, b.side) for b in out] == [
        (13, "idgham_ghunnah_tanween", "curr"),
        (15, "idgham_mutajanisayn_kamil", "curr"),
        (18, "idgham_ghunnah_noon", "curr"),
    ]


def test_compound_verse_ref_does_not_crash():
    """Cross-verse compounds (``s:a:w-s:a:w``) are accepted by the phonemizer
    and the service surfaces any in-scope cross-word firing within the
    range. ``37:151 - 37:152`` carries idgham_shafawi inside 37:151."""
    out = bridges_for_verse("37:151-37:152", ())
    assert any(b.rule == "idgham_shafawi" and b.side == "prev" for b in out)


def test_lru_cache_returns_identical_tuple():
    """Two calls with the same inputs return the same object — confirms the
    lru_cache fronts the phonemizer call. Concurrent route handlers share
    the result without re-running the phonemize."""
    first = bridges_for_verse("2:8", ())
    second = bridges_for_verse("2:8", ())
    assert first is second


def test_stops_order_independent_via_tuple_key():
    """The same set of stops in a different order is a different cache key
    (tuple identity) — that's fine; the FE always emits stops in word order
    so the cache hit rate stays high. This test just locks the behaviour."""
    a = bridges_for_verse("2:8", ("2:8:3",))
    b = bridges_for_verse("2:8", ("2:8:3",))
    assert a is b


def test_no_stops_returns_immutable_tuple():
    """The return type is ``tuple[BridgeInfo, ...]`` — important because
    lru_cache demands hashable returns and routes mustn't mutate a shared
    cached value."""
    out = bridges_for_verse("2:8", ())
    assert isinstance(out, tuple)
    with pytest.raises(AttributeError):
        out.append("nope")  # type: ignore[attr-defined]
