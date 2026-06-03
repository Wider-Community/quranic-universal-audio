"""Per-reciter ``pipeline_meta.json`` schema.

Persistent record of immutable facts emitted by the offline extraction
pipeline so Inspector doesn't have to re-derive them at runtime. Lives at
``reciters/<slug>/pipeline_meta.json``.

Currently records:

- ``deleted_basmala_chapters`` — the set of chapters whose Basmala was
  stripped by ``strip_specials`` (replaces Inspector's runtime walk of
  ``edit_history.jsonl`` in ``_deleted_basmala_chapters``).

Extras handling: ``extra="forbid"`` + ``strip_and_warn`` (consistent with
the rest of the canonical schemas). The model is lean and well-defined;
any unknown field surfaces a WARNING so we don't accumulate bloat
silently.

Backfill: ``scripts/backfill_deleted_basmala.py`` derives the field from
the existing ``edit_history.jsonl`` for legacy reciters; new extractions
write the sidecar directly via ``.local/extraction/segments/outputs.py``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ._extras import strip_and_warn


class PipelineMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    generated_at: str  # ISO-8601 timestamp, UTC
    deleted_basmala_chapters: list[int] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _surface_extras(cls, data: Any) -> Any:
        return strip_and_warn(
            data,
            declared=set(cls.model_fields),
            dead=set(),
            model_name="PipelineMeta",
        )
