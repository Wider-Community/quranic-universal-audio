"""Tajweed rule-key vocabulary — the codegen source for the FE rule registry.

These mirror the shard tag vocabulary: the producer's rule ids
(``quranic_phonemizer.tajweed_rules``) mapped through
``qua_sdk.integrations.vocabulary`` (a few renames, three rules a cell never
carries, and ``wasl_start`` split into one tag per prosthetic vowel). The
dependency arrows point away from each other (phonemizer <- sdk <- app) and the
phonemizer must stay off the inspector runtime import path, so qua_shared cannot
import it at module load — instead this enum is the codegen-facing mirror and
``tests/test_cell_vocab_parity.py`` composes the live producer with that map and
asserts the two agree (so it can never drift).

Referenced by ``TsShardCell`` (``bucket/ts_shard.py``) so the FE-types codegen
emits ``TajweedRule`` as a TS string union, against which the FE rule registry
(``tabs/timestamps/utils/tajweed-rules.ts``) types its keys — a phonemizer rename
or addition then surfaces as a TS compile error, not a silently-dropped underline.

This is the CELL tag vocabulary. The cross-word bridge rule a phone row carries
at slot 5 is a separate namespace (``qua_sdk.integrations.projection.BRIDGE_RULES``)
which still splits each noon rule from its tanween twin, and is not mirrored here.
"""

from __future__ import annotations

from enum import Enum


class TajweedRule(str, Enum):
    # Noon and meem sakinah, tanween
    GHUNNAH = "ghunnah"
    IKHFAA = "ikhfaa"
    IKHFAA_SHAFAWI = "ikhfaa_shafawi"
    IQLAB = "iqlab"
    IZHAR = "izhar"
    IZHAR_SHAFAWI = "izhar_shafawi"
    IDGHAM_BI_GHUNNAH = "idgham_bi_ghunnah"
    IDGHAM_BILA_GHUNNAH = "idgham_bila_ghunnah"
    IDGHAM_SHAFAWI = "idgham_shafawi"
    IDGHAM_MUTAMATHILAYN = "idgham_mutamathilayn"
    IDGHAM_MUTAQARIBAYN = "idgham_mutaqaribayn"
    IDGHAM_MUTAJANISAYN_KAMIL = "idgham_mutajanisayn_kamil"
    IDGHAM_MUTAJANISAYN_NAQIS = "idgham_mutajanisayn_naqis"

    # Madd — vowel lengthening
    MADD_TABII = "madd_tabii"
    MADD_WAJIB_MUTTASIL = "madd_wajib_muttasil"
    MADD_JAIZ_MUNFASIL = "madd_jaiz_munfasil"
    MADD_LAZIM = "madd_lazim"
    MADD_ARID_LIL_SUKUN = "madd_arid_lil_sukun"
    MADD_LEEN = "madd_leen"
    MADD_IWAD = "madd_iwad"

    # Heaviness and qalqala
    TAFKHEEM = "tafkheem"
    QALQALA_SUGHRA = "qalqala_sughra"
    QALQALA_KUBRA = "qalqala_kubra"

    # Hamza
    HAMZA_WASL_FATHA = "hamza_wasl_fatha"
    HAMZA_WASL_KASRA = "hamza_wasl_kasra"
    HAMZA_WASL_DAMMA = "hamza_wasl_damma"
    HAMZA_WASL_ELISION = "hamza_wasl_elision"
    IBDAL_HAMZA = "ibdal_hamza"
    TASHIL = "tashil"

    # Other articulations
    IMALA = "imala"
    ISHMAM = "ishmam"
    LAM_SHAMSIYYAH = "lam_shamsiyyah"
    ILTIQAA = "iltiqaa"
    ILTIQAA_KASRA = "iltiqaa_kasra"
    ILTIQAA_FATHA = "iltiqaa_fatha"

    # What a stop does to the written word
    PAUSAL_SUKUN = "pausal_sukun"
    TAA_MARBUTA_PAUSAL = "taa_marbuta_pausal"
    ORTHOGRAPHIC_SILENCE = "orthographic_silence"

    __str__ = str.__str__  # str()/f-string yield the value, not "TajweedRule.GHUNNAH"
