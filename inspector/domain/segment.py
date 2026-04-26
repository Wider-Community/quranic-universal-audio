"""Segment domain object.

Frozen dataclass representing a single aligned segment as stored in
detailed.json.  Adapters in ``inspector/adapters/`` convert between this
type and raw dict/JSON forms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Segment:
    """A single aligned recitation segment."""

    segment_uid: str
    chapter: int
    index: int
    time_start: int
    time_end: int
    matched_ref: str
    matched_text: str
    display_text: str
    confidence: float
    phonemes_asr: str
    entry_ref: str
    audio_url: str
    wrap_word_ranges: Optional[object] = None
    has_repeated_words: bool = False
    ignored_categories: tuple[str, ...] = field(default_factory=tuple)
