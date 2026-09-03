"""Wire shapes for maintainer-uploaded alignment samples (``/api/samples``).

A sample is one audio file plus one aligner-contract JSON, ingested into the
bucket under ``samples/<id>/`` and edited through the Segments view under the
slug ``sample--<id>``. The list row carries ownership, ingest status and the
"changed since export" signal; the upload itself is multipart (not modelled).

- ``SampleRow`` — one list entry (``GET /api/samples``, create/rename acks).
- ``SampleReviewRequest`` — ``POST /api/samples/<id>/review`` body.
- ``SamplesListResponse`` — the list envelope.
- ``SampleRenameRequest`` — ``PATCH /api/samples/<id>`` body.
- ``SampleRealignRequest`` / ``SampleRealignResponse`` — ``POST
  /api/samples/<id>/realign``: fresh word timings for one segment span (as
  the editor holds it) from the timing Space, audio-absolute ms, for the FE
  to commit via a save.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .seg import SegWordTiming

SampleStatus = Literal["processing", "ready", "failed"]
SampleSourceSchema = Literal["alignment", "alignment_resource", "legacy"]


class SampleRow(BaseModel):
    """One sample as the list and the acks render it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    slug: str
    name: str
    owner_hf_user_id: str
    owner_login: str | None = None
    status: SampleStatus
    error: str | None = None
    audio_filename: str
    audio_duration_ms: int | None = None
    source_schema: SampleSourceSchema
    pseudo_chapter: int
    created_at: str
    last_save_at: str | None = None
    last_export_at: str | None = None
    changed_since_export: bool
    #: Every Quran-ref segment carries a timing for each word of its ref.
    wbw_complete: bool = False
    #: Set while a maintainer's sign-off stands; cleared by the next save.
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    reviewed_by_login: str | None = None
    can_manage: bool


class SamplesListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    samples: list[SampleRow]


class SampleRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)


class SampleReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed: bool


class SampleRealignRequest(BaseModel):
    """The segment as the editor currently holds it: the FE may still be
    inside its autosave window, so the bucket copy is not consulted."""

    model_config = ConfigDict(extra="forbid")

    segment_uid: str = Field(..., min_length=1)
    matched_ref: str = Field(..., min_length=1)
    time_start: int = Field(..., ge=0)
    time_end: int = Field(..., ge=0)


class SampleRealignResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word_timings: list[SegWordTiming]
