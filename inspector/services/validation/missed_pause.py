"""Missed-pause candidate detection for the ``missed_pause`` category.

A candidate word bears a Quranic stop/pause sign (U+06D6..U+06DC) AND ends in
one of the pausal letters ه / ة / م / ن or any hamza seat after stripping
diacritics/decoration — the segmenter's known missed-pause classes. A segment
flags when such a word
sits strictly inside its matched word range (not the first word, not the
last): the stop sign gives a high pause prior, and non-edge means the
segmenter did not split there.

The candidate set is derived once from the Digital Khatt word map and cached
at module level (lazy).
"""

from __future__ import annotations

import unicodedata as _ud

from services.storage.data_loader import get_dk_words_flat, get_word_counts

# Quranic stop/pause signs: ۖ ۗ ۘ ۙ ۚ ۛ ۜ (U+06D6..U+06DC).
PAUSE_SIGNS: frozenset[str] = frozenset(chr(c) for c in range(0x06D6, 0x06DD))

# Hamza seats, all reported as a single ``ء`` class: ء (U+0621), أ (U+0623),
# ؤ (U+0624), إ (U+0625), ئ (U+0626). Word-final آ (U+0622) is excluded — its
# coda is the madd, not the glottal stop.
HAMZA: str = "ء"
HAMZA_SEATS: frozenset[str] = frozenset({"ء", "أ", "ؤ", "إ", "ئ"})

# Pausal finals the segmenter is known to miss:
# ه (U+0647), ة (U+0629), م (U+0645), ن (U+0646), and any hamza seat.
PAUSAL_FINALS: frozenset[str] = frozenset({"ه", "ة", "م", "ن"}) | HAMZA_SEATS

# Runaway-ayah guard; mirrors ``quran_refs.dk_text_for_ref``.
_MAX_AYAH_BOUNDARY = 300

_candidates: frozenset[str] | None = None


def candidate_locs() -> frozenset[str]:
    """Lazy cached set of candidate word locations (``"surah:ayah:word"``)."""
    global _candidates
    if _candidates is None:
        _candidates = frozenset(
            loc
            for loc, text in get_dk_words_flat().items()
            if any(s in text for s in PAUSE_SIGNS) and pausal_letter_for(text) is not None
        )
    return _candidates


def pause_mark_for(text: str) -> str | None:
    """Return the first stop/pause sign character found in ``text``, or None."""
    for ch in text:
        if ch in PAUSE_SIGNS:
            return ch
    return None


def interior_candidate_locs(
    surah: int, s_ayah: int, s_word: int, e_ayah: int, e_word: int
) -> list[str]:
    """Candidate locs strictly inside the word range (both edges excluded).

    Walks (ayah, word) from the start endpoint to the end endpoint using the
    canonical per-verse word counts (same pattern as ``dk_text_for_ref``),
    skipping the range's first and last word. Ranges of fewer than three
    words therefore never yield a loc.
    """
    if (s_ayah, s_word) >= (e_ayah, e_word):
        return []
    cands = candidate_locs()
    wc = get_word_counts()
    out: list[str] = []
    ay, w = s_ayah, s_word
    first = True
    while (ay, w) <= (e_ayah, e_word):
        if not first and (ay, w) != (e_ayah, e_word):
            loc = f"{surah}:{ay}:{w}"
            if loc in cands:
                out.append(loc)
        first = False
        w += 1
        if w > wc.get((surah, ay), 0):
            w = 1
            ay += 1
            if ay > _MAX_AYAH_BOUNDARY:
                break
    return out


# Quranic small high letters: ۥ (U+06E5), ۦ (U+06E6). Silent madd carriers that
# trail the real coda and are category ``Lo``, so a plain letter scan returns
# them instead of the ه they follow.
_SILENT_CARRIERS: frozenset[str] = frozenset({"ۥ", "ۦ"})


def _raw_final_letter(text: str) -> str | None:
    """Last spoken letter of ``text``, unnormalised.

    Two things a generic scan gets wrong here: ``strip_quran_deco`` folds a
    seated hamza onto its carrier (أ→ا, ؤ→و, ئ→ي), erasing a hamza coda, and
    the silent small-letter carriers outrank the coda they follow.
    """
    for ch in reversed(text):
        if ch in _SILENT_CARRIERS:
            continue
        if _ud.category(ch) == "Lo":
            return ch
    return None


def pausal_letter_for(text: str) -> str | None:
    """Return the word's final pausal letter, or None.

    Every hamza seat collapses to ``ء`` so the accordion shows one hamza
    filter rather than one per seat.
    """
    last = _raw_final_letter(text)
    if last in HAMZA_SEATS:
        return HAMZA
    return last if last in PAUSAL_FINALS else None


__all__ = [
    "HAMZA",
    "HAMZA_SEATS",
    "PAUSAL_FINALS",
    "PAUSE_SIGNS",
    "candidate_locs",
    "interior_candidate_locs",
    "pausal_letter_for",
    "pause_mark_for",
]
