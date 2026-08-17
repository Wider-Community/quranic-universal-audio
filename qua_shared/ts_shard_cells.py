"""Named accessor for Timestamps-shard cell rows — the 6th word slot, eight slots.

A shard word's optional 6th slot ``cells`` is a list of POSITIONAL rows
``[chars, role, status, phoneme_indices, source_letter_index, rules, share_group,
phoneme_rules]``
— see ``CellTiming`` in ``qua_shared/schemas/bucket/ts_shard.py``. They are the
per-character highlight tier from the producer's projection, which includes
``role == 'base'`` (consonant) rows alongside ``haraka``/``tanween``/``madd`` —
the full per-character breakdown (base consonants ALSO remain in ``letters[]``).

``phoneme_indices`` are **word-local indices over the word's indexable phones**
(the qalqala ``Q`` and other render-only markers excluded — the same coordinate
space as the bridge index, see ``qua_sdk.integrations.tokens.is_indexable``). To
resolve a cell's timing, walk the word's ``phones`` skipping render-only markers
and take the ``phoneme_indices``-th entries.

Consumers MUST read cells through ``parse_cell`` / ``iter_cells`` / ``word_cells``
rather than unpacking positionally, and MUST tolerate a word with no 6th slot
(v3/v4 shards) — ``word_cells`` returns ``[]`` there. This mirrors
``ts_shard_letters`` and keeps a future trailing slot from breaking a reader.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import NamedTuple


class CellRow(NamedTuple):
    """One character-phoneme cell, by name.

    ``role`` in {``base``, ``haraka``, ``tanween``, ``madd``}; ``status`` in
    {``present``, ``replaced``, ``inserted``, ``dropped``}. ``chars`` is the
    canonical source character(s), ``""`` for a fully implicit cell.
    ``phoneme_indices`` are word-local indexable-phone indices (``[]`` = silent).
    ``source_letter_index`` is the anchoring letter (``-1`` if fully implicit).
    ``rules`` is every rule the producer fired on the grapheme, in its order and
    possibly empty — there is no primary; ``share_group`` ties co-timed cells.

    ``phoneme_rules`` says which of ``phoneme_indices`` each rule is on, as one
    list per phone in that order. It is ``None`` for the ordinary cell, whose
    phones all name what ``rules`` names. A letter read as a whole word is the
    reason it exists: ``عٓ`` says four sounds and the hidden noon is the only one
    the ikhfaa is on, so drawing ``rules`` across the cell would light all four.
    """

    chars: str
    role: str
    status: str
    phoneme_indices: list[int]
    source_letter_index: int
    rules: list[str]
    share_group: int | None = None
    phoneme_rules: list[list[str]] | None = None


def parse_cell(row: object) -> CellRow:
    """Parse one positional cell row into a :class:`CellRow`.

    Reads only the named positions and ignores any trailing slot beyond the 8th.
    Raises ``ValueError`` on a row with fewer than the 5 required slots.
    """
    seq = tuple(row)  # type: ignore[call-overload]
    if len(seq) < 5:
        raise ValueError(
            f"cell row needs >=5 slots [chars, role, status, phoneme_indices, "
            f"source_letter_index], got {seq!r}"
        )
    chars, role, status, phoneme_indices, source_letter_index = seq[:5]
    raw_rules = seq[5] if len(seq) > 5 else None
    share_group = seq[6] if len(seq) > 6 else None
    per_phone = seq[7] if len(seq) > 7 else None
    return CellRow(
        str(chars),
        str(role),
        str(status),
        list(phoneme_indices),
        int(source_letter_index),
        _rules(raw_rules),
        share_group,
        [list(tags) for tags in per_phone] if per_phone else None,
    )


def _rules(raw: object) -> list[str]:
    """Slot 5 as a rule list. A shard written before the list carried one tag
    string there; reading it as characters would be silent nonsense."""
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    return list(raw)  # type: ignore[call-overload]


def iter_cells(rows: Iterable[object]) -> Iterator[CellRow]:
    """Yield each positional cell row in ``rows`` as a :class:`CellRow`."""
    for row in rows:
        yield parse_cell(row)


def word_cells(word: Sequence) -> list[CellRow]:
    """Cells of a shard ``word`` tuple — ``[]`` when the 6th slot is absent (v3/v4)."""
    if len(word) <= 5 or not word[5]:
        return []
    return list(iter_cells(word[5]))
