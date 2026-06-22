"""``qua_shared.ts_shard_letters`` — the named accessor that guards letter-row
reads against positional-unpack drift.

The regression these pin: a shard letter row grew a 4th ``silent`` slot at
schema v4, and every consumer that did ``for char, s, e in letters`` raised
``too many values to unpack (expected 3)``. The accessor must read 3-, 4-, and
any-future-slot rows without breaking.
"""

from __future__ import annotations

import pytest

from qua_shared.ts_shard_letters import LetterRow, iter_letters, parse_letter


def test_parse_letter_reads_legacy_v3_three_slot_row():
    assert parse_letter(["b", 10, 20]) == LetterRow("b", 10, 20, False)


def test_parse_letter_reads_v4_silent_flag():
    assert parse_letter(["a", 30, 40, True]) == LetterRow("a", 30, 40, True)


def test_parse_letter_ignores_future_trailing_slots():
    # The exact failure mode: a row that grew a slot must NOT break the reader.
    assert parse_letter(["m", 0, 5, False, "future"]) == LetterRow("m", 0, 5, False)


def test_parse_letter_preserves_null_timings():
    assert parse_letter(["x", None, None, True]) == LetterRow("x", None, None, True)


def test_parse_letter_rejects_fewer_than_three_slots():
    with pytest.raises(ValueError):
        parse_letter(["x", 1])


def test_iter_letters_maps_each_row():
    rows = [["b", 0, 1], ["a", 1, 2, True]]
    assert list(iter_letters(rows)) == [LetterRow("b", 0, 1, False), LetterRow("a", 1, 2, True)]
