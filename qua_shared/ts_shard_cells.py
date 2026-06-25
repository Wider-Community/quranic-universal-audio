"""Named accessor for Timestamps-shard cell rows (schema v5, the 6th word slot).

A shard word's optional 6th slot ``cells`` is a list of POSITIONAL rows
``[chars, role, status, phoneme_indices, source_letter_index, tag, share_group
(, phoneme_rule_tags)]`` — see ``CellTiming`` in
``qua_shared/schemas/bucket/ts_shard.py``. The 8th slot ``phoneme_rule_tags``
(schema v8) is optional; readers tolerate its absence on v5-v7 shards. They are the
per-character highlight tier from the phonemizer's
``character_phoneme_mappings()``. From the SDK annotator move, this includes
``role == 'base'`` (consonant) rows alongside ``haraka``/``tanween``/``madd`` —
the full per-character breakdown (base consonants ALSO remain in ``letters[]``).

``phoneme_indices`` are **word-local indices over the word's indexable phones**
(the qalqala ``Q`` and other render-only markers excluded — the same coordinate
space as the bridge index, see
``qua_sdk.components.timing.lib.cells._is_indexable``). To resolve a
cell's timing, walk the word's ``phones`` skipping render-only markers and take the
``phoneme_indices``-th entries.

Consumers MUST read cells through ``parse_cell`` / ``iter_cells`` / ``word_cells``
rather than unpacking positionally, and MUST tolerate a word with no 6th slot
(v3/v4 shards) — ``word_cells`` returns ``[]`` there. This mirrors
``ts_shard_letters`` and keeps a future trailing slot from breaking a reader.

This 7-slot row is the SDK's shard projection (written by
``qua_sdk.components.timing.lib.cells._stamp_cells``, read here). It is a DIFFERENT
contract from the phonemizer's ``Cell.to_list`` (a fuller 9-field dump in its own
field order) — do not apply one's positions to the other.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import NamedTuple


class CellRow(NamedTuple):
    """One character-phoneme cell, by name.

    ``role`` ∈ {``base``, ``haraka``, ``tanween``, ``madd``} — the SDK annotator
    emits ``base`` (consonant) rows too (base consonants ALSO remain in
    ``letters[]``). ``status`` ∈ {``present``, ``inserted``,
    ``dropped``, ``replaced``, ``shortened``}. ``chars`` is the canonical source
    character(s), ``""`` for a fully implicit cell. ``phoneme_indices`` are
    word-local indexable-phone indices (``[]`` = silent). ``source_letter_index``
    is the anchoring letter (``-1`` if fully implicit). ``tag`` is the canonical
    rule/case key the renderer switches on; ``share_group`` ties co-timed cells.
    ``phoneme_rule_tags`` (schema v8, optional) is a per-phoneme tag list parallel
    to ``phoneme_indices`` (each entry a rule key or ``None``) for cells whose
    phonemes carry distinct tajweed (muqattaat); ``None`` on v5-v7 shards.
    """

    chars: str
    role: str
    status: str
    phoneme_indices: list[int]
    source_letter_index: int
    tag: str | None = None
    share_group: int | None = None
    phoneme_rule_tags: list[str | None] | None = None


def parse_cell(row: object) -> CellRow:
    """Parse one positional cell row into a :class:`CellRow`.

    Reads only the named positions and ignores any trailing slot beyond the 8th.
    Raises ``ValueError`` on a row with fewer than the 5 required slots. The 8th
    slot ``phoneme_rule_tags`` (schema v8) is a per-phoneme tag list parallel to
    ``phoneme_indices``; ``None`` when absent (v5-v7 shards).
    """
    seq = tuple(row)  # type: ignore[call-overload]
    if len(seq) < 5:
        raise ValueError(
            f"cell row needs >=5 slots [chars, role, status, phoneme_indices, "
            f"source_letter_index], got {seq!r}"
        )
    chars, role, status, phoneme_indices, source_letter_index = seq[:5]
    tag = seq[5] if len(seq) > 5 else None
    share_group = seq[6] if len(seq) > 6 else None
    raw_rule_tags = seq[7] if len(seq) > 7 else None
    phoneme_rule_tags = list(raw_rule_tags) if raw_rule_tags is not None else None
    return CellRow(
        str(chars),
        str(role),
        str(status),
        list(phoneme_indices),
        int(source_letter_index),
        tag,
        share_group,
        phoneme_rule_tags,
    )


def iter_cells(rows: Iterable[object]) -> Iterator[CellRow]:
    """Yield each positional cell row in ``rows`` as a :class:`CellRow`."""
    for row in rows:
        yield parse_cell(row)


def word_cells(word: Sequence) -> list[CellRow]:
    """Cells of a shard ``word`` tuple — ``[]`` when the 6th slot is absent (v3/v4)."""
    if len(word) <= 5 or not word[5]:
        return []
    return list(iter_cells(word[5]))
