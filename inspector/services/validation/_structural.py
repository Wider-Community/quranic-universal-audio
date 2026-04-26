"""Structural error detection + segment statistics.

Extracted from validate_reciter_segments. Reads segments.json (the
verse-aggregated format) to detect time-ordering, word-ordering, and overlap
errors, and to compute per-reciter statistics.
"""

from __future__ import annotations

import statistics as _statistics

from services.data_loader import get_word_counts, load_seg_verses
from utils.references import chapter_from_ref


def _check_structural_errors(reciter: str, entries: list[dict]) -> tuple[list, list, dict | None]:
    """Check structural integrity of segments.json.

    Returns ``(errors, missing_verses, stats)`` where:
    - ``errors``         — list of {verse_key, chapter, msg} dicts
    - ``missing_verses`` — list of {verse_key, chapter, msg} dicts
    - ``stats``          — summary statistics dict or None when no verse data

    Uses the verse-aggregated segments.json format for O(1) per-verse access.
    """
    errors: list[dict] = []
    missing_verses: list[dict] = []
    stats: dict | None = None

    verses, pad_ms = load_seg_verses(reciter)
    if not verses:
        return errors, missing_verses, stats

    word_counts = get_word_counts()

    total_segments = 0
    single_seg = 0
    multi_seg_verses = 0
    multi_seg_segs = 0
    max_segs = 0
    cross_verse_count = 0
    seg_durations: list[float] = []
    pause_durations: list[float] = []

    for verse_key, segs in verses.items():
        is_cross = "-" in verse_key
        if is_cross:
            cross_verse_count += 1

        n_segs = len(segs)
        total_segments += n_segs
        max_segs = max(max_segs, n_segs)
        if n_segs == 1:
            single_seg += 1
        elif n_segs > 1:
            multi_seg_verses += 1
            multi_seg_segs += n_segs

        if is_cross:
            kparts = verse_key.split("-")
            start_kparts = kparts[0].split(":")
            try:
                surah = int(start_kparts[0])
            except (ValueError, IndexError):
                continue
        else:
            kparts = verse_key.split(":")
            if len(kparts) != 2:
                continue
            surah = int(kparts[0])

        for idx, seg_arr in enumerate(segs):
            if len(seg_arr) < 4:
                continue
            w_from, w_to, t_from, t_to = seg_arr[0], seg_arr[1], seg_arr[2], seg_arr[3]
            seg_durations.append(t_to - t_from)

            if t_from >= t_to:
                errors.append({"verse_key": verse_key, "chapter": surah, "segment_uid": None, "msg": "time_from >= time_to"})
            if w_from < 1:
                errors.append({"verse_key": verse_key, "chapter": surah, "segment_uid": None, "msg": "word_from < 1"})
            if not is_cross and w_to < w_from:
                errors.append({"verse_key": verse_key, "chapter": surah, "segment_uid": None, "msg": "word_to < word_from"})
            elif is_cross and w_to < 1:
                errors.append({"verse_key": verse_key, "chapter": surah, "segment_uid": None, "msg": "word_to < 1"})

            if idx + 1 < len(segs) and len(segs[idx + 1]) >= 4:
                next_t_from = segs[idx + 1][2]
                if next_t_from < t_to:
                    errors.append({"verse_key": verse_key, "chapter": surah, "segment_uid": None, "msg": "time overlap"})
                else:
                    true_pause = (next_t_from - t_to) + 2 * pad_ms
                    pause_durations.append(true_pause)

    # Missing verses — derive covered surahs from segments.json keys
    all_verse_keys_in_file: set[tuple[int, int]] = set()
    for verse_key in verses:
        if "-" in verse_key:
            kparts = verse_key.split("-")
            start_kparts = kparts[0].split(":")
            end_kparts = kparts[1].split(":")
            try:
                s = int(start_kparts[0])
                for a in range(int(start_kparts[1]), int(end_kparts[1]) + 1):
                    all_verse_keys_in_file.add((s, a))
            except (ValueError, IndexError):
                pass
        else:
            kparts = verse_key.split(":")
            if len(kparts) == 2:
                all_verse_keys_in_file.add((int(kparts[0]), int(kparts[1])))

    covered_surahs = {chapter_from_ref(entry["ref"]) for entry in entries}
    for (surah, ayah) in sorted(word_counts):
        if surah not in covered_surahs:
            continue
        if (surah, ayah) not in all_verse_keys_in_file:
            missing_verses.append({"verse_key": f"{surah}:{ayah}", "chapter": surah, "segment_uid": None, "msg": "missing verse"})

    stats = {
        "segments": total_segments,
        "single": single_seg,
        "multi_verses": multi_seg_verses,
        "multi_segs": multi_seg_segs,
        "cross_verse": cross_verse_count,
        "max_segs": max_segs,
        "seg_dur_min": min(seg_durations) if seg_durations else 0,
        "seg_dur_med": _statistics.median(seg_durations) if seg_durations else 0,
        "seg_dur_mean": _statistics.mean(seg_durations) if seg_durations else 0,
        "seg_dur_max": max(seg_durations) if seg_durations else 0,
        "pause_dur_min": min(pause_durations) if pause_durations else 0,
        "pause_dur_med": _statistics.median(pause_durations) if pause_durations else 0,
        "pause_dur_mean": _statistics.mean(pause_durations) if pause_durations else 0,
        "pause_dur_max": max(pause_durations) if pause_durations else 0,
    }

    return errors, missing_verses, stats
