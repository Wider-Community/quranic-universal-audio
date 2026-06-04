"""Shared fixtures + builders for the qua_shared timestamps test suite.

Hosts the synthetic MFA result builder (`_ok`), the two-occurrence loopback
chapter+results pair, and the canonical `PROVENANCE` metadata block used by
`test_timestamps_reshape.py`, `test_timestamps_segment_shards.py`, and
`test_timestamps_dedup.py`. Promoted here so writer + reshape + dedup faces
land on the same inputs.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_INSPECTOR = _ROOT / "inspector"
for _p in (_ROOT, _INSPECTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


PROVENANCE = {
    "created_at": "2026-06-04T00:00:00Z",
    "audio_source": "by_surah",
    "aligner_model": "quran_aligner_model",
    "method": "kalpy",
    "beam": 50,
    "shared_cmvn": False,
    "padding": "forward",
}


def _ok(locations, t0=0.0, step=0.5):
    """Synthetic MFA 'ok' result: one word per location, sequential times (s).

    Letters/phones use MFA's raw dict shape (``_convert_word`` compacts them
    to ``[char, s, e]`` / ``[phone, s, e]`` arrays in the canonical writer).
    """
    words = []
    for i, loc in enumerate(locations):
        s = t0 + i * step
        words.append({
            "location": loc, "start": s, "end": s + step,
            "letters": [{"char": "x", "start": s, "end": s + step}],
            "phones": [{"phone": "P", "start": s, "end": s + step}],
        })
    return {"status": "ok", "words": words}


def _multi_verse_loopback():
    """Synthetic chapter doc carrying 1:1 across two takes (words 1-2, then 3-4), then 1:2."""
    return {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:1:2", "time_start": 0, "time_end": 1000},
            {"matched_ref": "1:1:3-1:1:4", "time_start": 1500, "time_end": 2500},
            {"matched_ref": "1:2:1-1:2:3", "time_start": 2500, "time_end": 3500},
        ],
    }


def _multi_verse_loopback_results():
    """Companion MFA results for `_multi_verse_loopback`."""
    return {0: [
        (0, _ok(["1:1:1", "1:1:2"])),
        (1, _ok(["1:1:3", "1:1:4"], t0=1.5)),
        (2, _ok(["1:2:1", "1:2:2", "1:2:3"], t0=2.5)),
    ]}
