"""Cross-word tajweed bridges — ``GET /api/ts/tajweed/<verse_ref>`` response.

The Timestamps Analysis view renders cross-word special-rule phonemes as a
gold-bordered "bridge" tile that sits between two word blocks. The backend
derives these bridges from ``quranic_phonemizer.Phonemizer`` per (verse_ref,
stop_refs) so that:

- bridges are data-driven (no FE-side regex on phoneme symbols), and
- bridges disappear at the reciter's actual waqf (stops kill cross-word
  rules — the phonemizer handles this when ``stop_refs`` are passed in).

The merged result is always a single phoneme; whether it physically lives at
PREV-word-last or CURR-word-first is the phonemizer's decision and the FE
respects it via ``side``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BridgeInfo(BaseModel):
    """One cross-word tajweed bridge.

    - ``before_word_idx`` — the bridge tile renders BEFORE this word index
      (i.e. between word ``before_word_idx - 1`` and ``before_word_idx``).
      Word indices are 1-based, matching the phonemizer + shard convention.
    - ``rule`` — the source tajweed rule (one of the 8 cross-word rules in
      scope; see ``services/reference/tajweed.py::BRIDGE_RULES``).
    - ``side`` — ``"curr"`` if the merged phoneme lives at the start of word
      ``before_word_idx``; ``"prev"`` if it lives at the end of word
      ``before_word_idx - 1``. Determined by inspecting the phonemizer's
      per-word phoneme output, not by hardcoded per-rule conventions.
    """

    model_config = ConfigDict(extra="forbid")

    before_word_idx: int = Field(..., ge=1)
    rule: str
    side: Literal["prev", "curr"]


class TajweedBridgesResponse(BaseModel):
    """``GET /api/ts/tajweed/<verse_ref>`` body."""

    model_config = ConfigDict(extra="forbid")

    verse_ref: str
    stops: list[str] = Field(default_factory=list)
    bridges: list[BridgeInfo] = Field(default_factory=list)
