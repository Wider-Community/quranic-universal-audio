"""Per-reciter ``detailed.json`` segment schema.

Shared source of truth for the per-segment shape inside
``wip/<slug>/detailed.json`` and ``published/<slug>/detailed.json``.
Both the offline extraction pipeline (`.local/extraction/segments/outputs.py`)
and the Inspector save flow (`inspector/services/segments/save.py`) MUST
round-trip through this model — that is the structural fix for the
writer/reader drift we discovered in migration #4 + #5 (see
``docs/reference/migrate_wip.md`` §5).

``DetailedDocument`` wraps ``_meta`` + ``entries[]``; ``DetailedEntry``
wraps a per-chapter group; ``DetailedSegment`` is the atomic unit and
where 99% of the bytes live.

Forward-compat reads: ``extra="allow"`` tolerates unknown legacy fields
(e.g. snapshots from older extractions that still carry ``matched_text``
or ``has_repeated_words``). Writers should serialise with
``model_dump(exclude_none=True)`` so optional fields with no value don't
land as ``null`` in the JSON.

Authoritative spec: ``docs/reference/migrate_wip.md`` §5.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DetailedSegment(BaseModel):
    """Atomic seg in a chapter's ``segments`` list.

    Required (every writer always emits):
      - ``time_start`` / ``time_end`` — ms offsets within the chapter audio.
      - ``matched_ref`` — DP alignment span, e.g. ``"1:1:1-1:1:4"`` for
        canonical refs, or a special token (``"Basmala"``, ``"Isti'adha"``,
        ``"Amin"``, ``"Takbir"``, ``"Tahmeed"``, ``"Tasleem"``, ``"Sadaqa"``)
        for transition segs that get stripped by the post-pass.

    Persisted classifier optimisations (migrate_wip §2):
      - ``qalqala_letter`` — last Arabic letter when it's in the qalqala set
        (ق ط ب ج د), else ``None``. Default ``None`` for legacy data.
      - ``is_boundary_adj`` — pad-floor boundary flag (structural + phoneme
        tail). Default ``False`` for legacy data.

    Optional content fields:
      - ``confidence`` — DP alignment confidence in ``[0.0, 1.0]``. Failed
        alignments get ``0.0``.
      - ``matched_text`` — derivable from ``matched_ref`` via
        ``services/reference/quran_refs.py::dk_text_for_ref``. New extraction
        does NOT emit this; legacy on-disk data still has it (back-compat
        read). DROPPED in migration #5.
      - ``phonemes_asr`` — IPA phonemes from the ASR. Default-OFF in
        extraction output as of migration #5 (consumed internally at
        extraction time for ``is_boundary_adj`` stamping, then discarded).
        Re-enable with ``extract_segments.py --with-phonemes-asr`` for the
        ``SHOW_BOUNDARY_PHONEMES`` debug panel.
      - ``wrap_word_ranges`` — repetition-wrap geometry. Truthy iff the seg
        contains a multi-pass recital pattern. The ``repetitions``
        validation category triggers ONLY off this field (not the now-
        retired ``has_repeated_words`` boolean tautology).
      - ``segment_uid`` — UUIDv7 stamped by save-flow merge / split / strip
        ops and by the ``/seg/all`` lazy backfill route. Absent on fresh
        extraction output.
    """

    model_config = ConfigDict(extra="allow")

    # === Always-present (every writer) ===
    time_start: int = Field(..., ge=0)
    time_end: int = Field(..., ge=0)
    matched_ref: str

    # === Persisted classifier optimisations ===
    qalqala_letter: str | None = None
    is_boundary_adj: bool = False

    # === Optional content ===
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    matched_text: str | None = None
    phonemes_asr: str | None = None
    wrap_word_ranges: list[list[str]] | None = None
    segment_uid: str | None = None

    @model_validator(mode="after")
    def _validate_time_range(self) -> "DetailedSegment":
        if self.time_end < self.time_start:
            raise ValueError(
                f"time_end ({self.time_end}) must be >= time_start "
                f"({self.time_start})"
            )
        return self


class DetailedEntry(BaseModel):
    """Per-chapter group: ``{ref, segments[]}``.

    ``audio`` (per-chapter URL) was a duplicated source of truth with
    ``catalog/audio_manifest/<slug>.json::chapters[ch].url`` and was
    dropped in migration #5. Legacy on-disk data still has it; readers
    consume it via ``extra="allow"`` until those readers migrate to
    ``services.audio.audio_meta.chapter_urls(slug)[ch]``.
    """

    model_config = ConfigDict(extra="allow")

    ref: str = Field(..., min_length=1)
    segments: list[DetailedSegment] = Field(default_factory=list)


class DetailedMeta(BaseModel):
    """The ``_meta`` block at the top of ``detailed.json``.

    Kept lean per user direction — ``audio_source`` is load-bearing for
    ``.github/scripts/build_reciter.py`` + ``package_release.py``;
    pad / floor fields are read by ``services/storage/data_loader.py::
    resolve_pad``; the rest is provenance.
    """

    model_config = ConfigDict(extra="allow")

    created_at: str | None = None  # ISO-8601 timestamp; informational
    asr_model: str | None = None
    vad_model: str | None = None
    min_silence_ms: int | None = None
    min_speech_ms: int | None = None
    pad_left_ms: int | None = None
    pad_right_ms: int | None = None
    min_silence_floor_ms: int | None = None
    audio_source: str | None = None  # downstream consumers depend on this


class DetailedDocument(BaseModel):
    """Whole ``detailed.json`` document.

    Note: the on-disk JSON key is ``_meta`` (with leading underscore) for
    historical reasons. Pydantic disallows leading-underscore field names,
    so we expose it as ``meta`` Python-side with an ``alias="_meta"`` for
    JSON I/O. Use ``model_dump(by_alias=True)`` when serialising.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    meta: DetailedMeta = Field(default_factory=DetailedMeta, alias="_meta")
    entries: list[DetailedEntry] = Field(default_factory=list)


def parse_detailed_segment(raw: dict[str, Any]) -> DetailedSegment:
    """Parse one seg dict (e.g. from inside ``entries[i].segments``).

    Tolerates legacy fields (``matched_text``, ``has_repeated_words``,
    ``phonemes_asr``) via ``extra="allow"``. New writers should serialise
    via ``seg.model_dump(exclude_none=True)`` to omit fields without value.
    """
    return DetailedSegment.model_validate(raw)
