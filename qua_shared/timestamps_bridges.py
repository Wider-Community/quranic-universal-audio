"""Cross-word tajweed bridge tagging for timestamp shards.

A *bridge* is a cross-word tajweed merger phoneme (idgham) — a nasalised
``m̃ ñ j̃ w̃`` or a geminated consonant (``ll rˤrˤ tt ww …``) that fuses the end
of one word into the start of the next. The Timestamps tab renders it as a tile
between two word blocks.

This module is the **single source** for bridge phonemes, shared by the live TS
pipeline (``timestamps_pipeline``) and the one-time backfill. ``tag_segment_words``
does two things to a segment, both anchored to the phonemizer:

- **Re-attribution** — re-slices the shard's flat phones into words by the
  phonemizer's natural per-word counts. The aligner's word-boundary allocation
  can park a phone on the wrong word (idgham shafawi: مِّن's kasra lands on
  شهداءكم's tail after the merged meem); this restores canonical attribution so
  the FE stays a pure renderer.
- **Tagging** — stamps each merger phone with its rule (slot 5 of the tuple).

It does NOT classify by phoneme shape (a geminate merger is byte-identical to a
within-word shaddah geminate — ``ٱلرَّحْمَٰن → rˤrˤ`` looks exactly like an idgham
``rˤrˤ``). It asks the phonemizer where the cross-word rules fire and uses the
**flat phoneme index** of each merger. The flat phone sequence of a segment is
allocation-invariant and reproduces the shard's stored phones byte-for-byte
(verified across the published corpus), so the index lands on the right phone.

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


def _scan_mapping(mapping) -> tuple[list[tuple[int, str]], list[int]]:
    """Return ``(bridges, counts)`` for a phonemizer ``get_mapping()`` result.

    ``counts[i]`` is word ``i``'s shard-visible phoneme count — empty-string
    phonemes and the ``Q`` qalqala marker (dropped by ``transform_phonemes``)
    are excluded, so the counts re-slice the shard's flat phone array exactly.
    ``bridges`` is ``[(flat_phoneme_index, rule), ...]``: shafawi's merger is the
    previous word's last phoneme (``…m̃ |``), every other rule's is the current
    word's first (``| m̃ / | ll …``).

    Uses the phonemizer's natural per-word attribution (``get_mapping``) — NOT
    ``letter_phoneme_mappings()``, which reassigns merger phonemes across word
    boundaries. The flat sequence is allocation-invariant and reproduces the
    shard byte-for-byte.
    """
    words = mapping.words
    counts: list[int] = []
    spans: list[tuple[int, int] | None] = []
    acc = 0
    for w in words:
        n = sum(1 for p in w.phonemes if p and p != "Q")
        counts.append(n)
        spans.append((acc, acc + n - 1) if n else None)
        acc += n

    bridges: list[tuple[int, str]] = []
    for i in range(len(words) - 1):
        prev, curr = words[i], words[i + 1]
        if not prev.letter_mappings or not curr.letter_mappings:
            continue
        curr_targets = {
            t.rule.value for t in curr.letter_mappings[0].tajweed_rules if not t.is_source
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
        span = spans[i] if rule in _MERGER_ON_PREV else spans[i + 1]
        if span is None:
            continue
        bridges.append((span[1] if rule in _MERGER_ON_PREV else span[0], rule))

    return bridges, counts


def detect_segment_bridges(pm, seg_ref: str) -> list[tuple[int, str]]:
    """Return ``[(flat_phoneme_index, rule), ...]`` for one segment ref."""
    return _scan_mapping(pm.phonemize(ref=seg_ref).get_mapping())[0]


def tag_segment_words(pm, verse_key: str, words: list) -> int:
    """Tag bridges + canonicalise phone attribution on one segment, in place.

    ``words`` is a segment's word list as written to the shard — each word is
    ``[widx, start_ms, end_ms, [[char,s,e]...], [[phone,s,e]...]]`` in ascending,
    contiguous word order. ``verse_key`` is the segment's home verse (``"2:48"``).

    Two effects, both anchored to the phonemizer (the single source of truth):

    1. **Re-attribution** — the shard's flat phones are re-sliced into words by
       the phonemizer's natural per-word counts. The aligner's word-boundary
       allocation can park a phone on the wrong word (idgham shafawi: مِّن's kasra
       lands on شهداءكم after the merged meem); this restores each phone to its
       word so the FE stays a pure renderer. Word start/end are recomputed.
    2. **Tagging** — the merger phone grows to length 6 with its rule at slot 5
       (``[phone, start, end, None, None, rule]``; slots 3/4 are the FE reader's
       geminate flags).

    Returns the number of phones tagged. Skips (returns 0, no mutation) for
    repeats / out-of-order words, or if the phonemizer shape doesn't match the
    shard (flat count or word count) — a safety guard that never corrupts.
    """
    if not words:
        return 0
    widxs = [wd[0] for wd in words]
    if widxs != list(range(widxs[0], widxs[0] + len(widxs))):
        return 0
    lo, hi = widxs[0], widxs[-1]
    seg_ref = f"{verse_key}:{lo}" if lo == hi else f"{verse_key}:{lo}-{verse_key}:{hi}"
    bridges, counts = _scan_mapping(pm.phonemize(ref=seg_ref).get_mapping())
    return _apply_to_words(words, bridges, counts)


def _retime(word: list) -> None:
    """Set a word's start/end (slots 1/2) from its first/last phone."""
    phones = word[4]
    if phones:
        word[1] = phones[0][1]
        word[2] = phones[-1][2]


def _apply_to_words(words: list, bridges: list[tuple[int, str]], counts: list[int]) -> int:
    """Re-slice ``words``' phones to ``counts`` and stamp ``bridges``, in place.

    ``counts`` is the phonemizer's per-word phone count; ``bridges`` is
    ``[(flat_index, rule), ...]``. Both index the segment's flat phone array (all
    phones across words in order). No-op + return 0 when the shapes don't line up
    with the shard (guards against corrupting on unexpected phonemizer drift).

    The merger's *duration* is always owned by the FIRST word of the boundary so
    word highlighting / clips stay on it through the ghunnah: shafawi already
    lands on the prev word's tail, and for the head-merger rules (idgham
    ghunnah/bila-ghunnah …) the curr word's start is pushed past the merger and
    the prev word's end is extended to the merger's end. Phone attribution is
    untouched — the merger phone keeps its tag and renders in the bridge tile."""
    if len(counts) != len(words):
        return 0
    flat = [ph for wd in words for ph in wd[4] if ph[0]]
    if sum(counts) != len(flat):
        return 0

    tagged = 0
    for fidx, rule in bridges:
        if 0 <= fidx < len(flat) and _looks_like_merger(flat[fidx][0]):
            ph = flat[fidx]
            while len(ph) <= _BRIDGE_SLOT:
                ph.append(None)
            ph[_BRIDGE_SLOT] = rule
            tagged += 1

    off = 0
    head_to_word: dict[int, int] = {}
    for wi, c in enumerate(counts):
        head_to_word[off] = wi
        words[wi][4] = flat[off : off + c]
        off += c
        _retime(words[wi])

    for fidx, rule in bridges:
        if rule in _MERGER_ON_PREV:
            continue  # merger is the prev word's tail → first word already owns it
        if not (0 <= fidx < len(flat)) or not _looks_like_merger(flat[fidx][0]):
            continue
        w = head_to_word.get(fidx)  # head-merger rules land the merger at a word head
        if not w:  # None (not a head) or 0 (no prev word) → leave as-is
            continue
        cur = words[w][4]
        if len(cur) < 2:
            continue  # fully-dissolving word: nothing left to own its own span
        words[w - 1][2] = flat[fidx][2]  # first word holds through the ghunnah
        words[w][1] = cur[1][1]  # second word starts at its next phone
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
