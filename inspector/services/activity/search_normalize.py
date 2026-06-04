"""Arabic-aware search normalization.

Mirrors the frontend helper in
``inspector/frontend/src/lib/utils/fuzzy-match.ts`` so the
``/api/public/reciters?search=`` query and any future server-side fuzzy
match produce the same results as the in-browser dropdown filter.

Keep this in lockstep with the frontend implementation — the symmetry is
load-bearing for the picker's "search same string everywhere" promise.
"""

from __future__ import annotations

import re

# Strip diacritics + Quranic annotation marks (mirrors the frontend regex
# character classes; one-to-one with the SearchableSelect implementation).
_DIACRITIC_RE = re.compile(
    "["
    "ؐ-ؚ"  # Quranic annotations
    "ً-ٟ"  # Tanwin, sukun, shaddah, kasrah, etc.
    "ٰ"  # Superscript alef
    "ۖ-ۜ"
    "۟-ۤ"
    "ۧۨ"
    "۪-ۭ"
    "]"
)
_ALIF_VARIANTS_RE = re.compile("[أإآٱ]")
_TAA_MARBUTA_RE = re.compile("ة")
_ALIF_MAQSURA_RE = re.compile("ى")


def normalize_arabic(s: str) -> str:
    """Strip diacritics + normalize alif / taa-marbuta / alif-maqsura variants.

    Returns a lowercased ASCII-friendly string suitable for substring matching.
    The non-Arabic portion is lower-cased but otherwise untouched.
    """
    if not s:
        return ""
    s = _DIACRITIC_RE.sub("", s)
    s = _ALIF_VARIANTS_RE.sub("ا", s)
    s = _TAA_MARBUTA_RE.sub("ه", s)
    s = _ALIF_MAQSURA_RE.sub("ي", s)
    return s.lower()


def matches(haystack: str, needle: str) -> bool:
    """Case-insensitive Arabic-normalized substring match."""
    if not needle:
        return True
    return normalize_arabic(needle) in normalize_arabic(haystack)
