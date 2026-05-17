"""Per-reciter ``pipeline_meta.json`` schema.

Persistent record of immutable facts emitted by the offline extraction
pipeline so Inspector doesn't have to re-derive them at runtime. Lives at
``wip/<slug>/pipeline_meta.json`` (and ``published/<slug>/pipeline_meta.json``
after publish).

Currently records:

- ``deleted_basmala_chapters`` — the set of chapters whose Basmala was
  stripped by ``strip_specials`` (replaces Inspector's runtime walk of
  ``edit_history.jsonl`` in ``_deleted_basmala_chapters``).

The schema is intentionally lean and forward-compat (``extra="allow"``)
so additional extraction-time facts can land in the same sidecar without
a migration step.

Backfill: ``scripts/backfill_deleted_basmala.py`` derives the field from
the existing ``edit_history.jsonl`` for legacy reciters; new extractions
write the sidecar directly via ``.local/extraction/segments/outputs.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PipelineMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    generated_at: str  # ISO-8601 timestamp, UTC
    deleted_basmala_chapters: list[int] = Field(default_factory=list)
