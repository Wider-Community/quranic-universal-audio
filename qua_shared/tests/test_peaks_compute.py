"""Drift guard: the job's vendored peaks packing must stay byte-identical to
the canonical inspector implementation.

``qua_shared/peaks_compute.py`` re-homes ``compute_audio_peaks`` + ``pack_slim``
without the ``config`` import so the HF Job (which ships only ``scripts/``) can
generate v3 peaks. If the canonical ``inspector/services/audio/peaks_slim.py``
shape ever changes, this test fails — keep them in lockstep.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_INSPECTOR = _ROOT / "inspector"
for p in (_ROOT, _INSPECTOR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from qua_shared import peaks_compute  # noqa: E402
from services.audio import peaks_slim  # noqa: E402


def _hd_doc():
    # 600 HD min/max pairs (30 bps × 20s), deterministic.
    peaks = [[round(-((i % 50) / 50.0), 4), round(((i % 37) / 37.0), 4)]
             for i in range(600)]
    return {"schema_version": 2, "duration_ms": 20000, "peaks": peaks}


def test_pack_parity():
    hd = _hd_doc()
    assert peaks_compute.pack_slim(hd) == peaks_slim.pack_slim(hd), (
        "vendored pack_slim drifted from inspector peaks_slim.pack_slim"
    )


def test_pack_unpacks_via_inspector():
    blob = peaks_compute.pack_slim(_hd_doc())
    out = peaks_slim.unpack_slim(blob)
    assert out is not None
    assert out["schema_version"] == 3 and out["bps"] == 10 and out["peaks"]


def test_constants_match_config():
    # Guard the inlined constants against config drift.
    from config import (MIN_FULL_PEAK_BUCKETS, PEAKS_BUCKETS_PER_SEC,
                        PEAKS_FFMPEG_SAMPLE_RATE, PEAKS_PCM_NORMALIZER)
    assert peaks_compute.PEAKS_FFMPEG_SAMPLE_RATE == PEAKS_FFMPEG_SAMPLE_RATE
    assert peaks_compute.PEAKS_BUCKETS_PER_SEC == PEAKS_BUCKETS_PER_SEC
    assert peaks_compute.MIN_FULL_PEAK_BUCKETS == MIN_FULL_PEAK_BUCKETS
    assert peaks_compute.PEAKS_PCM_NORMALIZER == PEAKS_PCM_NORMALIZER
    assert peaks_compute.PEAKS_SLIM_BPS == peaks_slim.PEAKS_SLIM_BPS
    assert peaks_compute.SLIM_SCHEMA_VERSION == peaks_slim.SLIM_SCHEMA_VERSION
