"""Phonemizer singleton and canonical phoneme cache.

Gracefully degrades when the ``quranic_phonemizer`` package is not installed.
"""

import pickle
from pathlib import Path

from config import CACHE_DIR
from services import cache

# Import phonemizer (optional)
try:
    from quranic_phonemizer import Phonemizer
    _HAS_PHONEMIZER = True
except Exception:
    _HAS_PHONEMIZER = False

_phonemizer = None


def has_phonemizer() -> bool:
    """Return whether the phonemizer package is available."""
    return _HAS_PHONEMIZER


def get_phonemizer():
    """Return the Phonemizer singleton, creating it on first call.

    Raises ``RuntimeError`` if the package is not installed.
    """
    global _phonemizer
    if _phonemizer is None:
        if not _HAS_PHONEMIZER:
            raise RuntimeError("Phonemizer not available")
        _phonemizer = Phonemizer()
    return _phonemizer


def get_canonical_phonemes(reciter: str) -> dict[str, list[str]] | None:
    """Load or build canonical phoneme cache for a reciter.

    Returns dict mapping word location key (e.g. ``"1:1:4"``) to phoneme list,
    or ``None`` if phonemizer is unavailable.
    """
    cached = cache.get_canonical_phonemes_cache(reciter)
    if cached is not None:
        return cached

    cache_path = CACHE_DIR / reciter / "canonical_phonemes.pkl"

    # Try loading from disk
    if cache_path.exists():
        with open(cache_path, "rb") as f:
            data = pickle.load(f)
        cache.set_canonical_phonemes_cache(reciter, data)
        return data

    # Build from scratch -- need phonemizer and loaded segments
    if not _HAS_PHONEMIZER:
        return None

    from services.data_loader import load_detailed
    entries = load_detailed(reciter)
    if not entries:
        return None

    # Collect all segment-end word refs as stop points
    stop_refs = set()
    for entry in entries:
        for seg in entry.get("segments", []):
            matched_ref = seg.get("matched_ref", "")
            if not matched_ref:
                continue
            parts = matched_ref.split("-")
            if len(parts) == 2:
                stop_refs.add(parts[1])

    # Phonemize entire Quran with reciter's stop points
    pm = get_phonemizer()
    result = pm.phonemize(ref="1-114", stop_refs=list(stop_refs))

    # Build word_ref -> phonemes mapping
    data = {}
    for word in result._words:
        data[word.location.location_key] = word.get_phonemes()

    # Persist to disk
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(data, f)

    cache.set_canonical_phonemes_cache(reciter, data)
    return data
