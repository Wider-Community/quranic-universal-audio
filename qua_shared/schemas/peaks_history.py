"""Per-op waveform-slice sidecar schema (``edit_history_peaks.jsonl``).

One ``PeaksRecord`` per pipeline edit-history op (``waqf_sakt`` or
``delete_segment``/``strip_specials``). Read by the Inspector's History
panel so pre/post-op waveforms render with zero runtime compute.

Two writers must produce byte-equivalent records:
  - Offline: ``.local/extraction/segments/audio_persist.py::write_edit_history_peaks``
  - Runtime: ``inspector/services/audio/peaks_backfill.py::backfill_pipeline_peaks``

Migration #5 changes:
  - Drops ``batch_id`` (no reader filters by it; op_id is the join key).
  - Drops ``duration_ms`` (derivable from ``end_ms - start_ms``).
  - Drops ``saved_at_utc`` (no reader; same pattern as the timestamps
    dropped in migration #4).
  - Migrates peaks payload from ``list[list[float]]`` JSON to int8-b64
    encoded blob (mirror of ``services/audio/peaks_slim.py::pack_slim``).
    The legacy ``peaks`` shape is **no longer accepted** — existing bucket
    records must be migrated via ``migrate_wip5_in_place.py``.

Extras handling: ``extra="forbid"`` + ``strip_and_warn`` pre-validator
(legacy → INFO; unknown → WARNING). Legacy verbose-shape records carry
``peaks: list[list[float]]`` *and* lack ``peaks_b64`` — those are still
rejected (they need re-encoding via the migration script) because the
pre-validator only strips bloat, not malformed records.

Authoritative spec: ``docs/reference/data-migrations.md`` §5.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ._extras import strip_and_warn

_PEAKS_DEAD_FIELDS: set[str] = {
    # Migration #5 — verbose peaks payload + redundant metadata
    "peaks",
    "batch_id",
    "saved_at_utc",
    "duration_ms",
}


class PeaksRecord(BaseModel):
    """One pipeline-op waveform slice. Migration #5 canonical shape.

    All fields required:
      - ``op_id`` — the originating op's ``op_id`` in ``edit_history.jsonl``.
        Primary join key + backfill idempotency dedup key.
      - ``url`` — canonical (proxy-stripped) chapter audio URL. Covering-
        range cache key in the FE waveform layer.
      - ``start_ms`` / ``end_ms`` — bounding box covering all snapshots in
        the op (min/max over targets_before + targets_after).
      - ``bps`` + ``peaks_b64`` — peaks payload. Base64 of n×2 int8s at the
        given buckets-per-second density. Mirrors
        ``inspector/services/audio/peaks_slim.py::pack_slim``'s int8
        quantisation; ``peaks_history.py::_inflate_peaks_b64`` is the
        inverse for FE consumers that expect ``list[list[float]]``.

    The pre-Migration #5 ``peaks: list[list[float]]`` shape is not
    accepted — existing bucket records must be re-encoded via the
    one-shot migration script before this schema sees them.
    """

    model_config = ConfigDict(extra="forbid")

    op_id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    bps: int = Field(..., ge=1)
    peaks_b64: str = Field(..., min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _surface_extras(cls, data: Any) -> Any:
        return strip_and_warn(
            data,
            declared=set(cls.model_fields),
            dead=_PEAKS_DEAD_FIELDS,
            model_name="PeaksRecord",
        )

    @model_validator(mode="after")
    def _validate_shape(self) -> PeaksRecord:
        if self.end_ms <= self.start_ms:
            raise ValueError(f"end_ms ({self.end_ms}) must be > start_ms ({self.start_ms})")
        return self


def parse_peaks_record(raw: dict[str, Any]) -> PeaksRecord:
    """Parse one ``edit_history_peaks.jsonl`` line dict.

    Migration #5 dead fields (``peaks``, ``batch_id``, ``duration_ms``,
    ``saved_at_utc``) are stripped with an INFO log; unknown extras log
    WARNING. Records missing ``peaks_b64`` (legacy verbose-only shape)
    still fail at the field-level validator — they need re-encoding via
    the one-shot migration script first.
    """
    return PeaksRecord.model_validate(raw)
