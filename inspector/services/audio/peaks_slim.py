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

from qua_shared.audio.peaks import PEAKS_SLIM_BPS  # noqa: F401 — re-export
from qua_shared.audio.peaks import decimate as _shared_decimate
from qua_shared.audio.peaks import pack_slim as _shared_pack_slim

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
    q: str  # quantization tag -- "int8" today, reserved for future ("int16" etc.)
    bps: int  # buckets per second after decimation
    n: int  # number of [min, max] pairs encoded in peaks_b64
    peaks_b64: str  # base64 of n*2 int8s, alternating (min, max)


# ``pack_slim`` / ``decimate`` live in ``qua_shared.audio.peaks`` so the acquire
# HF Job bakes byte-identical blobs; re-exported here for the app's callers.
_decimate = _shared_decimate
pack_slim = _shared_pack_slim


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
