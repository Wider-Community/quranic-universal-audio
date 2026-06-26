"""Parity guard: the qua_shared cell + tajweed vocab mirrors the phonemizer's, and
the schema coerces a v6 cell row's role/status to the enums.

qua_shared cannot import the phonemizer at module load (it must stay off the
inspector runtime import path), so ``CellRole`` / ``CellStatus`` / ``TajweedRule``
are mirrors. The literal-pin tests below run unconditionally (in inspector CI,
where the phonemizer is NOT installed) and freeze the canonical value sets; the
``skipif``-gated tests additionally confirm the live phonemizer agrees with that
pin — so neither end can drift unnoticed.
"""

from __future__ import annotations

from typing import cast

import pytest

from qua_shared.schemas.bucket.cell_vocab import CellRole, CellStatus
from qua_shared.schemas.bucket.tajweed_vocab import TajweedRule
from qua_shared.schemas.bucket.ts_shard import TsShardWord

# The canonical value sets, pinned as literals so a drift fails even where the
# phonemizer is absent. Keep in lockstep with the phonemizer enums (the skipif
# tests below assert the live producer matches these exact sets).
_ROLE_VALUES = {"base", "haraka", "tanween", "madd"}
_STATUS_VALUES = {"present", "inserted", "dropped", "replaced", "shortened"}
_TAJWEED_VALUES = {
    "noon_ghunnah",
    "meem_ghunnah",
    "ikhfaa_noon",
    "ikhfaa_tanween",
    "ikhfaa_shafawi",
    "iqlab_noon",
    "iqlab_tanween",
    "idgham_ghunnah_noon",
    "idgham_ghunnah_tanween",
    "idgham_shafawi",
    "vowel_silent",
    "hamza_wasl_silent",
    "lam_shamsiyah",
    "idgham_bila_ghunnah_noon",
    "idgham_bila_ghunnah_tanween",
    "idgham_mutamathilayn",
    "idgham_mutaqaribayn",
    "idgham_mutajanisayn_kamil",
    "silent_iltiqaa_sakinayn",
    "tafkheem",
    "qalqala_sughra",
    "qalqala_kubra",
    "hamza_wasl_fatha",
    "hamza_wasl_kasra",
    "hamza_wasl_damma",
    "iltiqaa_sakinayn_tanween",
    "idgham_mutajanisayn_naqis",
    "madd_tabii",
    "madd_wajib_muttasil",
    "madd_jaiz_munfasil",
    "madd_lazim",
    "madd_arid_lissukun",
    "madd_leen",
}


def _phonemizer_vocab():
    try:
        from quranic_phonemizer import CellRole as PR
        from quranic_phonemizer import CellStatus as PS
        from quranic_phonemizer import TajweedRule as PT
    except ImportError:
        return None
    return PR, PS, PT


def test_vocab_value_sets_pinned():
    """The mirror value sets are frozen — runs even without the phonemizer."""
    assert {r.value for r in CellRole} == _ROLE_VALUES
    assert {s.value for s in CellStatus} == _STATUS_VALUES
    assert {r.value for r in TajweedRule} == _TAJWEED_VALUES


@pytest.mark.skipif(_phonemizer_vocab() is None, reason="phonemizer not installed")
def test_role_status_mirror_phonemizer():
    vocab = _phonemizer_vocab()
    assert vocab is not None
    pr, ps, _ = vocab
    assert {r.value for r in CellRole} == {r.value for r in pr} == _ROLE_VALUES
    assert {s.value for s in CellStatus} == {s.value for s in ps} == _STATUS_VALUES


@pytest.mark.skipif(_phonemizer_vocab() is None, reason="phonemizer not installed")
def test_tajweed_rule_mirror_phonemizer():
    vocab = _phonemizer_vocab()
    assert vocab is not None
    _, _, pt = vocab
    assert {r.value for r in TajweedRule} == {r.value for r in pt} == _TAJWEED_VALUES


def test_schema_coerces_v6_cell_row():
    v6 = [
        1,
        10,
        200,
        [["ب", 10, 90, False]],
        [["b", 10, 50], ["i", 50, 90]],
        [
            ["ب", "base", "present", [0], 0, None, None],
            ["ِ", "haraka", "present", [1], 0, None, None],
        ],
    ]
    w = TsShardWord.model_validate(v6)
    # v6 validates to the 6-tuple variant (cells present); narrow for the checker.
    cells = cast(tuple[int, int, int, list, list, list], w.root)[5]
    assert cells[0][1] is CellRole.BASE and cells[0][2] is CellStatus.PRESENT
    assert cells[1][1] is CellRole.HARAKA
    # round-trips back to bare strings on the wire (byte pass-through unchanged).
    assert w.model_dump(mode="json")[5][0][1] == "base"
