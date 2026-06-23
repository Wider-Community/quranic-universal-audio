"""Per-chapter Timestamps shard schema — ``reciters/<slug>/timestamps/<ch>.json.gz``.

The temporal segment-array shape written by
``qua_shared/timestamps_shards.py::build_segment_shards`` and consumed by the
deployed Timestamps tab read-path (a byte pass-through — Flask serves the
gzip verbatim, the FE decompresses and renders it).

The FE consumes this document, so it MUST codegen cleanly. The word payload is
a flat positional tuple (``TsShardWord``) modelled as a ``RootModel[tuple[...]]``
so ``pydantic-to-typescript`` emits a positional TS tuple matching the FE-typed
``TsShardWord`` projection in ``inspector/frontend/src/lib/types/ts-client.ts``.

Document shape (decompressed)::

    {
      "_meta": {schema_version, chapter, audio_category, <aligner provenance>},
      "segments": [{"ref": "1:1", "t": [start_ms, end_ms], "words": [<word>, ...]}, ...]
    }

Each ``word`` is the 5- or 6-slot tuple::

    [word_idx, start_ms, end_ms, letters[], phones[](, cells[])]

where ``letters`` is ``[char, start_ms|null, end_ms|null(, silent)]`` rows (the
4th ``silent`` bool lands from schema v4 — phonemizer ``silent_flags()``) and
``phones`` is ``[phone, start_ms, end_ms, ...optional flags]`` rows (slot 5
may carry a cross-word tajweed bridge rule — see
``qua_sdk.components.timing.lib.cells``).

The optional 6th slot ``cells`` (schema v5) is the per-character phoneme cells
from the phonemizer's ``character_phoneme_mappings()`` — the full per-character
breakdown. From the SDK annotator move, cells include ``role == 'base'``
(consonant) rows alongside ``haraka``/``tanween``/``madd`` — the structure is
unchanged (``CellTiming`` / ``ts_shard_cells.parse_cell`` already tolerate every
role), only the role set written is wider. Each cell is the positional row
``[chars, role, status, phoneme_indices, source_letter_index, tag, share_group]``;
see ``qua_shared/ts_shard_cells.py``. ``phoneme_indices`` are **word-local indices
over the word's indexable phones** (the qalqala ``Q`` excluded, same coordinate
space as the bridge index). Read via ``ts_shard_cells.parse_cell`` — never unpack
positionally, and tolerate a missing 6th slot on v3/v4 shards.

Extras handling: ``extra="forbid"`` + ``strip_and_warn`` on the document and
``_meta``. The word/letter/phone tuples are positional and are validated by
arity, not by a key set, so they carry no extras surface.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from .._extras import strip_and_warn
from ..config.cell_vocab import CellRole, CellStatus

# Letter timing triple: [char, start_ms, end_ms]; timings may be null when the
# aligner couldn't place an individual letter. A 4th slot ``silent`` (bool) is
# present from schema v4 — true when the grapheme produces no audible phoneme at
# its own position (hamza wasl, lam shamsiyah, the otiose tanween alef, …), so
# the highlight skips it once each letter is its own cell. Sourced from the
# phonemizer's ``silent_flags()``; absent on legacy v3 shards.
LetterTiming = tuple[str, int | None, int | None] | tuple[str, int | None, int | None, bool]

# Phone row: [phone, start_ms, end_ms, ...optional flags]. Heterogeneous and
# variable-length (slot 5 = cross-word bridge rule when present), so it stays a
# loose ``list`` of the union of cell types rather than a fixed tuple.
PhoneTiming = list[str | int | bool]

# Cell row (the 6th word slot): a per-character haraka/tanween cell.
# ``[chars, role, status, phoneme_indices, source_letter_index, tag, share_group]``.
# ``role`` / ``status`` are the codegen-source enums (``config/cell_vocab``);
# ``phoneme_indices`` are word-local indices over the word's indexable phones.
CellTiming = tuple[str, CellRole, CellStatus, list[int], int, str | None, int | None]


class TsShardWord(
    RootModel[
        tuple[int, int, int, list[LetterTiming], list[PhoneTiming]]
        | tuple[int, int, int, list[LetterTiming], list[PhoneTiming], list[CellTiming]]
    ]
):
    """One encoded word inside a segment — a flat positional tuple.

    Slots: ``[word_idx, start_ms, end_ms, letters, phones(, cells)]``. Modelled as
    a ``RootModel`` over a 5- **or** 6-tuple (the 6th ``cells`` slot is schema v5)
    so the FE codegen emits a positional TS tuple (mirrors ``TsShardWord`` in
    ``ts-client.ts``) rather than an object, and v3/v4 shards still validate.
    """


class TsShardCell(BaseModel):
    """Named (object) view of a positional ``CellTiming`` row.

    The shard stores cells positionally (``CellTiming``) and they are read via
    ``ts_shard_cells.parse_cell`` — this model is the codegen vehicle that emits
    ``CellRole`` / ``CellStatus`` as TS string unions for the FE (json2ts drops
    enums referenced only inside a positional tuple), and documents the row's
    fields by name.
    """

    model_config = ConfigDict(extra="forbid")

    chars: str
    role: CellRole
    status: CellStatus
    phoneme_indices: list[int]
    source_letter_index: int
    tag: str | None = None
    share_group: int | None = None


class TsShardSegment(BaseModel):
    """One recited segment in a chapter's temporal ``segments[]`` array.

    ``ref`` is always a single verse ``"surah:ayah"``; ``t`` is the segment's
    ``[start_ms, end_ms]`` span. A verse may recur across several entries
    (loopbacks / re-dos) — every accepted occurrence is one entry, emitted in
    recitation order.
    """

    model_config = ConfigDict(extra="forbid")

    ref: str = Field(..., min_length=1)
    t: tuple[int, int]
    words: list[TsShardWord] = Field(default_factory=list)


class TsShardMeta(BaseModel):
    """Slim per-shard ``_meta`` block.

    Aligner provenance (``padding``, ``beam``, ``method``, ``aligner_model``,
    ``shared_cmvn``, ``audio_source``, ``created_at``) passes through when the
    source ``_meta`` carried it. Audio routing (reciter / url_template /
    audio_urls) is deliberately NOT here — the audio-manifest sidecar is the
    source of truth. ``extra="allow"`` so the optional provenance fields the
    writer copies through stay typed-open for the FE.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int
    chapter: int
    audio_category: str


class TsShardDoc(BaseModel):
    """The decompressed body of one chapter shard: ``_meta`` + ``segments[]``.

    The on-disk JSON key is ``_meta`` (leading underscore); pydantic disallows
    leading-underscore field names, so it is exposed as ``meta`` Python-side
    with ``alias="_meta"``. Serialise with ``model_dump(by_alias=True)``.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    meta: TsShardMeta = Field(..., alias="_meta")
    segments: list[TsShardSegment] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _surface_extras(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        declared = set(TsShardDoc.model_fields)
        declared.add("_meta")  # JSON-side alias for ``meta``
        return strip_and_warn(
            data,
            declared=declared,
            dead=set(),
            model_name="TsShardDoc",
        )
