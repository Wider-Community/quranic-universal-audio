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


def test_stops_order_yields_distinct_cache_keys():
    """The same set of stops in a different order is a different cache key
    (tuple identity) — that's fine; the FE always emits stops in word order
    so the cache hit rate stays high. Identity comparison would be ambiguous
    when both calls return the interned empty tuple, so we read cache_info()
    to assert two distinct cache slots were populated."""
    bridges_for_verse.cache_clear()
    bridges_for_verse("2:8", ("2:8:3", "2:8:5"))
    bridges_for_verse("2:8", ("2:8:5", "2:8:3"))
    info = bridges_for_verse.cache_info()
    assert info.misses == 2, "different orderings must populate distinct cache slots"
    assert info.hits == 0


def test_no_stops_returns_immutable_tuple():
    """The return type is ``tuple[BridgeInfo, ...]`` — important because
    lru_cache demands hashable returns and routes mustn't mutate a shared
    cached value."""
    out = bridges_for_verse("2:8", ())
    assert isinstance(out, tuple)
    with pytest.raises(AttributeError):
        out.append("nope")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Route tests — GET /api/ts/tajweed/<verse_ref>?stops=...
# ---------------------------------------------------------------------------


def test_route_no_stops(flask_client):
    """No-stops query returns the same bridge the service does, JSON-shaped."""
    resp = flask_client.get("/api/ts/tajweed/2:8")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["verse_ref"] == "2:8"
    assert body["stops"] == []
    assert body["bridges"] == [
        {"before_word_idx": 4, "rule": "idgham_ghunnah_noon", "side": "curr"}
    ]


def test_route_with_stops_query_param(flask_client):
    """Comma-separated ``stops`` query suppresses the cross-word rule at the
    pause boundary — mirrors what the FE will send after inferring stops from
    MFA word-end gaps."""
    resp = flask_client.get("/api/ts/tajweed/2:8?stops=2:8:3")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["stops"] == ["2:8:3"]
    assert body["bridges"] == []


def test_route_empty_stops_param_is_treated_as_no_stops(flask_client):
    """``?stops=`` (empty string) should NOT split into one empty stop ref."""
    resp = flask_client.get("/api/ts/tajweed/2:8?stops=")
    assert resp.status_code == 200
    assert resp.get_json()["stops"] == []


def test_route_compound_verse_ref(flask_client):
    """Compound refs flow through the path converter (the ``<path:>`` type
    keeps the dash intact, where ``<string:>`` would split on it)."""
    resp = flask_client.get("/api/ts/tajweed/37:151-37:152")
    assert resp.status_code == 200
    body = resp.get_json()
    rules = [b["rule"] for b in body["bridges"]]
    assert "idgham_shafawi" in rules


# ---------------------------------------------------------------------------
# Regressions found by the .local/scripts/validate_tajweed_bridges.py harness.
# Each represents a class of bug the data-driven validation caught.
# ---------------------------------------------------------------------------


def test_tanween_carrier_with_silent_trailing_letter_triggers():
    """``2:5: هُدًى مِّن`` — the idgham_ghunnah_tanween source rule sits on the
    د (the consonant carrying the fathatan), NOT on the trailing silent ى.
    The original code only inspected ``prev.entries[-1].source_rules`` and
    missed every tanween case where the carrier is followed by ا / ى / و.
    The trigger-scan now walks backward to find the rule-bearing entry."""
    out = bridges_for_verse("2:5", ())
    rules_at_boundary = {b.before_word_idx: b.rule for b in out}
    assert rules_at_boundary.get(4) == "idgham_ghunnah_tanween"


def test_word_internal_mutajanisayn_is_not_a_bridge():
    """``2:233: أَرَدتُّمْ أَن`` — the prev word `أَرَدتُّمْ` carries an internal
    idgham_mutajanisayn_kamil (د → ت silently within the word). The rule
    fires on a non-terminal entry of prev_w. The original code wrongly
    promoted it to a cross-word bridge into the next word `أَن`. Cross-word
    qualification now requires curr_w's first letter to target the same
    rule — which it doesn't here."""
    out = bridges_for_verse("2:233", ())
    boundaries = {b.before_word_idx for b in out}
    assert 46 not in boundaries, "word-internal mutajanisayn must not promote"


def test_tanween_with_internal_shaddah_picks_curr_side():
    """``2:36: قَرَارࣱ وَمَتَـٰعٌ`` — the trigger letter raa carries shaddah so
    its own phonemes contain a geminate ``rˤrˤ``. That word-internal
    gemination is NOT the cross-word merger; the merger ``w̃`` lives on
    next word's وَ. Side detection must check the trigger's LAST phoneme
    only (``u``, the vowel), not any phoneme on the trigger."""
    out = bridges_for_verse("2:36", ())
    rules_at_boundary = {b.before_word_idx: (b.rule, b.side) for b in out}
    # 2:36 has a tanween-meem (vowel side=curr) before وَمَتَـٰعٌ at word 17.
    assert rules_at_boundary.get(17) == ("idgham_ghunnah_tanween", "curr")
