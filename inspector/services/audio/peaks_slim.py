"""Slim chapter-overview peaks — canonical on-bucket format (schema_version 3).

Packed representation: int8-quantized peaks at ``PEAKS_SLIM_BPS`` density,
JSON-wrapped with base64-encoded payload, gzipped. Single canonical file at
``reciters/<slug>/peaks/<chapter>.json.gz`` -- replaces the v2 verbose float-JSON
which weighed ~95 MiB per reciter (~14 MiB for a 3-hour chapter) and parsed
in ~400 ms on the FE.

Why this shape:

- **Decimate 30→10 bps**: chapter overview canvas is at most ~1100 px wide;
  even a 3-hour chapter at 10 bps oversamples by 100× for that target. The
  resolution loss is invisible at overview scale. Per-segment zoom (rendered
  by ``_slice_chapter_peaks``) sees chunkier waveforms at the smallest seg
  durations -- accepted trade-off, see docs/peaks_density_viz.html.
- **int8 quantization**: peaks are floats in [-1, 1]; quantize to [-127, 127]
  and pack as one byte per min/max. Float JSON strings averaged ~6 bytes per
  peak; int8 b64 averages ~1.33 bytes per peak. ~14× wire reduction.
- **gzip**: peak streams have high redundancy; gzip-6 hits ~10× compression on
  the packed payload with negligible (<50 ms) encode cost per chapter.
  Brotli's marginal wire savings did not justify ~5× encode cost.

Writers (do NOT duplicate the pack logic anywhere else):

- ``.local/extraction/segments/audio_persist.py`` -- runs on Katana, the only
  runtime-relevant writer.
- One-shot bucket CLIs: ``scripts/backfill_peaks_slim.py``,
  ``scripts/convert_peaks_v2_to_v3.py``. The runtime never writes peaks.

Reader: ``inspector/services/audio/audio_fetch.py::read_prefetched_peaks``.

See also: ``inspector/.claude/skills/inspector-audio/references/peaks.md``.
"""
from __future__ import annotations

import base64
import gzip
import json
from typing import TypedDict

import numpy as np

# Target density for the slim chapter overview. Decided by the resolution
# benchmark in docs/peaks_density_viz.html. Do NOT confuse with
# ``PEAKS_BUCKETS_PER_SEC`` (30) which is the HD density used by
# ``compute_audio_peaks`` and ``compute_segment_peaks`` -- those stay at 30.
PEAKS_SLIM_BPS = 10

# Pre-v3 files (v1 / v2 float-JSON) are treated as cache misses by
# ``is_current_schema`` and re-packed by ``scripts/backfill_peaks_slim.py``,
# which leaves ``.bak`` originals alongside the new ``.json.gz``.
SLIM_SCHEMA_VERSION = 3

# int8 normalizer -- peaks coming out of ``compute_audio_peaks`` are floats in
# [-1, 1]; clip and scale to the int8 range. Symmetric quantization (no zero
# shift) keeps the inverse trivially ``v / 127``.
_INT8_SCALE = 127


class SlimPeaksDoc(TypedDict):
    """Wire shape stored at ``reciters/<slug>/peaks/<chapter>.json.gz`` (gzipped)."""

    schema_version: int
    duration_ms: int
    q: str           # quantization tag -- "int8" today, reserved for future ("int16" etc.)
    bps: int         # buckets per second after decimation
    n: int           # number of [min, max] pairs encoded in peaks_b64
    peaks_b64: str   # base64 of n*2 int8s, alternating (min, max)


def _decimate(peaks: np.ndarray, src_bps: int, dst_bps: int) -> np.ndarray:
    """Reduce density by min-of-mins / max-of-maxes over windows of ``factor``.

    Preserves visual envelope — every input min/max contributes to its output
    bucket, so loud transients stay loud. Handles a non-divisible tail by
    folding it into a final bucket (cheap; one extra peak at most).
    """
    if dst_bps >= src_bps:
        return peaks
    factor = src_bps // dst_bps
    n_full = (len(peaks) // factor) * factor
    if n_full == 0:
        return peaks[:0]
    trimmed = peaks[:n_full].reshape(-1, factor, 2)
    mn = trimmed[:, :, 0].min(axis=1)
    mx = trimmed[:, :, 1].max(axis=1)
    tail = peaks[n_full:]
    if len(tail):
        mn = np.concatenate([mn, [tail[:, 0].min()]])
        mx = np.concatenate([mx, [tail[:, 1].max()]])
    return np.stack([mn, mx], axis=1)


def pack_slim(hd_doc: dict, target_bps: int = PEAKS_SLIM_BPS) -> bytes:
    """Pack an HD ``compute_audio_peaks`` output into the canonical gzip blob.

    Input shape: ``{"schema_version": 2, "duration_ms": int, "peaks": [[mn, mx], ...]}``
    at ``PEAKS_BUCKETS_PER_SEC`` density. Output is the bytes that go on the
    bucket -- one gzip member containing one JSON document.

    Concatenating multiple ``pack_slim`` outputs is valid gzip (RFC 1952) and
    is what the ``/api/seg/peaks`` route streams back to the FE.
    """
    if not isinstance(hd_doc, dict) or "peaks" not in hd_doc or "duration_ms" not in hd_doc:
        raise ValueError("pack_slim: expected dict with 'peaks' and 'duration_ms'")
    arr = np.asarray(hd_doc["peaks"], dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(f"pack_slim: expected peaks shape (N, 2), got {arr.shape}")
    arr = _decimate(arr, src_bps=30, dst_bps=target_bps)
    i8 = np.clip(np.round(arr * _INT8_SCALE), -_INT8_SCALE, _INT8_SCALE).astype(np.int8)
    doc: SlimPeaksDoc = {
        "schema_version": SLIM_SCHEMA_VERSION,
        "duration_ms": int(hd_doc["duration_ms"]),
        "q": "int8",
        "bps": target_bps,
        "n": int(i8.shape[0]),
        "peaks_b64": base64.b64encode(i8.tobytes()).decode("ascii"),
    }
    # mtime=0 keeps the gzip member byte-identical for the same input so the
    # CDN / browser cache key is stable across re-bakes that didn't change
    # the payload.
    return gzip.compress(
        json.dumps(doc, separators=(",", ":")).encode("utf-8"),
        compresslevel=6,
        mtime=0,
    )


def unpack_slim(blob: bytes) -> dict | None:
    """Inverse of ``pack_slim``. Returns the v3 dict with ``peaks`` as a plain
    ``list[list[float]]`` so existing slicers (``_slice_chapter_peaks``,
    ``write_edit_history_peaks``) work without shape changes.

    Returns ``None`` on any decode failure (corrupt file, wrong magic, bad
    base64) -- caller treats it as a cache miss exactly like the v1/v2
    invalidation path.
    """
    try:
        raw = gzip.decompress(blob)
        doc = json.loads(raw)
        if not isinstance(doc, dict) or doc.get("schema_version") != SLIM_SCHEMA_VERSION:
            return None
        if doc.get("q") != "int8":
            return None
        bin_ = base64.b64decode(doc["peaks_b64"])
        n = int(doc["n"])
        if len(bin_) != n * 2:
            return None
        i8 = np.frombuffer(bin_, dtype=np.int8).reshape(-1, 2)
        peaks = (i8.astype(np.float32) / _INT8_SCALE).tolist()
        return {
            "schema_version": SLIM_SCHEMA_VERSION,
            "duration_ms": int(doc["duration_ms"]),
            "bps": int(doc["bps"]),
            "peaks": peaks,
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def unpack_slim_envelope(blob: bytes) -> dict | None:
    """Inverse of :func:`pack_slim` that **skips dequant** — returns the slim
    envelope verbatim as ``{schema_version, duration_ms, q:'int8', bps, n,
    peaks_b64}``. This is the runtime reader for the FE-facing peaks route:
    the browser inflates b64 → ``Int8Array`` once on receive and the drawer
    consumes the typed array directly (see ``peaks-view.ts`` and
    ``the inspector-audio skill``).

    Validates the same envelope shape as :func:`unpack_slim` (schema_version,
    quantization tag, payload length) but skips the int8 → float32 →
    ``.tolist()`` step that the offline extraction's history-JSONL writer
    still uses. On a husary-ch2-sized chapter that loop alone costs ~5 ms
    server-side and allocates ~3 MB of float-list objects per request.

    Returns ``None`` on any decode failure (same contract as :func:`unpack_slim`).
    """
    try:
        raw = gzip.decompress(blob)
        doc = json.loads(raw)
        if not isinstance(doc, dict) or doc.get("schema_version") != SLIM_SCHEMA_VERSION:
            return None
        if doc.get("q") != "int8":
            return None
        n = int(doc["n"])
        # Cheap envelope sanity check: peaks_b64 byte length after decode
        # MUST equal n * 2 (one int8 each for min, max). Verifies the file
        # isn't truncated without paying the full decode.
        b64_len = len(doc["peaks_b64"])
        # base64 byte count: ceil(decoded / 3) * 4. Reverse: decoded = (b64_len * 3) // 4
        # (assumes proper padding, which we control on the writer side).
        decoded_len = (b64_len * 3) // 4
        if decoded_len < n * 2:
            return None
        return {
            "schema_version": SLIM_SCHEMA_VERSION,
            "duration_ms": int(doc["duration_ms"]),
            "bps": int(doc["bps"]),
            "q": "int8",
            "n": n,
            "peaks_b64": doc["peaks_b64"],
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
