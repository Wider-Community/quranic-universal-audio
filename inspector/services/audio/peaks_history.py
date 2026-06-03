"""Persistence for waveform peaks tied to history ops.

Per-op JSONL at ``<bucket>/reciters/<reciter>/edit_history_peaks.jsonl``,
append-only. Lets the History panel render waveforms across sessions
without re-computing; this root-level file is never GC'd, so anonymous
viewers of a released reciter still get instant waveforms.

Migration #5 canonical shape (one record per line)::

    {
      "op_id": "<uuid>",
      "url": "<canonical url, proxy-stripped>",
      "start_ms": int,
      "end_ms": int,
      "bps": int,            # buckets-per-second density (10 today)
      "peaks_b64": "<base64 of n*2 int8s>"
    }

The pre-#5 verbose shape (``peaks: list[list[float]]`` + ``batch_id`` /
``duration_ms`` / ``saved_at_utc``) is rejected by ``_validate_record``;
existing bucket files were re-encoded by ``migrate_wip5_in_place.py``. See
``qua_shared/schemas/peaks_history.py`` for the authoritative contract.

Writers: ``services/segments/save.py`` (runtime, slices baked chapter peaks
via ``op_peaks.build_op_records``), the History on-play write-back POST, the
offline pipeline (``write_edit_history_peaks``), and the
``backfill_pipeline_peaks.py`` CLI. ``append_peaks_records`` dedups by
``op_id`` so concurrent / repeat writers append at most one record per op.

Readers index by ``url`` + covering-range, so a record covering a row's span
renders it regardless of which op produced it (waveform for a URL+range is
identical) — making dedup-by-op_id safe.
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
    ``qua_shared/schemas/peaks_history.py`` for the canonical contract.
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

    **Dedup-by-op_id:** an op already persisted is skipped (no bucket write) —
    bounds the file to one record per op and means concurrent / repeat writers
    (autosave re-saves, multiple anonymous viewers playing the same op) append
    at most once. ``batch_id`` is accepted for caller compatibility but not
    part of the canonical record.

    Malformed records are skipped silently — partial persistence is fine
    because consumers fall through to lazy compute-on-play.
    """
    if not records:
        return 0

    # Build the seen-op_id set once (warms the in-memory list cache). Dedup
    # against both already-persisted ops and earlier records in this same call.
    seen: set[str] = {
        rec.get("op_id")
        for rec in load_peaks_records(reciter)
        if isinstance(rec.get("op_id"), str)
    }

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
        if line["op_id"] in seen:
            continue  # already persisted — no bucket write
        data_dir.append_peaks_history(reciter, line)
        cached = cache.get_seg_history_peaks(reciter)
        if cached is not None:
            cached.append(line)
        seen.add(line["op_id"])
        written += 1

    if written:
        # The serialized GET response is now stale.
        cache.pop_seg_history_peaks_response(reciter)
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
    inflate: bool = False,
) -> list[dict]:
    """Read the peaks JSONL for *reciter*. Returns ``[]`` if missing.

    Silently skips malformed records, mirroring
    ``services.history_query.parse_history_file``.

    The in-memory cache holds the **canonical** ``peaks_b64`` records (matching
    what ``append_peaks_records`` appends, so the two never drift). The
    FE-facing GET serves these verbatim and decodes b64 client-side. Pass
    ``inflate=True`` to get the legacy ``peaks: list[list[float]]`` shape (for
    any float consumer / tests) — applied after the cache read so the cache
    stays canonical.
    """
    excluded = exclude_op_ids or set()
    cached = cache.get_seg_history_peaks(reciter)
    if cached is None:
        cached = [
            rec for rec in data_dir.iter_peaks_history(reciter)
            if isinstance(rec, dict)
        ]
        cache.set_seg_history_peaks(reciter, cached)

    out = [rec for rec in cached if rec.get("op_id") not in excluded]
    if inflate:
        out = [_inflate_peaks_b64(rec) for rec in out]
    return out
