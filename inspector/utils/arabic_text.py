"""Arabic text utilities: stripping Quranic decoration, letter extraction."""

import unicodedata as _ud

# Characters to strip from Quranic text for bare-skeleton comparison
_STRIP_CHARS = set("\u0640\u06de\u06e6\u06e9\u200f")


def strip_quran_deco(text: str) -> str:
    """Strip Quranic decoration and diacritics for bare-skeleton comparison."""
    text = _ud.normalize("NFD", text)
    out = []
    for ch in text:
        if ch in _STRIP_CHARS:
            continue
        if _ud.category(ch) == "Mn":
            continue
        out.append(ch)
    return "".join(out).strip()


def last_arabic_letter(text: str) -> str | None:
    """Return the last Arabic letter in text, ignoring diacritics and all non-letter markers.

    Scans backward after stripping diacritics/decoration so that waqf markers,
    sajdah signs, hizb markers, end-of-ayah (U+06DD), spaces, and any other
    non-letter symbols are never mistakenly returned as the last letter.
    """
    stripped = strip_quran_deco(text)
    for ch in reversed(stripped):
        if _ud.category(ch).startswith('L'):
            return ch
    return None
