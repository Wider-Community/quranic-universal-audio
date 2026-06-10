"""Per-chapter Timestamps shard schema — ``reciters/<slug>/timestamps/<ch>.json.gz``.

The temporal segment-array shape written by
``qua_shared/timestamps_shards.py::build_segment_shards`` and consumed by the
deployed Timestamps tab read-path (a byte pass-through — Flask serves the
gzip verbatim, the FE decompresses and renders it).

The FE consumes this document, so it MUST codegen cleanly. The word payload is
a flat positional tuple (``TsShardWord``) modelled as a ``RootModel[tuple[...]]``
so ``pydantic-to-typescript`` emits a positional TS tuple matching the
hand-written ``TsShardWord`` in ``inspector/frontend/src/lib/types/api.ts``.

Document shape (decompressed)::

    {
      "_meta": {schema_version, chapter, audio_category, <aligner provenance>},
      "segments": [{"ref": "1:1", "t": [start_ms, end_ms], "words": [<word>, ...]}, ...]
    }

Each ``word`` is the 5-slot tuple::

    [word_idx, start_ms, end_ms, letters[], phones[]]

where ``letters`` is ``[char, start_ms|null, end_ms|null]`` triples and
``phones`` is ``[phone, start_ms, end_ms, ...optional flags]`` rows (slot 5
may carry a cross-word tajweed bridge rule — see ``timestamps_bridges``).

Extras handling: ``extra="forbid"`` + ``strip_and_warn`` on the document and
``_meta``. The word/letter/phone tuples are positional and are validated by
arity, not by a key set, so they carry no extras surface.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from .._extras import strip_and_warn

# Letter timing triple: [char, start_ms, end_ms]; timings may be null when the
# aligner couldn't place an individual letter.
LetterTiming = tuple[str, int | None, int | None]

# Phone row: [phone, start_ms, end_ms, ...optional flags]. Heterogeneous and
# variable-length (slot 5 = cross-word bridge rule when present), so it stays a
# loose ``list`` of the union of cell types rather than a fixed tuple.
PhoneTiming = list[str | int | bool]


class TsShardWord(RootModel[tuple[int, int, int, list[LetterTiming], list[PhoneTiming]]]):
    """One encoded word inside a segment — a flat positional tuple.

    Slots: ``[word_idx, start_ms, end_ms, letters, phones]``. Modelled as a
    ``RootModel`` over a 5-tuple so the FE codegen emits a positional TS tuple
    (mirrors ``TsShardWord`` in ``api.ts``) rather than an object.
    """


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
