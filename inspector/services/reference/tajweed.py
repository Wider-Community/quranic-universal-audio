"""Cross-word tajweed bridges for the Timestamps Analysis tab.

The TS Analysis view renders a gold-bordered tile between two word blocks when
a cross-word tajweed rule fires (idgham ghunnah, shafawi, bila ghunnah,
mutamathilayn, mutaqaribayn, mutajanisayn kamil). This module computes those
bridges from :mod:`quranic_phonemizer` so the FE doesn't have to reimplement
tajweed detection in TypeScript.

Why backend, not precompute:
- Stops are reciter-specific (waqf varies). The phonemizer needs ``stop_refs``
  to suppress cross-word rules at a real pause, so a static precomputed map
  wouldn't work.

Why cached:
- ``(verse_ref, stop_refs)`` is a pure, hashable, stable input — ``lru_cache``
  is a one-line win. Phonemizer init at module import time pays its ~250 ms
  one-shot off the request path.

The bridge phoneme is always a single phoneme — whichever side of the boundary
carries the rule's merged result in the phonemizer's per-letter output. We
don't hardcode per-rule conventions: the decision falls out of inspecting
``LetterMapping.phonemes`` on both adjacent letters.
"""

from __future__ import annotations

import functools
import logging
import time

from quranic_phonemizer import Phonemizer, TajweedRule

from scripts.lib.schemas.tajweed import BridgeInfo

log = logging.getLogger(__name__)

# The 8 cross-word rules a bridge tile should surface. Within-word firings of
# these same rules (e.g. ``بِسْمِ ٱللَّهِ``'s within-word mutamathilayn) are NOT
# bridges — they're already adjacent in the same block.
BRIDGE_RULES: frozenset[TajweedRule] = frozenset(
    {
        TajweedRule.IDGHAM_GHUNNAH_NOON,
        TajweedRule.IDGHAM_GHUNNAH_TANWEEN,
        TajweedRule.IDGHAM_SHAFAWI,
        TajweedRule.IDGHAM_BILA_GHUNNAH_NOON,
        TajweedRule.IDGHAM_BILA_GHUNNAH_TANWEEN,
        TajweedRule.IDGHAM_MUTAMATHILAYN,
        TajweedRule.IDGHAM_MUTAQARIBAYN,
        TajweedRule.IDGHAM_MUTAJANISAYN_KAMIL,
    }
)


_GHUNNAH_MARK = "̃"  # combining tilde used on nasalised idgham phonemes


def _is_merger_phoneme(p: str) -> bool:
    """A phoneme that bears a cross-word-merger signature.

    Two patterns cover the 8 in-scope rules:

    - **Ghunnah-family** (``idgham_ghunnah_*``, ``idgham_shafawi``) — the
      phoneme carries a combining tilde or its precomposed Latin form
      ``ñ`` (``m̃``, ``ñ``, ``j̃``, ``w̃``).
    - **Gemination-family** (``idgham_bila_ghunnah_*``,
      ``idgham_mutamathilayn``, ``idgham_mutaqaribayn``,
      ``idgham_mutajanisayn_kamil``) — the phoneme starts with a doubled
      consonant (``ll``, ``rˤrˤ``, ``mm``, ``nn``, ``bb``, ``tt``…).
    """
    if not p:
        return False
    if _GHUNNAH_MARK in p or "ñ" in p:
        return True
    # Doubled-consonant prefix — handles single-codepoint repeats and the
    # ``rˤrˤ``/``ðˤðˤ`` pair (pharyngealised repeat).
    if len(p) >= 2 and p[0] == p[1]:
        return True
    return False


_phonemizer: Phonemizer | None = None


def get_phonemizer() -> Phonemizer:
    """Return the process-wide :class:`Phonemizer` singleton (lazy-init).

    First call pays the ~250 ms package-db load. ``init_phonemizer()`` can be
    invoked from app boot to move that cost off the first user request.
    """
    global _phonemizer
    if _phonemizer is None:
        t0 = time.perf_counter()
        _phonemizer = Phonemizer()
        log.info(
            "quranic_phonemizer initialised in %.0f ms", (time.perf_counter() - t0) * 1000
        )
    return _phonemizer


def init_phonemizer() -> None:
    """Eagerly init at app boot so the first /api/ts/tajweed call is warm."""
    get_phonemizer()


def _resolve_word_idx(location: str) -> int:
    """``surah:ayah:word`` -> ``word`` (1-based). Muqattaat spell-out forms
    carry a 4th segment (``s:a:w:n``); we keep just the canonical word index.

    Verses without a word segment (shouldn't happen for ``tajweed_mappings``)
    return 0 — the caller filters such bridges defensively.
    """
    parts = location.split(":")
    if len(parts) < 3:
        return 0
    try:
        return int(parts[2])
    except ValueError:
        return 0


@functools.lru_cache(maxsize=4096)
def bridges_for_verse(
    verse_ref: str, stop_refs: tuple[str, ...] = ()
) -> tuple[BridgeInfo, ...]:
    """Compute cross-word tajweed bridges for ``verse_ref`` under ``stop_refs``.

    Returns an immutable tuple so the lru_cache entry is safely shared between
    concurrent requests. The route handler converts to a list for JSON.

    For each consecutive word pair (i, i+1) in the phonemizer's word list, we
    check whether the LAST letter of word i has a ``source_rule`` in
    :data:`BRIDGE_RULES`. If so, the bridge phoneme is whichever adjacent
    letter holds the rule's *merged* result — detected by signature:

    - if any phoneme on the source letter (word i's last) carries a merger
      signature — combining tilde ``̃`` (ghunnah ``m̃ ñ j̃ w̃``) or
      doubled-consonant gemination (``ll mm rˤrˤ``…) — the merger lives at
      prev's tail -> ``side="prev"`` (idgham shafawi: ``لَهُم → … m̃``).
    - otherwise the source went silent (or kept only its base vowel after
      the cross-word transformation) and the merger sits at the target
      letter's head -> ``side="curr"`` (idgham ghunnah noon ``مَن → silent``,
      ``يَقُولُ → j̃ …``; idgham ghunnah tanween where the carrier letter
      keeps its base ``l i`` while the tanween-noon migrates to next word).

    ``before_word_idx`` is 1-based and matches the FE's word-index convention
    (shard word arrays + ``TsWord.location``).
    """
    pm = get_phonemizer()
    result = pm.phonemize(ref=verse_ref, stop_refs=list(stop_refs) if stop_refs else None)
    mapping = result.letter_phoneme_mappings().mapping

    out: list[BridgeInfo] = []
    words = mapping.words
    for i in range(len(words) - 1):
        prev_w, curr_w = words[i], words[i + 1]
        if not prev_w.letter_mappings or not curr_w.letter_mappings:
            continue
        prev_last = prev_w.letter_mappings[-1]
        src_rules = {t.rule for t in prev_last.tajweed_rules if t.is_source}
        in_scope = src_rules & BRIDGE_RULES
        if not in_scope:
            continue
        # If multiple in-scope rules fire on the same letter, pick deterministically.
        rule = sorted(in_scope, key=lambda r: r.value)[0]

        # Side: where did the phonemizer put the merged result? Match by
        # signature on the SOURCE letter — if any of its phonemes bears a
        # ghunnah-tilde or gemination prefix, the merger lives at prev's tail
        # (shafawi). Otherwise the source either went silent or kept only its
        # base vowel/consonant (tanween-carrier case), and the merger sits at
        # the target letter's head. Reading the phonemizer's own output this
        # way avoids hardcoding a per-rule prev/curr table.
        side = "prev" if any(_is_merger_phoneme(p) for p in prev_last.phonemes) else "curr"

        before_word_idx = _resolve_word_idx(curr_w.location)
        if before_word_idx == 0:
            # Malformed location (muqattaat or unexpected form) — skip.
            continue

        out.append(BridgeInfo(before_word_idx=before_word_idx, rule=rule.value, side=side))

    return tuple(out)
