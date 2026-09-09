"""Per-edition projections of the Hafs classifier tables.

``inspector/constants.py`` holds three hand-curated Hafs tables — the muqattaat
opening verses, an allow-list of *refs* a reciter may recite alone, and a
separate allow-list of standalone *skeletons* — which the segment classifier
consults independently to decide whether a one-word segment is a legitimate
standalone recitation or a fragment. A fourth table, the one-word verses, is
derived from ``surah_info.json``.

Under another riwayah those coordinates move. Warsh renumbers 50 of the 114
surahs, so a Hafs ``(surah, ayah)`` key is not merely a different verse there —
it can be out of range. The tables are therefore **projected**, never reused:
each Hafs entry goes through ``qua_domain``'s Hafs->target word projection and
comes back as the target edition's own coordinates.

Two properties make this safe:

* **Hafs is the identity.** ``muqattaat_words("hafs")`` and friends return the
  frozen constants verbatim, with no ``qua_domain`` call — so the 37 published
  Hafs reciters cannot shift, and the package stays optional. A test asserts the
  derived Hafs table equals the constant.
* **Word granularity, not verse.** Warsh's ``2:1`` is an eight-word verse whose
  *first* word is the muqattaat; a verse-level table would flag its other seven
  words as standalone. Every table below is keyed to the word.

Sizes differ from Hafs and that is correct, not a bug:

| table                 | hafs | shuba | warsh / qalun |
|-----------------------|------|-------|---------------|
| ``muqattaat_words``   |   30 |    30 | 30 — Hafs 42:1:1 + 42:2:1 land in ONE Warsh verse as 42:1:1 + 42:1:2 |
| ``muqattaat_verses``  |   30 |    30 | **29** — the same merge, seen verse-wise |
| ``standalone_refs``   |   10 |    10 | 10, four renumbered |
| ``standalone_words``  |    8 |     8 | 8, one respelled |
| ``single_word_verses``|   28 |    28 | 3 |
"""

from __future__ import annotations

from constants import MUQATTAAT_VERSES, STANDALONE_REFS, STANDALONE_WORDS
from qua_shared.riwayat import DEFAULT_SDK_RIWAYAH
from services.reference import editions
from services.storage import cache
from utils.arabic_text import strip_quran_deco

WordRef = tuple[int, int, int]
VerseRef = tuple[int, int]

#: The disconnected letters always open their verse, so the Hafs word table is
#: the verse table at ``word == 1``. (The verses themselves are NOT all one word
#: — 13:1 runs on past the letters — which is why the two tables below are not
#: interchangeable.) Asserted against the projection in the Shu'bah gate.
_HAFS_MUQATTAAT_WORDS: frozenset[WordRef] = frozenset(
    (surah, ayah, 1) for surah, ayah in MUQATTAAT_VERSES
)


def _fmt(ref: WordRef) -> str:
    return f"{ref[0]}:{ref[1]}:{ref[2]}"


def _parse(ref: str) -> WordRef:
    surah, ayah, word = ref.split(":")
    return int(surah), int(ayah), int(word)


def _project_words(refs: frozenset[WordRef], riwayah: str) -> frozenset[WordRef]:
    """Map Hafs word refs onto ``riwayah``'s own coordinates.

    A Hafs word can project onto several target words (a split) or share a
    target with its neighbour (a join); both are kept, so a segment starting at
    any of the target words still classifies. A word with no counterpart in the
    target edition (``target_absent``) simply drops out — there is nothing there
    to recite.
    """
    projection = editions.projection(riwayah)
    out: set[WordRef] = set()
    for ref in refs:
        projected = projection.project_range(_fmt(ref))
        for group in projected.groups:
            out.update(_parse(word.ref) for word in group.target_words)
    return frozenset(out)


def _tables(riwayah: str) -> dict:
    cached = cache.get_edition_tables(riwayah)
    if cached is not None:
        return cached
    if riwayah == DEFAULT_SDK_RIWAYAH:
        built = _hafs_tables()
    else:
        built = _projected_tables(riwayah)
    cache.set_edition_tables(riwayah, built)
    return built


def _hafs_tables() -> dict:
    """The frozen constants, verbatim — the identity case.

    Deliberately does not touch ``qua_domain``: Hafs display text comes from
    ``qpc_hafs.json``, whose glyph variant differs from the package's Hafs index
    in 44,481 words, and re-deriving the skeletons from the other variant would
    silently change what ``STANDALONE_WORDS`` matches.
    """
    from services.storage.data_loader import get_single_word_verses

    return {
        "muqattaat_words": _HAFS_MUQATTAAT_WORDS,
        "muqattaat_verses": frozenset(MUQATTAAT_VERSES),
        "standalone_refs": frozenset(STANDALONE_REFS),
        "standalone_words": frozenset(STANDALONE_WORDS),
        "single_word_verses": frozenset(get_single_word_verses()),
        "fatiha_last_ayah": 7,
    }


def _projected_standalone_words(riwayah: str) -> frozenset[str]:
    """The ``STANDALONE_WORDS`` skeletons, respelled in the target script.

    ``STANDALONE_WORDS`` is a *text* allow-list, unrelated to the ref allow-list
    in ``STANDALONE_REFS`` — the classifier consults them independently. So this
    is not a projection of those refs: it finds every Hafs word whose skeleton
    is in the set (633 occurrences of 8 skeletons), projects each, and takes the
    target spellings.

    Every occurrence is projected rather than one sample per skeleton, because
    nothing guarantees two occurrences of one Hafs word share a target spelling.
    Today exactly one of the eight moves — Warsh writes the standalone
    ``wa-bi-al-layl`` without the alif-wasla — and a Hafs skeleton would simply
    never match a Warsh segment.
    """
    from services.storage.data_loader import get_dk_words_flat

    projection = editions.projection(riwayah)
    out: set[str] = set()
    for ref, text in get_dk_words_flat().items():
        if strip_quran_deco(text) not in STANDALONE_WORDS:
            continue
        for group in projection.project_range(ref).groups:
            for word in group.target_words:
                skeleton = strip_quran_deco(word.text)
                if skeleton:
                    out.add(skeleton)
    return frozenset(out)


def _projected_tables(riwayah: str) -> dict:
    counts = editions.word_counts(riwayah)
    muqattaat = _project_words(_HAFS_MUQATTAAT_WORDS, riwayah)
    return {
        "muqattaat_words": muqattaat,
        "muqattaat_verses": frozenset((surah, ayah) for surah, ayah, _ in muqattaat),
        "standalone_refs": _project_words(frozenset(STANDALONE_REFS), riwayah),
        "standalone_words": _projected_standalone_words(riwayah),
        "single_word_verses": frozenset(key for key, n in counts.items() if n == 1),
        "fatiha_last_ayah": editions.surah(1, riwayah).ayah_count,
    }


def muqattaat_words(riwayah: str) -> frozenset[WordRef]:
    """``(surah, ayah, word)`` of every disconnected-letters opening.

    Word-keyed because an edition can put two openings in one verse: Warsh
    merges Hafs's 42:1 (``ha-mim``) and 42:2 (``ayn-sin-qaf``) into a single
    verse, so ``42:1:1`` and ``42:1:2`` are both muqattaat there.
    """
    return _tables(riwayah)["muqattaat_words"]


def muqattaat_verses(riwayah: str) -> frozenset[VerseRef]:
    """``(surah, ayah)`` of every verse that OPENS with disconnected letters.

    Distinct from :func:`muqattaat_words`, and not interchangeable with it: the
    boundary-adjustment rule exempts the whole verse, including words far past
    the letters (13:1 continues for another eight words). Narrowing that to the
    opening word would newly flag one-word segments in those verses across the
    37 published Hafs reciters.
    """
    return _tables(riwayah)["muqattaat_verses"]


def standalone_refs(riwayah: str) -> frozenset[WordRef]:
    """Word refs a reciter legitimately recites alone."""
    return _tables(riwayah)["standalone_refs"]


def standalone_words(riwayah: str) -> frozenset[str]:
    """Standalone-recitation skeletons, spelled in this edition's own script."""
    return _tables(riwayah)["standalone_words"]


def single_word_verses(riwayah: str) -> frozenset[VerseRef]:
    """``(surah, ayah)`` of every verse that is one word long in this edition."""
    return _tables(riwayah)["single_word_verses"]


def fatiha_last_ayah(riwayah: str) -> int:
    """Al-Fatiha's final verse number — where the Amin check looks."""
    return _tables(riwayah)["fatiha_last_ayah"]


def basmala_is_numbered(riwayah: str) -> bool:
    """True iff this edition counts the Fatiha Basmala as verse ``1:1``."""
    return editions.basmala_is_numbered(riwayah)
