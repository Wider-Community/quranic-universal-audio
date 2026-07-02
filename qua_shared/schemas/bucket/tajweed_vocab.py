"""Tajweed rule-key vocabulary — the codegen source for the FE rule registry.

These mirror the phonemizer's canonical ``TajweedRule`` (the producer owns the
domain vocabulary). The dependency arrows point away from each other
(phonemizer ← sdk ← app) and the phonemizer must stay off the inspector runtime
import path, so qua_shared cannot import it at module load — instead this enum is
the codegen-facing mirror and ``tests/test_cell_vocab_parity.py`` asserts it stays
byte-equal to the phonemizer's values (so it can never drift).

Referenced by ``TsShardCell`` (``bucket/ts_shard.py``) so the FE-types codegen
emits ``TajweedRule`` as a TS string union, against which the FE rule registry
(``tabs/timestamps/utils/tajweed-rules.ts``) types its keys — a phonemizer rename
or addition then surfaces as a TS compile error, not a silently-dropped underline.

This is the producer vocabulary only; a handful of FE/SDK-synthesized tags
(``izhar_*``, ``iqlab_silent_noon``, ``iltiqaa``/``iltiqaa_kasra``, ``madd_iwad``,
``allah_dagger_alef``) are NOT enum members and are owned FE-side.
"""

from __future__ import annotations

from enum import Enum


class TajweedRule(str, Enum):
    # Ghunnah — nasalization
    NOON_GHUNNAH = "noon_ghunnah"
    MEEM_GHUNNAH = "meem_ghunnah"
    IKHFAA_NOON = "ikhfaa_noon"
    IKHFAA_TANWEEN = "ikhfaa_tanween"
    IKHFAA_SHAFAWI = "ikhfaa_shafawi"
    IQLAB_NOON = "iqlab_noon"
    IQLAB_TANWEEN = "iqlab_tanween"
    IDGHAM_GHUNNAH_NOON = "idgham_ghunnah_noon"
    IDGHAM_GHUNNAH_TANWEEN = "idgham_ghunnah_tanween"
    IDGHAM_SHAFAWI = "idgham_shafawi"

    # Silent — letter produces no sound
    VOWEL_SILENT = "vowel_silent"
    HAMZA_WASL_SILENT = "hamza_wasl_silent"
    LAM_SHAMSIYAH = "lam_shamsiyah"
    IDGHAM_BILA_GHUNNAH_NOON = "idgham_bila_ghunnah_noon"
    IDGHAM_BILA_GHUNNAH_TANWEEN = "idgham_bila_ghunnah_tanween"
    IDGHAM_MUTAMATHILAYN = "idgham_mutamathilayn"
    IDGHAM_MUTAQARIBAYN = "idgham_mutaqaribayn"
    IDGHAM_MUTAJANISAYN_KAMIL = "idgham_mutajanisayn_kamil"
    SILENT_ILTIQAA_SAKINAYN = "silent_iltiqaa_sakinayn"

    # Tafkheem — heaviness
    TAFKHEEM = "tafkheem"

    # Qalqala
    QALQALA_SUGHRA = "qalqala_sughra"
    QALQALA_KUBRA = "qalqala_kubra"

    # Hamza wasl vowel (when starting)
    HAMZA_WASL_FATHA = "hamza_wasl_fatha"
    HAMZA_WASL_KASRA = "hamza_wasl_kasra"
    HAMZA_WASL_DAMMA = "hamza_wasl_damma"

    # Iltiqaa (meeting of two sukuns)
    ILTIQAA_SAKINAYN_TANWEEN = "iltiqaa_sakinayn_tanween"
    IDGHAM_MUTAJANISAYN_NAQIS = "idgham_mutajanisayn_naqis"

    # Madd — vowel lengthening
    MADD_TABII = "madd_tabii"
    MADD_WAJIB_MUTTASIL = "madd_wajib_muttasil"
    MADD_JAIZ_MUNFASIL = "madd_jaiz_munfasil"
    MADD_LAZIM = "madd_lazim"
    MADD_ARID_LISSUKUN = "madd_arid_lissukun"
    MADD_LEEN = "madd_leen"

    __str__ = str.__str__  # str()/f-string yield the value, not "TajweedRule.NOON_GHUNNAH"
