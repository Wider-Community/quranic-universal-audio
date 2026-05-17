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

from services.storage import cache, data_dir

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
    """Return an error string if ``rec`` is malformed, else None.

    Migration #5 canonical shape: ``{op_id, url, start_ms, end_ms, bps,
    peaks_b64}``. The pre-#5 ``peaks: list[list[float]]`` shape is no
    longer accepted; existing bucket records were re-encoded via
    ``migrate_wip5_in_place.py``. See
    ``scripts/lib/schemas/peaks_history.py`` for the canonical contract.
    """
    op_id = rec.get("op_id")
    if not isinstance(op_id, str) or not op_id:
        return "missing/invalid op_id"
    url = rec.get("url")
    if not isinstance(url, str) or not url:
        return "missing/invalid url"
    for k in ("start_ms", "end_ms"):
        v = rec.get(k)
        if not isinstance(v, int) or v < 0:
            return f"missing/invalid {k}"
    if rec["end_ms"] <= rec["start_ms"]:
        return "end_ms must be > start_ms"
    peaks_b64 = rec.get("peaks_b64")
    if not isinstance(peaks_b64, str) or not peaks_b64:
        return "missing/invalid peaks_b64"
    if not isinstance(rec.get("bps"), int) or rec["bps"] < 1:
        return "peaks_b64 requires bps density tag"
    return None


def append_peaks_records(
    reciter: str,
    records: list[dict],
    batch_id: str | None = None,
) -> int:
    """Append per-op peak records for *reciter*. Returns count written.

    Migration #5 canonical shape: ``{op_id, url, start_ms, end_ms, bps,
    peaks_b64}``. Callers must provide the int8-b64 encoded peaks; legacy
    ``peaks: list[list[float]]`` inputs are rejected by ``_validate_record``.
    See ``inspector/scripts/backfill_pipeline_peaks.py`` (one-shot CLI)
    for the encoder + per-op compute path; pre-existing bucket records
    were migrated by ``.local/extraction/scripts/migrate_wip5_in_place.py``.

    Malformed records are skipped silently — partial persistence is fine
    because consumers fall through to lazy compute-on-play.
    """
    if not records:
        return 0

    written = 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        line: dict = {
            "op_id": rec.get("op_id"),
            "url": normalize_audio_url(rec.get("url", "")),
            "start_ms": rec.get("start_ms"),
            "end_ms": rec.get("end_ms"),
            "bps": rec.get("bps"),
            "peaks_b64": rec.get("peaks_b64"),
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


_PEAKS_INT8_SCALE = 127


def _inflate_peaks_b64(rec: dict) -> dict:
    """Inflate a canonical record (``peaks_b64`` + ``bps``) into the
    ``peaks: list[list[float]]`` shape FE consumers expect.

    Returns a shallow copy with the ``peaks`` field added. On decode
    failure (corrupt b64, odd byte count) returns the input untouched so
    a single bad record doesn't sink the whole response — but the schema
    validator should have caught any malformed input upstream.
    """
    b64 = rec.get("peaks_b64")
    if not isinstance(b64, str) or not b64:
        return rec
    try:
        import base64
        raw = base64.b64decode(b64)
        import numpy as np  # noqa: PLC0415
        i8 = np.frombuffer(raw, dtype=np.int8)
        if i8.size == 0 or i8.size % 2 != 0:
            return rec
        peaks_f = (i8.astype(np.float32) / _PEAKS_INT8_SCALE).reshape(-1, 2)
        out = dict(rec)
        out["peaks"] = peaks_f.tolist()
        return out
    except Exception:  # noqa: BLE001
        return rec


def load_peaks_records(
    reciter: str,
    exclude_op_ids: set[str] | None = None,
) -> list[dict]:
    """Read the peaks JSONL for *reciter*. Returns ``[]`` if missing.

    Silently skips malformed records, mirroring
    ``services.history_query.parse_history_file``.

    Migration #5: records written by the offline pipeline now carry
    ``peaks_b64`` + ``bps`` instead of ``peaks: list[list[float]]``.
    Inflate at read time so the FE wire shape (and the in-memory
    ``peaks`` list) is stable across the transition.
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
        out.append(_inflate_peaks_b64(rec))
    if not excluded:
        cache.set_seg_history_peaks(reciter, out)
    return out
