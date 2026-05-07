"""Phoneme tail matching: detect boundary adjustment issues via ASR vs. canonical tails."""

import json

from config import PHONEME_SUB_COSTS_PATH
from constants import BOUNDARY_VOWELS
from services import cache
from services.data_loader import get_word_counts


def get_phoneme_sub_pairs() -> set[frozenset]:
    """Load phoneme substitution equivalence pairs (lazy, cached)."""
    cached = cache.get_phoneme_sub_pairs_cache()
    if cached is not None:
        return cached
    pairs: set[frozenset] = set()
    if PHONEME_SUB_COSTS_PATH.exists():
        with open(PHONEME_SUB_COSTS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for category, entries in data.items():
            if category == "_meta":
                continue
            for key in entries:
                a, b = key.split("|", 1)
                pairs.add(frozenset((a, b)))
    cache.set_phoneme_sub_pairs_cache(pairs)
    return pairs


def phonemes_match(a: str, b: str, sub_pairs: set[frozenset]) -> bool:
    """Check if two phonemes are equal or equivalent via substitution costs."""
    return a == b or frozenset((a, b)) in sub_pairs


def tails_match(canonical_tail: list[str], asr_tail: list[str],
                sub_pairs: set[frozenset]) -> bool:
    """Check if two phoneme tails match, allowing known substitutions."""
    if len(canonical_tail) != len(asr_tail):
        return False
    return all(phonemes_match(c, a, sub_pairs) for c, a in zip(canonical_tail, asr_tail))


def get_phoneme_tails(phonemes_asr: str, matched_ref: str,
                      canonical: dict[str, list[str]], n: int
                      ) -> tuple[list[str], list[str]] | None:
    """Return (canonical_tail, asr_tail) of length *n*, or ``None`` if unavailable."""
    if not phonemes_asr or not matched_ref or not canonical:
        return None

    asr_tokens = phonemes_asr.split()
    if len(asr_tokens) < n:
        return None

    parts = matched_ref.split("-")
    if len(parts) != 2:
        return None
    sp = parts[0].split(":")
    ep = parts[1].split(":")
    if len(sp) != 3 or len(ep) != 3:
        return None
    try:
        surah = int(sp[0])
        s_ayah, s_word = int(sp[1]), int(sp[2])
        e_ayah, e_word = int(ep[1]), int(ep[2])
    except (ValueError, IndexError):
        return None

    # Build canonical phoneme list from end words backwards until we have >= n
    canonical_tail: list[str] = []
    if s_ayah == e_ayah:
        for w in range(e_word, s_word - 1, -1):
            word_phonemes = canonical.get(f"{surah}:{s_ayah}:{w}", [])
            canonical_tail = word_phonemes + canonical_tail
            if len(canonical_tail) >= n:
                break
    else:
        word_counts = get_word_counts()
        for ayah in range(e_ayah, s_ayah - 1, -1):
            w_start = s_word if ayah == s_ayah else 1
            w_end = e_word if ayah == e_ayah else word_counts.get((surah, ayah), 1)
            for w in range(w_end, w_start - 1, -1):
                word_phonemes = canonical.get(f"{surah}:{ayah}:{w}", [])
                canonical_tail = word_phonemes + canonical_tail
                if len(canonical_tail) >= n:
                    break
            if len(canonical_tail) >= n:
                break

    if len(canonical_tail) < n:
        return None

    return canonical_tail[-n:], asr_tokens[-n:]


def tail_phoneme_mismatch(phonemes_asr: str, matched_ref: str,
                          canonical: dict[str, list[str]], k: int) -> bool:
    """Detect segment cutting off early: canonical 2nd-to-last phoneme is a long vowel
    and ASR ends on that vowel (last canonical phoneme missing).
    """
    tails = get_phoneme_tails(phonemes_asr, matched_ref, canonical, 2)
    if tails is None:
        return False
    canon_tail, asr_tail_2 = tails
    asr_last = phonemes_asr.split()[-1]
    canon_last = canon_tail[1]

    # Case 1: canonical ends with long vowel + consonant, ASR ends on the vowel
    # Exception: long vowel + glottal stop is normal -- ASR routinely drops it
    if (canon_tail[0] in BOUNDARY_VOWELS
        and canon_last != '\u0294'
        and phonemes_match(canon_tail[0], asr_last, get_phoneme_sub_pairs())):
        return True

    # Case 2: canonical last phoneme is Q (qalqala marker) but ASR doesn't end with Q
    if canon_last == 'Q' and asr_last != 'Q':
        return True

    return False
