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
_PHARYNGEAL = "ˤ"  # ˤ — superscript glottal stop suffix on emphatic consonants


def _is_merger_phoneme(p: str) -> bool:
    """A phoneme that bears a cross-word-merger signature.

    Two patterns cover the 8 in-scope rules:

    - **Ghunnah-family** (``idgham_ghunnah_*``, ``idgham_shafawi``) — the
      phoneme carries a combining tilde or its precomposed Latin form
      ``ñ`` (``m̃``, ``ñ``, ``j̃``, ``w̃``).
    - **Gemination-family** (``idgham_bila_ghunnah_*``,
      ``idgham_mutamathilayn``, ``idgham_mutaqaribayn``,
      ``idgham_mutajanisayn_kamil``) — the phoneme is a doubled consonant
      (``ll``, ``mm``, ``bb``, ``tt`` …), optionally pharyngealised
      (``rˤrˤ``, ``sˤsˤ``, ``tˤtˤ``, ``ðˤðˤ`` …). The pharyngeal modifier
      ``ˤ`` (U+02E4) is dropped before comparing so the doubled-prefix
      check fires on both forms.
    """
    if not p:
        return False
    if _GHUNNAH_MARK in p or "ñ" in p:
        return True
    base = p.replace(_PHARYNGEAL, "")
    if len(base) >= 2 and base[0] == base[1]:
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

        # Find the trigger entry: the LAST entry in prev_w that carries an
        # in-scope source rule whose target letter actually lives on
        # curr_w[0]. For noon-sukun and meem-sukun cases this is literally
        # the last letter (``ن``, ``م``). For tanween cases the trigger sits
        # on the consonant CARRYING the tanween diacritic — the last entries
        # are silent alef/alef-maksura/ى that hang off the tanween
        # (``هُدًى``: trigger=``د``, last=``ى`` silent). The cross-word check
        # against curr_w's first entry's ``target_rules`` rejects word-internal
        # firings of the same rule (``أَرَدتُّمْ``: ``د → ت`` mutajanisayn fires
        # within the word; no bridge into the next word).
        curr_first_targets = {t.rule for t in curr_w.letter_mappings[0].tajweed_rules}
        trigger = None
        trigger_rule = None
        for e in reversed(prev_w.letter_mappings):
            in_scope = {t.rule for t in e.tajweed_rules if t.is_source} & BRIDGE_RULES
            cross_word = in_scope & curr_first_targets
            if cross_word:
                trigger = e
                trigger_rule = sorted(cross_word, key=lambda r: r.value)[0]
                break
        if trigger is None or trigger_rule is None:
            continue

        # Side: where did the phonemizer put the merged result? Match by
        # signature on the TRIGGER letter's LAST phoneme — when the merger
        # lives on prev (shafawi: ``لَهُم → … m̃``), it surfaces as the trigger
        # letter's terminal phoneme. Checking ANY phoneme on the trigger
        # would over-fire on tanween carriers whose own shaddah produces a
        # word-internal geminate (``قَرَارࣱ → aˤ, rˤrˤ, u``: the ``rˤrˤ`` is the
        # shaddah on the carrier, NOT the cross-word merger; the merger
        # actually sits on the next word's first letter).
        side = (
            "prev"
            if trigger.phonemes and _is_merger_phoneme(trigger.phonemes[-1])
            else "curr"
        )

        before_word_idx = _resolve_word_idx(curr_w.location)
        if before_word_idx == 0:
            # Malformed location (muqattaat or unexpected form) — skip.
            continue

        out.append(
            BridgeInfo(before_word_idx=before_word_idx, rule=trigger_rule.value, side=side)
        )

    return tuple(out)
