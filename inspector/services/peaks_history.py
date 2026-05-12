"""Persistence for waveform peaks tied to history ops.

Per-op JSONL at ``<bucket>/<kind>/<reciter>/edit_history_peaks.jsonl``,
append-only. Lets the History panel render waveforms across sessions
without re-computing — and survives full-audio download/delete switching
since this file lives in the data tree, not the audio cache.

Schema (one record per line)::

    {
      "op_id": "<uuid>",
      "batch_id": "<uuid>" | null,
      "url": "<canonical url, proxy-stripped>",
      "start_ms": int,
      "end_ms": int,
      "peaks": [[min, max], ...],
      "duration_ms": int,
      "saved_at_utc": "<iso>"
    }

Same op_id may appear on multiple lines when peaks are persisted lazily for
different ranges (e.g. on play after a save where peaks weren't ready).
Consumers index by ``url`` and use covering-range matching, so duplicates are
benign.
"""

import re
from datetime import datetime, timezone
from urllib.parse import unquote

from services import cache, data_dir

_PROXY_RE = re.compile(r"/api/seg/audio-proxy/[^?]+\?url=(.+)")


def normalize_audio_url(url: str) -> str:
    """Strip the audio-proxy wrapper so proxy and direct URLs share a key.

    Mirrors ``frontend/src/lib/utils/waveform-cache.ts::normalizeAudioUrl``.
    """
    if not url:
        return url
    m = _PROXY_RE.search(url)
    return unquote(m.group(1)) if m else url


def _validate_record(rec: dict) -> str | None:
    """Return an error string if ``rec`` is malformed, else None."""
    op_id = rec.get("op_id")
    if not isinstance(op_id, str) or not op_id:
        return "missing/invalid op_id"
    url = rec.get("url")
    if not isinstance(url, str) or not url:
        return "missing/invalid url"
    for k in ("start_ms", "end_ms", "duration_ms"):
        v = rec.get(k)
        if not isinstance(v, int) or v < 0:
            return f"missing/invalid {k}"
    if rec["end_ms"] <= rec["start_ms"]:
        return "end_ms must be > start_ms"
    peaks = rec.get("peaks")
    if not isinstance(peaks, list) or not peaks:
        return "missing/invalid peaks"
    return None


def append_peaks_records(
    reciter: str,
    records: list[dict],
    batch_id: str | None = None,
) -> int:
    """Append per-op peak records for *reciter*. Returns count written.

    Each record must carry ``op_id``, ``url``, ``start_ms``, ``end_ms``,
    ``peaks``, ``duration_ms``. ``url`` is normalized (proxy stripped) and
    ``batch_id`` / ``saved_at_utc`` are stamped on each line.
    Malformed records are skipped silently — partial persistence is fine
    because consumers fall through to compute-on-play.
    """
    if not records:
        return 0
    now = datetime.now(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")

    written = 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        line = {
            "op_id": rec.get("op_id"),
            "batch_id": batch_id if rec.get("batch_id") is None else rec.get("batch_id"),
            "url": normalize_audio_url(rec.get("url", "")),
            "start_ms": rec.get("start_ms"),
            "end_ms": rec.get("end_ms"),
            "peaks": rec.get("peaks"),
            "duration_ms": rec.get("duration_ms"),
            "saved_at_utc": now,
        }
        err = _validate_record(line)
        if err:
            continue
        data_dir.append_peaks_history(reciter, line)
        cached = cache.get_seg_history_peaks(reciter)
        if cached is not None:
            cached.append(line)
        written += 1
    return written


def load_peaks_records(
    reciter: str,
    exclude_op_ids: set[str] | None = None,
) -> list[dict]:
    """Read the peaks JSONL for *reciter*. Returns ``[]`` if missing.

    Silently skips malformed records, mirroring
    ``services.history_query.parse_history_file``.
    """
    excluded = exclude_op_ids or set()
    out: list[dict] = []
    cached = cache.get_seg_history_peaks(reciter)
    if cached is not None and not excluded:
        return cached

    for rec in data_dir.iter_peaks_history(reciter):
        if not isinstance(rec, dict):
            continue
        if rec.get("op_id") in excluded:
            continue
        out.append(rec)
    if not excluded:
        cache.set_seg_history_peaks(reciter, out)
    return out
