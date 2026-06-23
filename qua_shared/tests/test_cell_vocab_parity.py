"""Parity guard: the qua_shared cell vocab mirrors the phonemizer's, and the
schema coerces a v6 cell row's role/status to the enums.

qua_shared cannot import the phonemizer at module load (it must stay off the
inspector runtime import path), so ``CellRole`` / ``CellStatus`` are a mirror;
this asserts they never drift from the phonemizer's canonical values.
"""

from __future__ import annotations

import pytest

from qua_shared.schemas.bucket.ts_shard import TsShardWord
from qua_shared.schemas.config.cell_vocab import CellRole, CellStatus


def _phonemizer_vocab():
    try:
        from quranic_phonemizer import CellRole as PR
        from quranic_phonemizer import CellStatus as PS
    except ImportError:
        return None
    return PR, PS


@pytest.mark.skipif(_phonemizer_vocab() is None, reason="phonemizer not installed")
def test_role_status_mirror_phonemizer():
    pr, ps = _phonemizer_vocab()
    assert {r.value for r in CellRole} == {r.value for r in pr}
    assert {s.value for s in CellStatus} == {s.value for s in ps}


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
    cells = w.root[5]
    assert cells[0][1] is CellRole.BASE and cells[0][2] is CellStatus.PRESENT
    assert cells[1][1] is CellRole.HARAKA
    # round-trips back to bare strings on the wire (byte pass-through unchanged).
    assert w.model_dump(mode="json")[5][0][1] == "base"
