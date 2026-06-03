"""Build per-op history-peaks records by slicing baked chapter peaks.

A history-peaks record (``edit_history_peaks.jsonl``) lets the History panel
render an op's pre/post waveform with zero recompute. The cheap, complete way
to produce one at save time is to **slice the already-baked 10 bps chapter
peaks** (``reciters/<slug>/peaks/<ch>.json.gz``) for the op's covering range —
no ffmpeg, no float roundtrip — and re-encode the int8 sub-range as b64.

Single source of truth for the op→record shape, reused by:
  - ``services/segments/save.py::save_seg_data`` — runtime, every editor save.
  - ``scripts/backfill_pipeline_peaks.py`` — one-shot CLI catch-up (pipeline
    ops), which keeps its own ffmpeg compute path but shares the pure helpers
    here so the op→range/url resolution never drifts.

Canonical record shape (Migration #5): ``{op_id, url, start_ms, end_ms, bps,
peaks_b64}`` — see ``qua_shared/schemas/peaks_history.py``.
"""
from __future__ import annotations

import base64
import logging
import math
from typing import Iterable

import numpy as np

from services.audio import audio_fetch
from services.audio.peaks_history import normalize_audio_url

log = logging.getLogger(__name__)


def _snaps(op: dict) -> list[dict]:
    """All snapshot dicts on an op (``targets_before`` + ``targets_after``)."""
    out: list[dict] = []
    for key in ("targets_before", "targets_after"):
        arr = op.get(key)
        if isinstance(arr, list):
            out.extend(s for s in arr if isinstance(s, dict))
    return out


def op_time_range(op: dict) -> tuple[int, int] | None:
    """``(min start_ms, max end_ms)`` across an op's snapshots, or ``None``.

    A delete op carries only ``targets_before``; its before-snapshot still
    supplies a range, so deletes are covered.
    """
    starts: list[int] = []
    ends: list[int] = []
    for snap in _snaps(op):
        t0 = snap.get("time_start")
        t1 = snap.get("time_end")
        if isinstance(t0, (int, float)) and isinstance(t1, (int, float)) and t1 > t0:
            starts.append(int(t0))
            ends.append(int(t1))
    if not starts:
        return None
    return min(starts), max(ends)


def resolve_op_chapter(op: dict, default_chapter: int | None = None) -> int | None:
    """Snapshot ``chapter`` first, then ``default_chapter`` (the save's chapter
    or the batch chapter)."""
    for snap in _snaps(op):
        ch = snap.get("chapter")
        if isinstance(ch, int) and ch > 0:
            return ch
    if isinstance(default_chapter, int) and default_chapter > 0:
        return default_chapter
    return None


def resolve_op_url(
    op: dict,
    by_chapter: dict[int, str],
    default_chapter: int | None = None,
) -> str | None:
    """Snapshot's stamped ``audio_url`` first, then catalog lookup by chapter."""
    for snap in _snaps(op):
        url = snap.get("audio_url")
        if isinstance(url, str) and url:
            return url
    ch = resolve_op_chapter(op, default_chapter)
    if ch is None:
        return None
    return by_chapter.get(ch)


def slice_chapter_peaks_b64(
    reciter: str, url: str, start_ms: int, end_ms: int,
) -> tuple[str, int, int, int] | None:
    """Slice the baked chapter peaks for ``url`` over ``[start_ms, end_ms]``.

    Reads the slim int8 envelope (``audio_fetch.read_prefetched_peaks``),
    slices the int8 buckets covering the range, and re-encodes that sub-range
    as b64 — no dequant, lossless against the baked 10 bps source.

    Returns ``(peaks_b64, bps, actual_start_ms, actual_end_ms)`` or ``None``
    when peaks aren't baked for that chapter / the range is empty. The
    returned span is the bucket-snapped ACTUAL span so the invariant
    ``n == (end - start) * bps / 1000`` holds for the consumer's pps math.
    """
    env = audio_fetch.read_prefetched_peaks(reciter, url)
    if not env:
        return None
    n = int(env.get("n") or 0)
    duration_ms = int(env.get("duration_ms") or 0)
    bps = int(env.get("bps") or 0)
    b64 = env.get("peaks_b64")
    if n <= 0 or duration_ms <= 0 or bps < 1 or not isinstance(b64, str):
        return None
    try:
        i8 = np.frombuffer(base64.b64decode(b64), dtype=np.int8)
    except (ValueError, TypeError):
        return None
    if i8.size < n * 2:
        return None
    i8 = i8[: n * 2].reshape(-1, 2)  # (n, 2)

    pps = n / duration_ms  # peaks per millisecond
    i0 = max(0, int(math.floor(start_ms * pps)))
    i1 = min(n, int(math.ceil(end_ms * pps)))
    if i1 <= i0:
        return None
    sliced = i8[i0:i1]
    out_b64 = base64.b64encode(sliced.tobytes()).decode("ascii")
    actual_start = int(round(i0 / pps))
    actual_end = int(round(i1 / pps))
    if actual_end <= actual_start:
        return None
    return out_b64, bps, actual_start, actual_end


def audio_url_by_chapter(reciter: str) -> dict[int, str]:
    """Map ``chapter -> URL`` from the bucket audio_manifest sidecar.

    Fallback for ops whose snapshots lack a stamped ``audio_url``; the manifest
    is cached in ``audio_meta`` after first read.
    """
    from services.audio.audio_meta import chapter_urls
    out: dict[int, str] = {}
    for key, url in chapter_urls(reciter).items():
        if ":" in str(key):  # by_ayah keys ("<surah>:<ayah>") — skip
            continue
        try:
            out[int(key)] = url
        except (TypeError, ValueError):
            continue
    return out


def build_op_records(
    reciter: str,
    ops: Iterable[dict],
    by_chapter: dict[int, str],
    default_chapter: int | None = None,
) -> list[dict]:
    """Build canonical history-peaks records for every op with sliceable peaks.

    Skips (silently, with a debug log) ops missing op_id / range / url, or
    whose chapter peaks aren't baked — those are filled lazily on play. Never
    raises; callers treat peaks as best-effort.
    """
    out: list[dict] = []
    for op in ops or []:
        if not isinstance(op, dict):
            continue
        op_id = op.get("op_id")
        if not isinstance(op_id, str) or not op_id:
            continue
        rng = op_time_range(op)
        if rng is None:
            continue
        url = resolve_op_url(op, by_chapter, default_chapter)
        if not url:
            log.debug("[%s] op %s: no resolvable audio_url", reciter, op_id)
            continue
        sliced = slice_chapter_peaks_b64(reciter, url, rng[0], rng[1])
        if sliced is None:
            log.debug("[%s] op %s: no baked chapter peaks to slice", reciter, op_id)
            continue
        peaks_b64, bps, start_ms, end_ms = sliced
        out.append({
            "op_id": op_id,
            "url": normalize_audio_url(url),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "bps": bps,
            "peaks_b64": peaks_b64,
        })
    return out
