"""Per-character cell role / status vocabulary — the codegen source for the FE.

These mirror what the producer writes into a shard cell row: ``CellRole`` the
roles ``qua_sdk.integrations.cellrows`` assigns a glyph, ``CellStatus`` what the
reading did with the rasm at that cell. The dependency arrows point away from each
other (phonemizer <- sdk <- app), and the phonemizer must stay off the inspector
runtime import path, so qua_shared cannot import it at module load — instead these
enums are the codegen-facing mirror and ``tests/test_cell_vocab_parity.py`` asserts
they stay equal to the live producer's values (so they can never drift).

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
    PRESENT = "present"      # the rasm wrote it and the reading keeps it
    REPLACED = "replaced"    # written, and shown as the letter the reading gives it
    INSERTED = "inserted"    # a cell of its own, for what the rasm never wrote
    DROPPED = "dropped"      # written, and said nothing

    __str__ = str.__str__
