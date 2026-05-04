"""Statistics computation: histograms, percentiles, segmentation stats.

No Flask imports -- all functions accept parameters and return plain dicts.
"""

import statistics as _statistics

from config import (
    CONF_HIST_BIN_SIZE,
    PAUSE_HIST_BIN_MS,
    PAUSE_HIST_MAX_MS,
    SEG_DUR_HIST_BIN_MS,
    SEG_DUR_HIST_MAX_MS,
    SEGS_PER_VERSE_HIST_MAX,
    WORDS_PER_SEG_HIST_MAX,
)
from services import cache
from services.data_loader import load_detailed, load_seg_verses


def histogram(values: list, bin_size: float, lo: float, hi: float, *, cap: bool = True) -> dict:
    """Build a histogram with fixed bin edges.

    When *cap* is True (default), values >= hi are clamped into the last bin.
    When *cap* is False, the upper bound is extended to cover the actual data
    range so no values are clamped.

    Returns ``{"bins": [...], "counts": [...]}``.
    """
    if not cap and values:
        actual_max = max(values)
        if actual_max > hi:
            import math
            hi = math.ceil(actual_max / bin_size) * bin_size + bin_size
    n_bins = int((hi - lo) / bin_size)
    counts = [0] * (n_bins + 1)  # +1 for overflow bin
    bins = [lo + i * bin_size for i in range(n_bins)] + [hi]
    for v in values:
        idx = int((v - lo) / bin_size)
        if idx < 0:
            idx = 0
        elif idx >= len(counts):
            idx = len(counts) - 1
        counts[idx] += 1
    return {"bins": bins, "counts": counts}


def percentile(sorted_values: list, pct: float) -> float:
    """Return the *pct*-th percentile from an already-sorted list."""
    if not sorted_values:
        return 0
    k = (len(sorted_values) - 1) * pct / 100
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_values) else f
    return round(sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f]), 1)


def compute_stats(reciter: str) -> dict | None:
    """Compute segmentation statistics and histogram distributions.

    Returns a dict suitable for ``jsonify()`` or ``None`` if reciter not found.
    """
    verses, pad_ms = load_seg_verses(reciter)
    if not verses:
        return None

    seg_durations = []
    pause_durations = []
    words_per_seg = []
    segs_per_verse = {}

    for verse_key, segs in verses.items():
        is_cross = "-" in verse_key
        if not is_cross:
            segs_per_verse[verse_key] = len(segs)

        for idx, seg in enumerate(segs):
            if len(seg) < 4:
                continue
            w_from, w_to, t_from, t_to = seg[0], seg[1], seg[2], seg[3]
            seg_durations.append(t_to - t_from)
            words_per_seg.append(w_to - w_from + 1)

    # Compute pauses from detailed.json
    entries = load_detailed(reciter)
    meta = cache.get_seg_meta(reciter)
    for entry in entries:
        entry_segs = entry.get("segments", [])
        for i in range(len(entry_segs) - 1):
            t_to = entry_segs[i].get("time_end", 0)
            next_t_from = entry_segs[i + 1].get("time_start", 0)
            if next_t_from > t_to:
                true_pause = (next_t_from - t_to) + 2 * pad_ms
                pause_durations.append(true_pause)

    spv_values = list(segs_per_verse.values())

    # Confidence from detailed.json
    confidences = []
    for entry in entries:
        for seg in entry.get("segments", []):
            conf = seg.get("confidence", 0.0)
            if seg.get("matched_ref"):
                confidences.append(round(conf * 100, 1))

    total_segments = len(seg_durations)
    total_verses = len(spv_values)
    single_word = sum(1 for w in words_per_seg if w == 1)
    multi_seg = sum(1 for v in spv_values if v > 1)

    summary = {
        "total_segments": total_segments,
        "total_verses": total_verses,
        "single_word_segs": single_word,
        "single_word_pct": round(single_word / total_segments * 100, 1) if total_segments else 0,
        "multi_seg_verses": multi_seg,
        "multi_seg_pct": round(multi_seg / total_verses * 100, 1) if total_verses else 0,
        "segs_per_verse_mean": round(_statistics.mean(spv_values), 2) if spv_values else 0,
        "segs_per_verse_max": max(spv_values) if spv_values else 0,
        "seg_dur_median_ms": round(_statistics.median(seg_durations)) if seg_durations else 0,
        "pause_dur_median_ms": round(_statistics.median(pause_durations)) if pause_durations else 0,
    }

    distributions = {
        "pause_duration_ms": histogram(pause_durations, PAUSE_HIST_BIN_MS, 0, PAUSE_HIST_MAX_MS),
        "seg_duration_ms": histogram(seg_durations, SEG_DUR_HIST_BIN_MS, 0, SEG_DUR_HIST_MAX_MS, cap=False),
        "words_per_seg": histogram(words_per_seg, 1, 1, WORDS_PER_SEG_HIST_MAX, cap=False),
        "segs_per_verse": histogram(spv_values, 1, 1, SEGS_PER_VERSE_HIST_MAX),
        "confidence": histogram(confidences, CONF_HIST_BIN_SIZE, 0, 100),
    }

    for key, values in [
        ("pause_duration_ms", pause_durations),
        ("seg_duration_ms", seg_durations),
        ("words_per_seg", words_per_seg),
        ("confidence", confidences),
    ]:
        if values and key in distributions:
            sv = sorted(values)
            distributions[key]["percentiles"] = {
                "p25": percentile(sv, 25),
                "p50": percentile(sv, 50),
                "p75": percentile(sv, 75),
            }

    vad_params = {
        "min_silence_ms": meta.get("min_silence_ms", 0),
        "min_speech_ms": meta.get("min_speech_ms", 0),
        "pad_ms": pad_ms,
    }

    return {
        "vad_params": vad_params,
        "summary": summary,
        "distributions": distributions,
    }
