"""Cross-word tajweed bridge tagging for timestamp shards.

A *bridge* is a cross-word tajweed merger phoneme (idgham) — a nasalised
``m̃ ñ j̃ w̃`` or a geminated consonant (``ll rˤrˤ tt ww …``) that fuses the end
of one word into the start of the next. The Timestamps tab renders it as a tile
between two word blocks.

This module is the **single source** for locating bridge phonemes, shared by:

- the live TS pipeline (``timestamps_pipeline._normalize_from_results``), which
  stamps the tag onto freshly-aligned shards, and
- the one-time backfill, which stamps existing shards.

It does NOT classify by phoneme shape (a geminate merger is byte-identical to a
within-word shaddah geminate — ``ٱلرَّحْمَٰن → rˤrˤ`` looks exactly like an idgham
``rˤrˤ``). Instead it asks the phonemizer where the cross-word rules fire and
returns the **flat phoneme index** of each merger. The flat phone sequence of a
segment is allocation-invariant and reproduces the shard's stored phones exactly
(verified byte-for-byte across the published corpus), so a flat index resolved
here lands on the correct shard interval regardless of word-boundary allocation.

The 8 in-scope rules are the complete set of cross-word *mergers*; ikhfaa/iqlab
are cross-word but non-merging and out of scope. ``idgham_mutajanisayn_naqis``
(partial) never fires cross-word, so it is absent by construction.
"""

from __future__ import annotations

# Source rules that produce a cross-word merger phoneme. Values are the
# quranic_phonemizer TajweedRule enum ``.value`` strings.
BRIDGE_RULES: frozenset[str] = frozenset(
    {
        "idgham_ghunnah_noon",
        "idgham_ghunnah_tanween",
        "idgham_shafawi",
        "idgham_bila_ghunnah_noon",
        "idgham_bila_ghunnah_tanween",
        "idgham_mutamathilayn",
        "idgham_mutaqaribayn",
        "idgham_mutajanisayn_kamil",
    }
)

# The lone rule whose merger lives at the PREV word's tail (``…m̃ |``); every
# other rule's merger is the CURR word's first phoneme (``| m̃ / | ll …``).
# Verified against every cross-word firing in the muṣḥaf.
_MERGER_ON_PREV: frozenset[str] = frozenset({"idgham_shafawi"})

# The bridge rule string occupies index 5 of a compact phone tuple
# ``[phone, start_ms, end_ms, geminate_start, geminate_end, bridge_rule]``;
# slots 3/4 (geminate flags, unused in the segment-array shard) are padded so
# the FE reader's fixed positions are preserved.
_BRIDGE_SLOT = 5


def _looks_like_merger(phone: str) -> bool:
    """A nasalised (combining tilde / ``ñ``) or geminated (doubled consonant,
    pharyngeal-insensitive) phone — the shape every cross-word merger takes.

    Used only as a defensive guard at tag time so a future index drift can never
    silently stamp a vowel; the authoritative signal is the rule's flat index."""
    if not phone:
        return False
    if "̃" in phone or "ñ" in phone:
        return True
    base = phone.replace("ˤ", "")
    return len(base) >= 2 and base[0] == base[1]


def detect_segment_bridges(pm, seg_ref: str) -> list[tuple[int, str]]:
    """Return ``[(flat_phoneme_index, rule), ...]`` for one segment.

    ``seg_ref`` is the segment's word-range ref (e.g. ``"2:2:1-2:2:4"`` or a
    single ``"2:5:3"``) — the same range that produced the shard's phones, so the
    last word is pausal and cross-word rules at the pause are naturally
    suppressed. ``pm`` is a ``quranic_phonemizer.Phonemizer``.

    Uses ``get_mapping()`` (the phonemizer's natural per-word attribution) — NOT
    ``letter_phoneme_mappings()``, which reassigns merger phonemes across word
    boundaries and would shift the flat offset off the merger. The flat index
    counts non-empty word-level phonemes in word order and aligns 1:1 with the
    shard's flattened phone array (the flat sequence is allocation-invariant and
    reproduces the shard byte-for-byte).
    """
    mapping = pm.phonemize(ref=seg_ref).get_mapping()
    words = mapping.words
    out: list[tuple[int, str]] = []

    # Flat span [first_idx, last_idx] of each word's shard-visible phonemes
    # (None if the word contributes none). The shard drops empty-string phonemes
    # and the ``Q`` qalqala marker (``transform_phonemes``), so the flat count
    # must drop them too for positions to align. Mergers are never ``Q``.
    spans: list[tuple[int, int] | None] = []
    acc = 0
    for w in words:
        n = sum(1 for p in w.phonemes if p and p != "Q")
        spans.append((acc, acc + n - 1) if n else None)
        acc += n

    for i in range(len(words) - 1):
        prev, curr = words[i], words[i + 1]
        if not prev.letter_mappings or not curr.letter_mappings:
            continue
        curr_targets = {
            t.rule.value
            for t in curr.letter_mappings[0].tajweed_rules
            if not t.is_source
        }
        rule = None
        for e in reversed(prev.letter_mappings):
            srcs = {t.rule.value for t in e.tajweed_rules if t.is_source}
            cross = (srcs & curr_targets) & BRIDGE_RULES
            if cross:
                rule = sorted(cross)[0]
                break
        if rule is None:
            continue

        # shafawi's merger is the prev word's last phoneme (…m̃ |); every other
        # rule's merger is the curr word's first phoneme (| m̃ / | ll …).
        span = spans[i] if rule in _MERGER_ON_PREV else spans[i + 1]
        if span is None:
            continue
        flat = span[1] if rule in _MERGER_ON_PREV else span[0]
        out.append((flat, rule))

    return out


def tag_segment_words(pm, verse_key: str, words: list) -> int:
    """Stamp bridge rules onto a single segment's compact word list, in place.

    ``words`` is a segment's word list as written to the shard — each word is
    ``[widx, start_ms, end_ms, [[char,s,e]...], [[phone,s,e]...]]`` in ascending,
    contiguous word order. ``verse_key`` is the segment's home verse (``"2:48"``).

    A tagged phone tuple grows to length 6:
    ``[phone, start, end, None, None, rule]`` (slots 3/4 kept for the FE reader's
    geminate flags). Returns the number of phones tagged.

    Skips segments whose word indices aren't ascending-contiguous (repeats /
    out-of-order passes) — those can't be reproduced by a single range phonemize
    and are handled upstream. Defensively refuses to tag a phone that doesn't
    look like a merger, so an unexpected drift never mis-stamps a vowel.
    """
    if not words:
        return 0
    widxs = [wd[0] for wd in words]
    if widxs != list(range(widxs[0], widxs[0] + len(widxs))):
        return 0
    lo, hi = widxs[0], widxs[-1]
    seg_ref = f"{verse_key}:{lo}" if lo == hi else f"{verse_key}:{lo}-{verse_key}:{hi}"
    bridges = dict(detect_segment_bridges(pm, seg_ref))
    if not bridges:
        return 0
    return _apply_bridge_tags(words, bridges)


def _apply_bridge_tags(words: list, bridges: dict[int, str]) -> int:
    """Stamp ``{flat_index: rule}`` onto a segment's compact phone tuples.

    Flat index counts non-empty phones across ``words`` in order (matching
    ``detect_segment_bridges``). A tagged tuple grows to length 6 with ``rule``
    at slot 5. Defensively refuses to tag a phone that doesn't look like a
    merger. Returns the number of phones tagged."""
    tagged = 0
    flat = 0
    for wd in words:
        for ph in wd[4]:
            if not ph[0]:
                continue
            rule = bridges.get(flat)
            if rule is not None and _looks_like_merger(ph[0]):
                while len(ph) <= _BRIDGE_SLOT:
                    ph.append(None)
                ph[_BRIDGE_SLOT] = rule
                tagged += 1
            flat += 1
    return tagged


def tag_v2_doc(pm, v2_doc: dict) -> int:
    """Stamp bridge tags across every occurrence of a raw v2 document, in place.

    ``v2_doc`` is the ``build_raw_v2`` shape (``{output_key: [occurrence, ...]}``
    plus ``_meta``). Each occurrence's ``words_by_verse`` carries one verse's
    words. Returns the total number of phones tagged.
    """
    total = 0
    for key, occs in v2_doc.items():
        if key == "_meta" or not isinstance(occs, list):
            continue
        for occ in occs:
            for verse_key, words in (occ.get("words_by_verse") or {}).items():
                total += tag_segment_words(pm, verse_key, words)
    return total
