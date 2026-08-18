"""What the bounded-equivalence gate is allowed to find.

Every table here is a claim about how the shard's tajweed vocabulary moved
between the legacy producer and the current one. The gate (``ts_bounded_
equivalence.py``) sorts each difference against these and fails on anything
they do not name, so a legitimate producer change edits this file in the same
commit that makes it -- and says, in the commit, which count moved and why.
"""

from __future__ import annotations

#: Legacy cell tag -> the tag the shard carries now, one for one. Both legacy
#: silence names land on one because the producer draws no distinction between
#: an unclassified silence and a vowel letter that says nothing.
RENAMED_TAGS = {
    "hamza_wasl_silent": "hamza_wasl_elision",
    "silent_iltiqaa_sakinayn": "hamza_wasl_elision",
    "lam_shamsiyah": "lam_shamsiyyah",
    "madd_arid_lissukun": "madd_arid_lil_sukun",
    "vowel_silent": "orthographic_silence",
    "silent_unclassified": "orthographic_silence",
    "iltiqaa_sakinayn_tanween": "madd_iwad",
    "allah_dagger_alef": "madd_tabii",
}

#: Legacy tags that split a noon rule from its tanween twin, and the louder
#: qalqala the shard never named apart. Each folds onto one cell tag. The
#: split survives in the cross-word bridge vocabulary, which is not this.
COLLAPSED_TAGS = {
    "ikhfaa_noon": "ikhfaa",
    "ikhfaa_tanween": "ikhfaa",
    "iqlab_noon": "iqlab",
    "iqlab_tanween": "iqlab",
    "idgham_ghunnah_noon": "idgham_bi_ghunnah",
    "idgham_ghunnah_tanween": "idgham_bi_ghunnah",
    "idgham_bila_ghunnah_noon": "idgham_bila_ghunnah",
    "idgham_bila_ghunnah_tanween": "idgham_bila_ghunnah",
    "noon_ghunnah": "ghunnah",
    "meem_ghunnah": "ghunnah",
    "qalqala_akbar": "qalqala_kubra",
}

#: Legacy named the prosthetic hamza; the shard names the vowel it takes, so
#: one legacy tag answers to any of three.
LEGACY_WASL_VOWEL = "hamza_wasl_vowel"
WASL_VOWEL_TAGS = frozenset({"hamza_wasl_fatha", "hamza_wasl_kasra", "hamza_wasl_damma"})

#: Tags the producer now emits that legacy had no name for.
NEW_RULE_TAGS = frozenset(
    {
        "izhar",
        "izhar_shafawi",
        "imala",
        "tashil",
        "ishmam",
        "ibdal_hamza",
        "pausal_sukun",
        "pausal_alif",
        "taa_marbuta_pausal",
        "orthographic_silence",
        "idgham_mutajanisayn_naqis",
    }
)

#: A tag the shard now carries beside one it already names, and the tag that
#: carries it, mirroring ``qua_sdk.integrations.vocabulary.IMPLIED``. The alif
#: a stop gives a tanween fath is held for two counts, which is the natural
#: madd; legacy named that nowhere on the cell.
IMPLIED_TAGS = {"madd_tabii": "madd_iwad"}

#: Producer rules a cell never carries, mirroring ``qua_sdk.integrations.
#: vocabulary.DROPPED`` so the classifier stays importable without the SDK.
#: ``test_bounded_equivalence`` asserts the mirror against the live one.
DROPPED_RULES = frozenset({"lam_qamariyyah", "tarqeeq", "fakk_idgham"})

#: Legacy names for a letter that says nothing. A merger or a carrier letter
#: moving its silence takes these with it.
LEGACY_SILENCE_TAGS = frozenset(
    {"vowel_silent", "silent_unclassified", "hamza_wasl_silent", "silent_iltiqaa_sakinayn"}
)

#: The one merger family whose sound legacy hosted on the word before.
LABIAL_MERGER = "idgham_shafawi"

#: The carrier of a dagger alif in ٱلصَّلَوٰة / ٱلزَّكَوٰة / ٱلْحَيَوٰة.
CARRIER_WAW = "و"

#: A stop on a qalqala letter legacy left unnamed.
FIX_QALQALA_AT_STOP = "qalqala_kubra"

#: The cell tags a cross-word merger leaves on the word it merged into. Across
#: a waṣl join its partner is in the next segment, where this scan cannot look,
#: so the join itself is what says the re-attribution is the reason.
MERGER_CELL_TAGS = frozenset(
    {
        "idgham_bi_ghunnah",
        "idgham_bila_ghunnah",
        "idgham_shafawi",
        "idgham_mutamathilayn",
        "idgham_mutaqaribayn",
        "idgham_mutajanisayn_kamil",
    }
)

#: A hidden noon leaves a hum, and before a letter of istilaa that hum is
#: heavy. Legacy coloured it and named the hiding twice instead of naming the
#: weight, so a word carrying both is the correction and not a new rule.
FIX_HEAVY_HUM = ("tafkheem", "ikhfaa")

#: Corrections named one at a time: the ref, what moved there, and why the new
#: reading is the right one.
FIX_REFS = {
    "89:4:3": {
        "token": "yasri's raa is light, not heavy",
        "tafkheem": "yasri's raa is light, not heavy",
    },
    # The riwayah disagrees with itself here and Hafs reads the seen; the
    # shards were written under the saad. `docs/hafs/variants.md` names the
    # variant `seen_sad_yabsut` / `seen_sad_bastah`, both defaulting to seen.
    "2:245:14": {"token": "yabsut and bastah are read with the seen"},
    "7:69:22": {"token": "yabsut and bastah are read with the seen"},
    # Started on, `ٱئْتِ` is read `إِىٓتِ`: the prosthetic hamza takes a kasra and
    # the quiescent hamza after it becomes the madd that kasra opens. One sound
    # where legacy read two, so the stamper folds the two stored phones into one
    # over their union and the word's stored array is one shorter.
    "10:15:11": {"bucket": "starting on `ٱئْتِ` reads its second hamza as a madd"},
}

#: Differences accepted as they are, each with the reason it is not a bug.
RESIDUE_REFS = {
    "11:42:15": "legacy also named a ghunnah the doubled meem already carries",
}

#: What each measured corpus declares, keyed by the shape that identifies it.
#: A run over a shape not here reports its counts and asserts nothing about
#: them. Two reciters are measured because one alone cannot tell a producer
#: change from a segmentation one: the same rule fires in a different waqf
#: context when the runs are cut elsewhere, so a count that moves in one corpus
#: and not the other is the segmentation talking.
#:
#: `families` maps a family to (direction its count may move, differences here).
#: `exact` is a mechanical map over a frozen corpus: it has one right answer,
#: and a producer change that moves it says so in the same commit. `at_most`
#: may only fall, as a correction lands upstream or a residue is resolved and
#: the difference stops existing.
#:
#: The four `cell_` families are the cell row itself: which letter each sound is
#: drawn under, which letters grey, how the share groups partition the word, and
#: what each cell shows. A frozen shard's row was written to the older contract,
#: under which the carrier came before the haraka it lengthens, a long vowel was
#: claimed by one letter rather than both, and an added cell wrote no letter at
#: all. So these count a whole contract, not one rule each, and they are here to
#: hold that count still: the producer may not move a single cell without saying
#: which family moved and why. A regression in greying moves `cell_greyed` alone
#: and nothing else, which is what makes them worth counting apart.
#:
#: `members` is the two families declared one row at a time. Each row is a
#: difference that was looked at and accepted; none may grow without being
#: looked at again.
#:
#: `cells_dropped` is words the stamper writes no cells for. The stamper
#: reconciles the two letter rows rather than demanding they match, so this is
#: a word the projection and the aligner spell differently, or one in a run
#: whose stored phone count a correction moved -- the run goes with the word.
#:
#: `count_fixed` is words whose stored phone count a listed correction moved.
#: Each is named by ref in `FIX_REFS` under `count`, which is what permits it;
#: this only bounds how many there may be.
DECLARED = {
    # mishary_rashid_al_afasy_mp3quran
    (114, 80200): {
        "families": {
            "rename": ("exact", 33566),
            "collapse": ("exact", 15568),
            "new_rule": ("exact", 17622),
            "dropped": ("exact", 8573),
            "merger_attribution": ("exact", 8093),
            "fix": ("at_most", 557),
            "residue": ("at_most", 236),
            "cell_owner": ("exact", 44228),
            "cell_greyed": ("exact", 939),
            "cell_share": ("exact", 15637),
            "cell_cut": ("exact", 24534),
        },
        "members": {
            "the waw carrying a dagger alif is sounded": ("at_most", 184),
            "a carrier letter legacy sounded is greyed": ("at_most", 42),
            "a carrier letter legacy greyed is sounded": ("at_most", 2),
            "a carrier letter's silence moved": ("at_most", 0),
            "legacy also named a ghunnah the doubled meem already carries": ("at_most", 1),
            "a stop on a qalqala letter legacy left unnamed": ("at_most", 3),
            "a stop keeps the vowel's own length": ("at_most", 1),
            "yasri's raa is light, not heavy": ("at_most", 1),
            "the hum a hidden noon leaves before istilaa is heavy": ("at_most", 527),
            "yabsut and bastah are read with the seen": ("at_most", 2),
            "starting on `ٱئْتِ` reads its second hamza as a madd": ("at_most", 0),
        },
        "cells_dropped": ("exact", 0),
        "count_fixed": ("at_most", 0),
    },
    # nasser_al_qatami_mp3quran
    (114, 84998): {
        "families": {
            "rename": ("exact", 35364),
            "collapse": ("exact", 16248),
            "new_rule": ("exact", 19268),
            "dropped": ("exact", 8969),
            "merger_attribution": ("exact", 8301),
            "fix": ("at_most", 569),
            "residue": ("at_most", 257),
            "cell_owner": ("exact", 46555),
            "cell_greyed": ("exact", 1079),
            "cell_share": ("exact", 16661),
            "cell_cut": ("exact", 26199),
        },
        "members": {
            "the waw carrying a dagger alif is sounded": ("at_most", 184),
            "a carrier letter legacy sounded is greyed": ("at_most", 42),
            "a carrier letter legacy greyed is sounded": ("at_most", 2),
            "a carrier letter's silence moved": ("at_most", 0),
            "legacy also named a ghunnah the doubled meem already carries": ("at_most", 1),
            "a stop on a qalqala letter legacy left unnamed": ("at_most", 3),
            "a stop keeps the vowel's own length": ("at_most", 1),
            "yasri's raa is light, not heavy": ("at_most", 1),
            "the hum a hidden noon leaves before istilaa is heavy": ("at_most", 527),
            "yabsut and bastah are read with the seen": ("at_most", 2),
            "starting on `ٱئْتِ` reads its second hamza as a madd": ("at_most", 1),
        },
        # The stamper folds the one word whose stored phones the reading says
        # are one sound, so no word goes without cells in either corpus.
        "cells_dropped": ("exact", 0),
        "count_fixed": ("at_most", 0),
    },
}


def declared_for(shards: int, words: int) -> dict | None:
    """What a run of this shape is held to, or None if nothing measured it."""
    return DECLARED.get((shards, words))


def targets_of_legacy(tag: str) -> frozenset[str]:
    """Every new tag a legacy tag may have become."""
    if tag == LEGACY_WASL_VOWEL:
        return WASL_VOWEL_TAGS
    for table in (RENAMED_TAGS, COLLAPSED_TAGS):
        if tag in table:
            return frozenset({table[tag]})
    return frozenset({tag})


def family_of_legacy(tag: str) -> str:
    """Which vocabulary family a legacy tag's move belongs to."""
    return "collapse" if tag in COLLAPSED_TAGS else "rename"
