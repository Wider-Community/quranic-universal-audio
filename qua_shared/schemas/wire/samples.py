"""Wire shapes for maintainer-uploaded alignment samples (``/api/samples``).

A sample is one audio file plus one aligner-contract JSON, ingested into the
bucket under ``samples/<id>/`` and edited through the Segments view under the
slug ``sample--<id>``. The list row carries ownership, ingest status and the
"changed since export" signal; the upload itself is multipart (not modelled).

- ``SampleRow`` — one list entry (``GET /api/samples``, create/rename acks).
- ``SamplesListResponse`` — the list envelope.
- ``SampleRenameRequest`` — ``PATCH /api/samples/<id>`` body.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SampleStatus = Literal["processing", "ready", "failed"]
SampleSourceSchema = Literal["alignment", "alignment_resource"]


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
    can_manage: bool


class SamplesListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    samples: list[SampleRow]


class SampleRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
