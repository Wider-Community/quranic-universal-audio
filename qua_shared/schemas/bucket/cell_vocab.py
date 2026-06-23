"""Per-character cell role / status vocabulary — the codegen source for the FE.

These mirror the phonemizer's canonical ``CellRole`` / ``CellStatus`` (the producer
owns the domain vocabulary). The dependency arrows point away from each other
(phonemizer ← sdk ← app), and the phonemizer must stay off the inspector runtime
import path, so qua_shared cannot import it at module load — instead these enums
are the codegen-facing mirror and ``tests/test_cell_vocab_parity.py`` asserts they
stay byte-equal to the phonemizer's values (so they can never drift).

Referenced by ``CellTiming`` (``bucket/ts_shard.py``) so the FE-types codegen emits
``CellRole`` / ``CellStatus`` as TS string unions, replacing the FE's former
hand-typed literals.
"""

from __future__ import annotations

from enum import Enum


class CellRole(str, Enum):
    BASE = "base"
    HARAKA = "haraka"
    TANWEEN = "tanween"
    MADD = "madd"

    __str__ = str.__str__  # str()/f-string yield the value, not "CellRole.BASE"


class CellStatus(str, Enum):
    PRESENT = "present"
    INSERTED = "inserted"
    DROPPED = "dropped"
    REPLACED = "replaced"
    SHORTENED = "shortened"

    __str__ = str.__str__
