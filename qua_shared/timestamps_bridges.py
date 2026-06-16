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
**flat phoneme index** of each merger.

Indexing runs over *indexable* phones only — the phonemizer's letter-derived
phoneme sequence, excluding the render-only markers an aligner may additionally
store in a shard (the qalqala echo ``Q``). Such a marker carries no grapheme and
never appears in the phonemizer's flat sequence, so the shard's phones are
grouped into units (one indexable phone plus any markers trailing it) and a
bridge index lands on the unit's anchor. This keeps the detector and the shard in
one coordinate space no matter which render-only markers a given model emits, and
the markers ride along with their anchor through re-attribution untouched.

The 8 in-scope rules are the complete set of cross-word *mergers*; ikhfaa/iqlab
are cross-word but non-merging and out of scope. ``idgham_mutajanisayn_naqis``
(partial) never fires cross-word, so it is absent by construction.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

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

# Render-only phone markers an aligner may store in a shard that the phonemizer's
# letter-derived flat sequence does NOT contain — the qalqala echo ``Q``. They
# carry no grapheme, are excluded from the bridge index, and ride along with the
# indexable phone they trail. Extend this set if a model adds another such marker.
_RENDER_ONLY: frozenset[str] = frozenset({"Q"})


def _is_indexable(phone: str) -> bool:
    """A phone that participates in the phonemizer's flat phoneme index: a
    non-empty phone that is not a render-only marker (e.g. the qalqala ``Q``)."""
    return bool(phone) and phone not in _RENDER_ONLY


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

    ``counts[i]`` is word ``i``'s indexable phoneme count — non-indexable phones
    (empty strings, the qalqala ``Q`` marker) are excluded, so the counts re-slice
    the shard's indexable units (see ``_apply_to_words``) exactly.
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
        n = sum(1 for p in w.phonemes if _is_indexable(p))
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

    Three effects, all anchored to the phonemizer (the single source of truth):

    1. **Re-attribution** — the shard's flat phones are re-sliced into words by
       the phonemizer's natural per-word counts. The aligner's word-boundary
       allocation can park a phone on the wrong word (idgham shafawi: مِّن's kasra
       lands on شهداءكم after the merged meem); this restores each phone to its
       word so the FE stays a pure renderer. Word start/end are recomputed.
    2. **Tagging** — the merger phone grows to length 6 with its rule at slot 5
       (``[phone, start, end, None, None, rule]``; slots 3/4 are the FE reader's
       geminate flags).
    3. **Silent flags** — each letter grows a 4th slot ``silent`` (bool) from the
       phonemizer's ``silent_flags()`` so the highlight skips silent graphemes
       once each letter is its own cell. The segment is phonemized continuously,
       so verse-final waqf forms (a stopping tanween alef) render in their
       continuing form — a pausal refinement needs the true stop boundary.

    Returns the number of phones tagged. Skips (returns 0, no mutation) for
    repeats / out-of-order words, or if the phonemizer shape doesn't match the
    shard (indexable-unit count or word count) — a safety guard that never
    corrupts; a drop with bridges in hand is logged, never silent.
    """
    if not words:
        return 0
    widxs = [wd[0] for wd in words]
    if widxs != list(range(widxs[0], widxs[0] + len(widxs))):
        return 0
    lo, hi = widxs[0], widxs[-1]
    seg_ref = f"{verse_key}:{lo}" if lo == hi else f"{verse_key}:{lo}-{verse_key}:{hi}"
    mapping = pm.phonemize(ref=seg_ref).get_mapping()
    bridges, counts = _scan_mapping(mapping)
    _stamp_silent_flags(words, mapping)
    tagged = _apply_to_words(words, bridges, counts)
    if bridges and not tagged:
        # The shape guard tripped with bridges in hand — render-only markers are
        # handled, so this is genuine phonemizer/shard drift. Surface it; a silent
        # drop here is exactly how the qalqala-``Q`` regression hid for so long.
        log.warning(
            "bridge drift: %s detected %d bridge(s) but applied 0 (phonemizer "
            "shape != shard shape)", seg_ref, len(bridges)
        )
    return tagged


def _stamp_silent_flags(words: list, mapping) -> bool:
    """Append a 4th ``silent`` bool to every letter triple, in place.

    The phonemizer's per-grapheme silent flags are 1:1 with the shard's
    ``letters[]`` (same written-text tokenization); they are consumed in lockstep
    by character. No-op (returns False, no mutation) on any char-misalignment so a
    phonemizer/shard mismatch can never corrupt a letter.
    """
    from quranic_phonemizer.silent import build_silent_flags

    flags = build_silent_flags(mapping)
    letters = [lt for wd in words for lt in wd[3]]
    if [c for c, _ in flags] != [lt[0] for lt in letters]:
        return False
    for lt, (_, silent) in zip(letters, flags, strict=True):
        if len(lt) <= 3:
            lt.append(silent)
        else:
            lt[3] = silent
    return True


def _retime(word: list) -> None:
    """Set a word's start/end (slots 1/2) from its first/last phone."""
    phones = word[4]
    if phones:
        word[1] = phones[0][1]
        word[2] = phones[-1][2]


def _segment_units(words: list) -> list[list[list]]:
    """Group a segment's phones into indexable units across word order.

    Each unit is ``[anchor, *render_only_markers]`` — one indexable phone followed
    by any render-only markers (``Q``) that trail it. The unit sequence is the
    phonemizer's coordinate space (``counts`` index it), while every phone object
    is preserved in order so re-slicing the units back into words keeps the
    markers attached to their anchor. A leading marker with no anchor yet (never
    expected) seeds its own unit so nothing is dropped."""
    units: list[list[list]] = []
    for wd in words:
        for ph in wd[4]:
            if not ph[0]:
                continue
            if _is_indexable(ph[0]) or not units:
                units.append([ph])
            else:
                units[-1].append(ph)
    return units


def _apply_to_words(words: list, bridges: list[tuple[int, str]], counts: list[int]) -> int:
    """Re-slice ``words``' phones to ``counts`` and stamp ``bridges``, in place.

    ``counts`` is the phonemizer's per-word indexable-phone count; ``bridges`` is
    ``[(unit_index, rule), ...]``. Both index the segment's indexable *units* (an
    indexable phone plus any render-only markers trailing it — see
    ``_segment_units``), so a stored qalqala ``Q`` rides along instead of skewing
    the index. No-op + return 0 when the shapes don't line up with the shard
    (guards against corrupting on genuine phonemizer drift).

    The merger's *duration* is always owned by the FIRST word of the boundary so
    word highlighting / clips stay on it through the ghunnah: shafawi already
    lands on the prev word's tail, and for the head-merger rules (idgham
    ghunnah/bila-ghunnah …) the curr word's start is pushed past the merger and
    the prev word's end is extended to the merger's end. Phone attribution is
    untouched — the merger phone keeps its tag and renders in the bridge tile."""
    if len(counts) != len(words):
        return 0
    units = _segment_units(words)
    if sum(counts) != len(units):
        return 0

    tagged = 0
    for fidx, rule in bridges:
        if 0 <= fidx < len(units) and _looks_like_merger(units[fidx][0][0]):
            ph = units[fidx][0]
            while len(ph) <= _BRIDGE_SLOT:
                ph.append(None)
            ph[_BRIDGE_SLOT] = rule
            tagged += 1

    off = 0
    head_to_word: dict[int, int] = {}
    for wi, c in enumerate(counts):
        head_to_word[off] = wi
        words[wi][4] = [ph for unit in units[off : off + c] for ph in unit]
        off += c
        _retime(words[wi])

    for fidx, rule in bridges:
        if rule in _MERGER_ON_PREV:
            continue  # merger is the prev word's tail → first word already owns it
        if not (0 <= fidx < len(units)) or not _looks_like_merger(units[fidx][0][0]):
            continue
        w = head_to_word.get(fidx)  # head-merger rules land the merger at a word head
        if not w:  # None (not a head) or 0 (no prev word) → leave as-is
            continue
        cur = words[w][4]
        if len(cur) < 2:
            continue  # fully-dissolving word: nothing left to own its own span
        words[w - 1][2] = units[fidx][0][2]  # first word holds through the ghunnah
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
