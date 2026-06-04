"""Cross-file boundary check between timestamps and segments.

Compares MFA word-level timestamps against segment boundaries to flag verses
where the timestamps are narrower than the segments — a sign that MFA stopped
short of the speech edge.

Pure function — no I/O side effects beyond reading ``segments.json`` from disk.
Used by:
  - inspector/services/validation/timestamps.py (runtime check on Inspector data).
  - .github/scripts/build_reciter.py --build-manifest (build-time pre-compute
    so the deployed Inspector can render the validation panel without a live
    segments.json fetch).
"""

from __future__ import annotations

import json
from pathlib import Path


def _ms_to_hms(ms: float) -> str:
    """Format ms as ``[h:]m:ss.s`` for human-readable mismatch messages."""
    total_s = ms / 1000.0
    h = int(total_s // 3600)
    m = int((total_s % 3600) // 60)
    s = total_s % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:04.1f}"
    return f"{m}:{s:04.1f}"


def _parse_segments(path: Path) -> tuple[dict[str, list[list]], dict]:
    """Parse ``segments.json`` → ``(verses_dict, meta_dict)``."""
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.pop("_meta", {})
    return doc, meta


def compute_boundary_mismatches(
    ts_verses: dict[str, list[list]],
    seg_path: Path,
    *,
    default_tolerance_ms: int = 500,
) -> dict:
    """Compare timestamp boundaries against segment boundaries per verse.

    Args:
      ts_verses: ``{verse_key: [[idx, start_ms, end_ms, ...], ...]}`` from
        ``parse_timestamps`` / ``parse_timestamps_full``. Letters/phones
        beyond index 2 are ignored.
      seg_path: path to ``segments.json``. Returns an empty result if it
        doesn't exist (the validator falls through to other categories).
      default_tolerance_ms: tolerance fallback when ``segments._meta.pad_ms``
        is missing or zero. Tolerance is otherwise ``3 * pad_ms`` to absorb
        normal MFA undershoot at speech edges.

    Returns dict with:
      - ``has_segments``: bool — whether ``seg_path`` was readable.
      - ``tolerance_ms``: int — applied tolerance.
      - ``pad_ms``: int — segments' configured pad (0 if unknown).
      - ``mismatches``: list[dict] — ``{verse_key, side, diff_ms, msg}`` for
        every flagged boundary. ``side`` is ``"start"`` or ``"end"``.

    Only flags **directional** mismatches: timestamps narrower than
    segments. Timestamps extending beyond segments is expected (cross-verse
    word bleed) and isn't reported.
    """
    if not seg_path.exists():
        return {
            "has_segments": False,
            "tolerance_ms": default_tolerance_ms,
            "pad_ms": 0,
            "mismatches": [],
        }

    seg_verses, seg_meta = _parse_segments(seg_path)
    pad_ms = int(seg_meta.get("pad_ms", 0) or 0)
    tolerance = 3 * pad_ms if pad_ms > 0 else default_tolerance_ms

    mismatches: list[dict] = []
    for verse_key, ts_words in ts_verses.items():
        if verse_key not in seg_verses:
            continue
        segs = seg_verses[verse_key]
        if not ts_words or not segs:
            continue
        ts_first_start = ts_words[0][1]
        ts_last_end = ts_words[-1][2]

        # Repeated verses: pick the segment whose boundary is closest to
        # this timestamp range, not segs[0]/segs[-1] (which would compare
        # against the wrong occurrence).
        best_start_seg = min(segs, key=lambda s: abs(s[2] - ts_first_start))
        best_end_seg = min(segs, key=lambda s: abs(s[3] - ts_last_end))

        # Start: flag only if timestamps start AFTER segment start (late).
        start_diff = ts_first_start - best_start_seg[2]
        if start_diff > tolerance:
            mismatches.append(
                {
                    "verse_key": verse_key,
                    "side": "start",
                    "diff_ms": int(start_diff),
                    "msg": (
                        f"start mismatch: timestamps {_ms_to_hms(ts_first_start)} "
                        f"vs segments {_ms_to_hms(best_start_seg[2])} "
                        f"(diff {start_diff}ms)"
                    ),
                }
            )

        # End: flag only if timestamps end BEFORE segment end (short).
        end_diff = best_end_seg[3] - ts_last_end
        if end_diff > tolerance:
            mismatches.append(
                {
                    "verse_key": verse_key,
                    "side": "end",
                    "diff_ms": int(end_diff),
                    "msg": (
                        f"end mismatch: timestamps {_ms_to_hms(ts_last_end)} "
                        f"vs segments {_ms_to_hms(best_end_seg[3])} "
                        f"(diff {end_diff}ms)"
                    ),
                }
            )

    return {
        "has_segments": True,
        "tolerance_ms": tolerance,
        "pad_ms": pad_ms,
        "mismatches": mismatches,
    }
