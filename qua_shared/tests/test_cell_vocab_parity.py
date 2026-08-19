"""Parity guard: the qua_shared cell + tajweed vocab mirrors the producer's, and
the schema coerces a v11 cell row's role/status to the enums.

qua_shared cannot import the phonemizer at module load (it must stay off the
inspector runtime import path), so ``CellRole`` / ``CellStatus`` / ``TajweedRule``
are mirrors. The literal-pin tests below run unconditionally (in inspector CI,
where the phonemizer is NOT installed) and freeze the canonical value sets; the
``skipif``-gated tests additionally derive the same sets from the live producer —
so neither end can drift unnoticed.

The producer names a rule; the SHARD tag is that name mapped through
``qua_sdk.integrations.vocabulary`` (renames, the three rules a cell never carries,
and ``wasl_start`` split per prosthetic vowel). ``TajweedRule`` mirrors the shard
tag, so the live check composes the two rather than reading either alone.
"""

from __future__ import annotations

from typing import cast

import pytest

from qua_shared.schemas.bucket.cell_vocab import CellRole, CellStatus
from qua_shared.schemas.bucket.tajweed_vocab import TajweedRule
from qua_shared.schemas.bucket.ts_shard import TsShardWord

# The canonical value sets, pinned as literals so a drift fails even where the
# producer is absent. Keep in lockstep with the producer (the skipif tests below
# assert the live producer yields these exact sets).
_ROLE_VALUES = {"base", "haraka", "tanween", "madd"}
# Four: a cell with no glyph is "inserted"; one whose rules say the reading
# shows a letter other than the written one is "replaced"; the rest are
# "present" or "dropped" by whether the glyph reached a sound. The former
# ``shortened`` named a carrier a shortening silenced, which "dropped" says.
_STATUS_VALUES = {"present", "replaced", "inserted", "dropped"}
_TAJWEED_VALUES = {
    "ghunnah",
    "ikhfaa",
    "ikhfaa_shafawi",
    "iqlab",
    "izhar",
    "izhar_shafawi",
    "idgham_bi_ghunnah",
    "idgham_bila_ghunnah",
    "idgham_shafawi",
    "idgham_mutamathilayn",
    "idgham_mutaqaribayn",
    "idgham_mutajanisayn_kamil",
    "idgham_mutajanisayn_naqis",
    "madd_tabii",
    "madd_wajib_muttasil",
    "madd_jaiz_munfasil",
    "madd_lazim",
    "madd_arid_lil_sukun",
    "madd_leen",
    "madd_iwad",
    "tafkheem",
    "qalqala_sughra",
    "qalqala_kubra",
    "hamza_wasl_fatha",
    "hamza_wasl_kasra",
    "hamza_wasl_damma",
    "hamza_wasl_elision",
    "ibdal_hamza",
    "tashil",
    "imala",
    "ishmam",
    "lam_shamsiyyah",
    "iltiqaa",
    "iltiqaa_kasra",
    "pausal_sukun",
    "taa_marbuta_pausal",
    "orthographic_silence",
}


def _producer():
    try:
        from qua_sdk.integrations import cellrows, vocabulary
        from quranic_phonemizer import tajweed_rules
    except ImportError:
        return None
    return cellrows, vocabulary, tajweed_rules


needs_producer = pytest.mark.skipif(
    _producer() is None, reason="phonemizer / qua_sdk not installed"
)


def _live_tajweed_tags(vocabulary, tajweed_rules) -> set[str]:
    """Every shard tag the producer can put in a cell's ``rules`` list."""
    tags: set[str] = set()
    for rule_id, _en, _ar in tajweed_rules("hafs"):
        if rule_id in vocabulary.DROPPED:
            continue
        if rule_id == "wasl_start":
            tags |= set(vocabulary.WASL_START_BY_QUALITY.values())
            continue
        tags.add(vocabulary.RENAMED.get(rule_id, rule_id))
    return tags


def test_vocab_value_sets_pinned():
    """The mirror value sets are frozen — runs even without the producer."""
    assert {r.value for r in CellRole} == _ROLE_VALUES
    assert {s.value for s in CellStatus} == _STATUS_VALUES
    assert {r.value for r in TajweedRule} == _TAJWEED_VALUES


@needs_producer
def test_role_mirrors_producer():
    producer = _producer()
    assert producer is not None
    cellrows, _vocabulary, _rules = producer
    assert set(cellrows._ROLE_OF_KIND.values()) == _ROLE_VALUES


@needs_producer
def test_status_mirrors_producer():
    """Exercise every branch of ``cellrows._status``: it reads only whether the
    pairing wrote a glyph and whether that glyph reached a sound. A written
    cell under one of the replacement rules takes the fourth instead."""
    from types import SimpleNamespace

    producer = _producer()
    assert producer is not None
    cellrows, vocabulary, _rules = producer
    glyphless = SimpleNamespace(glyphs=())
    written = SimpleNamespace(glyphs=(0,))
    live = {
        cellrows._status(glyphless, []),
        cellrows._status(written, [0]),
        cellrows._status(written, []),
    }
    assert vocabulary.REPLACEMENTS, "no rule shows a cell the letter it is read as"
    assert live | {"replaced"} == {s.value for s in CellStatus} == _STATUS_VALUES


@needs_producer
def test_every_replacement_rule_is_a_shard_tag():
    """A cell shows the reading's letter under a rule name; a rule the shard
    never tags could never reach one."""
    producer = _producer()
    assert producer is not None
    _cellrows, vocabulary, _rules = producer
    assert vocabulary.REPLACEMENTS <= {r.value for r in TajweedRule}
    assert set(vocabulary.IMPLIED) | set(vocabulary.IMPLIED.values()) <= {
        r.value for r in TajweedRule
    }


@needs_producer
def test_tajweed_rule_mirrors_producer():
    producer = _producer()
    assert producer is not None
    _cellrows, vocabulary, tajweed_rules = producer
    live = _live_tajweed_tags(vocabulary, tajweed_rules)
    assert {r.value for r in TajweedRule} == live == _TAJWEED_VALUES


def test_schema_coerces_cell_row():
    word = [
        1,
        10,
        200,
        [["ب", 10, 90, False]],
        [["b", 10, 50], ["i", 50, 90]],
        [
            ["ب", "base", "present", [0], 0, [], None],
            ["ِ", "haraka", "present", [1], 0, ["madd_tabii"], None],
        ],
    ]
    w = TsShardWord.model_validate(word)
    # a word with cells validates to the 6-tuple variant; narrow for the checker.
    cells = cast(tuple[int, int, int, list, list, list], w.root)[5]
    assert cells[0][1] is CellRole.BASE and cells[0][2] is CellStatus.PRESENT
    assert cells[1][1] is CellRole.HARAKA
    # round-trips back to bare strings on the wire (byte pass-through unchanged).
    assert w.model_dump(mode="json")[5][0][1] == "base"
