"""Backfill missing per-op peaks for pipeline edits.

The alignment pipeline (``.local/extraction/segments/post_passes.py``) writes
``waqf_sakt`` and ``strip_specials`` operations into ``edit_history.jsonl`` but
never the matching records in ``edit_history_peaks.jsonl`` — that file is
appended only by the user-edit save path
(``services/segments/save.py::save_reciter_segments``). Without peaks records,
the History panel's waveform stays blank for pipeline rows.

This module is the catch-up: walk the reciter's history, find pipeline ops
whose ``op_id`` is not yet covered in the peaks JSONL, compute peaks for each
op's time range, and append them. Idempotent — re-running is a no-op once
every pipeline op has a record.

Hooked into the lifecycle from ``services/segments/auto_detect.py`` so it runs
at boot (catch-up for slugs that arrived before this code shipped) and on
every new alignment-completed transition.
"""

from __future__ import annotations

import logging
from typing import Iterable

from services.activity.history_query import parse_history_for_reciter
from services.audio.peaks import compute_segment_peaks
from services.audio.peaks_history import (
    append_peaks_records,
    load_peaks_records,
)
from services.storage.data_loader import load_detailed
from utils.references import chapter_from_ref

logger = logging.getLogger(__name__)


def _audio_url_by_chapter(reciter: str) -> dict[int, str]:
    """Map ``chapter -> entry.audio`` for the reciter's detailed.json.

    Mirrors ``services/segments/segments_query.py:32-37`` — the entry's
    ``audio`` field is the canonical audio URL. The first entry per chapter
    wins (all entries within a chapter share an audio file by construction).
    """
    out: dict[int, str] = {}
    for entry in load_detailed(reciter) or []:
        ch = chapter_from_ref(entry.get("ref", ""))
        if ch and ch not in out:
            audio = entry.get("audio")
            if isinstance(audio, str) and audio:
                out[ch] = audio
    return out


def _iter_pipeline_ops(records: Iterable[dict]) -> Iterable[tuple[dict, dict]]:
    """Yield ``(batch, op)`` for every pipeline op in the records stream.

    A pipeline op is either:
    - any op with ``op_type == "waqf_sakt"`` (regardless of batch_type), or
    - any op inside a batch whose ``batch_type == "strip_specials"``.
    """
    for batch in records:
        if batch.get("record_type") == "genesis":
            continue
        is_strip = batch.get("batch_type") == "strip_specials"
        for op in batch.get("operations") or []:
            if is_strip or op.get("op_type") == "waqf_sakt":
                yield batch, op


def _resolve_op_chapter(op: dict, batch: dict) -> int | None:
    """Pick the chapter for an op.

    Prefer the snapshot's stamped ``chapter`` field (added by the extraction
    fix). Fall back to ``targets_before[0].matched_ref`` chapter parse, then
    the batch-level ``chapter`` (waqf_sakt is one batch per chapter).
    """
    snapshots = (op.get("targets_before") or []) + (op.get("targets_after") or [])
    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        ch = snap.get("chapter")
        if isinstance(ch, int) and ch > 0:
            return ch
        # Legacy snapshots — parse from matched_ref when it's a real Quran ref.
        ref = snap.get("matched_ref", "")
        if isinstance(ref, str) and ref and ":" in ref:
            ch = chapter_from_ref(ref)
            if ch:
                return ch
    bch = batch.get("chapter")
    return bch if isinstance(bch, int) and bch > 0 else None


def _resolve_op_audio_url(
    op: dict, batch: dict, by_chapter: dict[int, str],
) -> str | None:
    """Pick the audio URL for an op. Snapshot first, then chapter lookup."""
    for snap in (op.get("targets_before") or []) + (op.get("targets_after") or []):
        if isinstance(snap, dict):
            url = snap.get("audio_url")
            if isinstance(url, str) and url:
                return url
    ch = _resolve_op_chapter(op, batch)
    if ch is None:
        return None
    return by_chapter.get(ch)


def _op_time_range(op: dict) -> tuple[int, int] | None:
    """Return ``(start_ms, end_ms)`` covering the op's snapshots.

    For waqf_sakt: targets_before are the two split segments; targets_after is
    the merged one. We want the full merge window, so we take the min/max over
    every snapshot. For strip_specials deletions: a single snapshot in
    targets_before. Either way, snapshots[*].time_start/time_end give us the
    range directly.
    """
    snapshots = (op.get("targets_before") or []) + (op.get("targets_after") or [])
    starts: list[int] = []
    ends: list[int] = []
    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        t0 = snap.get("time_start")
        t1 = snap.get("time_end")
        if isinstance(t0, (int, float)) and isinstance(t1, (int, float)) and t1 > t0:
            starts.append(int(t0))
            ends.append(int(t1))
    if not starts:
        return None
    return min(starts), max(ends)


def backfill_pipeline_peaks(reciter: str) -> int:
    """Compute + persist peaks for every pipeline op missing from the peaks JSONL.

    Returns the count of records newly written. Safe to call repeatedly — ops
    already covered are skipped. Failures per-op are logged and skipped (the
    lazy-on-play path remains as a backstop).
    """
    records = parse_history_for_reciter(reciter)
    if not records:
        return 0

    pipeline_ops = list(_iter_pipeline_ops(records))
    if not pipeline_ops:
        return 0

    already_persisted: set[str] = {
        rec.get("op_id")
        for rec in load_peaks_records(reciter)
        if isinstance(rec.get("op_id"), str)
    }

    missing = [
        (batch, op) for batch, op in pipeline_ops
        if op.get("op_id") not in already_persisted
    ]
    if not missing:
        return 0

    by_chapter = _audio_url_by_chapter(reciter)

    written_total = 0
    by_batch: dict[str | None, list[dict]] = {}

    for batch, op in missing:
        op_id = op.get("op_id")
        if not isinstance(op_id, str):
            continue
        rng = _op_time_range(op)
        if rng is None:
            logger.warning(
                "peaks_backfill[%s]: op %s has no usable time range; skipping",
                reciter, op_id,
            )
            continue
        url = _resolve_op_audio_url(op, batch, by_chapter)
        if not url:
            logger.warning(
                "peaks_backfill[%s]: op %s has no resolvable audio_url; skipping",
                reciter, op_id,
            )
            continue
        try:
            data = compute_segment_peaks(url, rng[0], rng[1], reciter)
        except Exception:  # noqa: BLE001
            logger.exception(
                "peaks_backfill[%s]: compute failed for op %s", reciter, op_id,
            )
            continue
        if not data or not data.get("peaks"):
            logger.warning(
                "peaks_backfill[%s]: empty peaks for op %s", reciter, op_id,
            )
            continue
        record = {
            "op_id": op_id,
            "url": url,
            "start_ms": rng[0],
            "end_ms": rng[1],
            "peaks": data["peaks"],
            "duration_ms": data.get("duration_ms", rng[1] - rng[0]),
        }
        by_batch.setdefault(batch.get("batch_id"), []).append(record)

    for batch_id, batch_records in by_batch.items():
        written_total += append_peaks_records(reciter, batch_records, batch_id=batch_id)

    if written_total:
        logger.info(
            "peaks_backfill[%s]: wrote %d peaks record(s) for pipeline ops",
            reciter, written_total,
        )
    return written_total


__all__ = ["backfill_pipeline_peaks"]
