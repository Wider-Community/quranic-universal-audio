"""Named accessor for Timestamps-shard letter rows.

A shard word's ``letters`` is a list of POSITIONAL rows
``[char, start_ms, end_ms]`` or ``[char, start_ms, end_ms, silent]`` — see
``LetterTiming`` in ``qua_shared/schemas/bucket/ts_shard.py``. The 4th ``silent``
bool arrived with schema v4 (phonemizer ``silent_flags()``); legacy v3 rows omit
it.

Consumers (HF dataset publish, GH release cut, …) MUST read letters through
``parse_letter`` / ``iter_letters`` rather than unpacking a row positionally. A
bare ``for char, s, e in letters`` breaks the instant the row grows a slot —
which is exactly how the v4 ``silent`` field silently took down every publish
and cut (``ValueError: too many values to unpack (expected 3)``). The accessor
reads only the slots it names and ignores any trailing ones, so a future slot
can't break a reader.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import NamedTuple


class LetterRow(NamedTuple):
    """One letter timing, by name.

    ``start_ms`` / ``end_ms`` may be ``None`` when the aligner couldn't place the
    letter. ``silent`` is ``True`` for a grapheme that produces no audible phoneme
    at its own position (hamza wasl, lam shamsiyah, …); it is absent on legacy v3
    rows and defaults to ``False``.
    """

    char: str
    start_ms: int | None
    end_ms: int | None
    silent: bool = False


def parse_letter(row: object) -> LetterRow:
    """Parse one positional letter row into a :class:`LetterRow`.

    Tolerates 3-slot (legacy v3) and 4-slot (v4 ``silent``) rows — and any future
    trailing slot — by reading only the named positions. Raises ``ValueError`` on
    a row with fewer than the 3 required slots.
    """
    seq = tuple(row)  # type: ignore[call-overload]
    if len(seq) < 3:
        raise ValueError(f"letter row needs >=3 slots [char, start, end], got {seq!r}")
    char, start_ms, end_ms = seq[0], seq[1], seq[2]
    silent = bool(seq[3]) if len(seq) > 3 else False
    return LetterRow(str(char), start_ms, end_ms, silent)


def iter_letters(rows: Iterable[object]) -> Iterator[LetterRow]:
    """Yield each positional letter row in ``rows`` as a :class:`LetterRow`."""
    for row in rows:
        yield parse_letter(row)
