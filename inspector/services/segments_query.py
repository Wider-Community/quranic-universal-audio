"""Query helpers for Segments-tab read-only data endpoints.

No Flask imports -- functions accept parameters and return plain dicts/lists.
Extracted from ``routes/segments_data.py`` in Wave 2b (stage2-plan.md §4) as
a pure behavior-preserving move.
"""

import statistics

from config import LOW_CONFIDENCE_RED, LOW_CONFIDENCE_THRESHOLD
from services import cache
from services.data_loader import (
    dk_text_for_ref,
    get_word_counts,
    load_detailed,
)
from utils.references import chapter_from_ref


def get_chapter_data(reciter: str, chapter: int,
                     verse_filter: str | None = None) -> dict | None:
    """Return segments, audio URL, summary, and issues for a chapter.

    Returns ``None`` if no matching entries exist for the ``(reciter, chapter)``
    pair — the caller converts to an HTTP 404. Otherwise returns the full
    response dict used by ``GET /api/seg/data/<reciter>/<chapter>``.
    """
    entries = load_detailed(reciter)
    matching = [e for e in entries if chapter_from_ref(e["ref"]) == chapter]
    if not matching:
        return None

    audio_url = matching[0].get("audio", "")

    segments = []
    idx = 0
    for entry_idx, entry in enumerate(matching):
        entry_audio = entry.get("audio", "")
        for seg in entry.get("segments", []):
            t_start = seg.get("time_start", 0)
            t_end = seg.get("time_end", 0)
            mref = seg.get("matched_ref", "")
            seg_dict = {
                "index": idx,
                "entry_idx": entry_idx,
                "time_start": t_start,
                "time_end": t_end,
                "matched_ref": mref,
                "matched_text": seg.get("matched_text", ""),
                "display_text": dk_text_for_ref(mref),
                "confidence": round(seg.get("confidence", 0.0), 4),
                "audio_url": entry_audio,
            }
            if seg.get("ignored_categories"):
                seg_dict["ignored_categories"] = seg["ignored_categories"]
            elif seg.get("ignored"):
                seg_dict["ignored_categories"] = ["_all"]
            segments.append(seg_dict)
            idx += 1

    if verse_filter:
        prefix = f"{chapter}:{verse_filter}:"
        segments = [s for s in segments if s["matched_ref"].startswith(prefix)]

    matched = [s for s in segments if s["matched_ref"]]
    failed = [s for s in segments if not s["matched_ref"]]
    confidences = [s["confidence"] for s in matched]

    speech_durations = [s["time_end"] - s["time_start"] for s in segments]
    total_speech = sum(speech_durations)
    pad_ms = cache.get_seg_meta(reciter).get("pad_ms", 0)
    silence_durations = []
    for i in range(len(segments) - 1):
        if segments[i]["entry_idx"] == segments[i + 1]["entry_idx"]:
            gap = segments[i + 1]["time_start"] - segments[i]["time_end"] + 2 * pad_ms
            if gap > 0:
                silence_durations.append(gap)
    total_silence = sum(silence_durations)

    issue_indices = []
    for s in segments:
        if not s["matched_ref"]:
            issue_indices.append(s["index"])
        elif s["confidence"] < LOW_CONFIDENCE_RED:
            issue_indices.append(s["index"])

    # Missing verses
    missing_verses = []
    wc = get_word_counts()
    expected_verses = {v for (s, v) in wc if s == chapter}
    if expected_verses:
        found_verses = set()
        for s in segments:
            ref = s["matched_ref"]
            if ref:
                parts = ref.split("-")
                if len(parts) == 2:
                    start = parts[0].split(":")
                    end = parts[1].split(":")
                    if len(start) >= 2:
                        try:
                            for v in range(int(start[1]), int(end[1]) + 1):
                                found_verses.add(v)
                        except (ValueError, IndexError):
                            pass
        missing_verses = sorted(expected_verses - found_verses)

    summary = {
        "total_segments": len(segments),
        "matched_segments": len(matched),
        "failed_segments": len(failed),
        "conf_min": round(min(confidences), 4) if confidences else 0,
        "conf_median": round(statistics.median(confidences), 4) if confidences else 0,
        "conf_mean": round(statistics.mean(confidences), 4) if confidences else 0,
        "conf_max": round(max(confidences), 4) if confidences else 0,
        "below_60": sum(1 for c in confidences if c < LOW_CONFIDENCE_RED),
        "below_80": sum(1 for c in confidences if c < LOW_CONFIDENCE_THRESHOLD),
        "total_speech_ms": round(total_speech),
        "avg_segment_ms": round(total_speech / len(segments)) if segments else 0,
        "total_silence_ms": round(total_silence),
        "avg_silence_ms": round(total_silence / len(silence_durations)) if silence_durations else 0,
        "issue_indices": issue_indices,
        "missing_verses": [f"{chapter}:{v}" for v in missing_verses],
    }

    verse_word_counts = {}
    for (s, v), n in wc.items():
        if s == chapter:
            verse_word_counts[f"{chapter}:{v}"] = n

    return {
        "audio_url": audio_url,
        "segments": segments,
        "summary": summary,
        "verse_word_counts": verse_word_counts,
    }
