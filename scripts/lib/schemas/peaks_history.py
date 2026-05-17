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
    The legacy ``peaks`` field is kept as a read-only fallback during the
    transition window so old records continue to parse.

Authoritative spec: ``docs/reference/migrate_wip.md`` §5.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PeaksRecord(BaseModel):
    """One pipeline-op waveform slice.

    Required:
      - ``op_id`` — the originating op's ``op_id`` in ``edit_history.jsonl``.
        Primary join key + backfill idempotency dedup key.
      - ``url`` — canonical (proxy-stripped) chapter audio URL. Covering-
        range cache key in the FE waveform layer.
      - ``start_ms`` / ``end_ms`` — bounding box covering all snapshots in
        the op (min/max over targets_before + targets_after).

    Peaks payload — at least ONE form must be present:
      - ``peaks_b64`` + ``bps`` — new canonical encoding (post-#5). Base64
        of n×2 int8s at the given buckets-per-second density.
      - ``peaks`` — legacy ``list[list[float]]`` shape; back-compat for
        old records during transition.
    """

    model_config = ConfigDict(extra="allow")

    op_id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)

    # === New canonical encoding (post-#5) ===
    bps: int | None = Field(None, ge=1)
    peaks_b64: str | None = None

    # === Legacy back-compat (writers no longer emit) ===
    peaks: list[list[float]] | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> "PeaksRecord":
        if self.end_ms <= self.start_ms:
            raise ValueError(
                f"end_ms ({self.end_ms}) must be > start_ms ({self.start_ms})"
            )
        if self.peaks_b64 is None and self.peaks is None:
            raise ValueError(
                "record must carry peaks payload — either `peaks_b64` (new) "
                "or `peaks` (legacy back-compat)"
            )
        if self.peaks_b64 is not None and self.bps is None:
            raise ValueError("`peaks_b64` requires `bps` density tag")
        return self


def parse_peaks_record(raw: dict[str, Any]) -> PeaksRecord:
    """Parse one ``edit_history_peaks.jsonl`` line dict.

    Tolerates legacy fields (``batch_id``, ``duration_ms``,
    ``saved_at_utc``) via ``extra="allow"``. New writers should serialise
    via ``record.model_dump(exclude_none=True)`` to omit absent optional
    fields.
    """
    return PeaksRecord.model_validate(raw)
