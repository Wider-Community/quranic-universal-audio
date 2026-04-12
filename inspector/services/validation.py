"""Validation engine: 10-category segment validation, chapter validation counts, and
validation log generation.

No Flask imports -- all functions accept parameters and return plain dicts.
"""

import statistics as _statistics
import sys
from collections import defaultdict
from pathlib import Path

from config import (
    BOUNDARY_TAIL_K,
    LOW_CONFIDENCE_THRESHOLD,
    SHOW_BOUNDARY_PHONEMES,
    SURAH_INFO_PATH,
)
from constants import (
    MUQATTAAT_VERSES,
    QALQALA_LETTERS,
    STANDALONE_REFS,
    STANDALONE_WORDS,
    VALIDATION_CATEGORIES,
)
from services import cache
from services.data_loader import (
    dk_text_for_ref,
    get_word_counts,
    load_audio_urls,
    load_detailed,
    load_seg_verses,
    word_has_stop,
)
from services.phoneme_matching import (
    get_phoneme_sub_pairs,
    get_phoneme_tails,
    tail_phoneme_mismatch,
)
from services.phonemizer_service import get_canonical_phonemes
from utils.arabic_text import last_arabic_letter, strip_quran_deco
from utils.formatting import format_ms
from utils.references import chapter_from_ref, seg_belongs_to_entry


def is_ignored_for(seg: dict, category: str) -> bool:
    """Check if a segment is ignored for a specific validation category."""
    ic = seg.get("ignored_categories")
    if ic:
        return "_all" in ic or category in ic
    return bool(seg.get("ignored"))


def chapter_validation_counts(entries: list, chapter: int, meta: dict,
                              canonical: dict | None = None) -> dict:
    """Count validation issues for a single chapter.  Returns ``{category: count}``."""
    word_counts = get_word_counts()
    single_word_verses = {k for k, v in word_counts.items() if v == 1}
    is_by_ayah = "by_ayah" in meta.get("audio_source", "")

    counts = {cat: 0 for cat in VALIDATION_CATEGORIES}
    verse_segments: dict[tuple, list] = defaultdict(list)

    for entry in entries:
        ch = chapter_from_ref(entry["ref"])
        if ch != chapter:
            continue
        entry_ref = entry.get("ref", "")
        for seg in entry.get("segments", []):
            matched_ref = seg.get("matched_ref", "")
            confidence = seg.get("confidence", 0.0)

            if not matched_ref:
                counts["failed"] += 1
                continue

            if is_by_ayah and ":" in entry_ref and not seg_belongs_to_entry(matched_ref, entry_ref):
                counts["audio_bleeding"] += 1

            if seg.get("wrap_word_ranges"):
                counts["repetitions"] += 1

            if confidence < LOW_CONFIDENCE_THRESHOLD:
                counts["low_confidence"] += 1

            parts = matched_ref.split("-")
            if len(parts) != 2:
                continue
            sp = parts[0].split(":")
            ep = parts[1].split(":")
            if len(sp) != 3 or len(ep) != 3:
                continue
            try:
                surah, s_ayah, s_word = int(sp[0]), int(sp[1]), int(sp[2])
                e_ayah, e_word = int(ep[1]), int(ep[2])
            except (ValueError, IndexError):
                continue

            if s_ayah != e_ayah:
                if not is_ignored_for(seg, "cross_verse"):
                    counts["cross_verse"] += 1
                for ayah in range(s_ayah, e_ayah + 1):
                    if ayah == s_ayah:
                        wc = word_counts.get((surah, ayah), s_word)
                        verse_segments[(surah, ayah)].append((s_word, wc))
                    elif ayah == e_ayah:
                        verse_segments[(surah, ayah)].append((1, e_word))
                    else:
                        wc = word_counts.get((surah, ayah), 1)
                        verse_segments[(surah, ayah)].append((1, wc))
            else:
                verse_segments[(surah, s_ayah)].append((s_word, e_word))
                is_boundary = False
                if (s_word == e_word
                    and not is_ignored_for(seg, "boundary_adj")
                    and (surah, s_ayah) not in MUQATTAAT_VERSES
                    and (surah, s_ayah) not in single_word_verses
                    and (surah, s_ayah, s_word) not in STANDALONE_REFS
                    and strip_quran_deco(seg.get("matched_text", "")) not in STANDALONE_WORDS):
                    is_boundary = True

                # Phoneme tail mismatch (only if not already flagged)
                if (not is_boundary and canonical and not is_ignored_for(seg, "boundary_adj")
                    and seg.get("phonemes_asr")):
                    if tail_phoneme_mismatch(seg["phonemes_asr"], matched_ref,
                                             canonical, BOUNDARY_TAIL_K):
                        is_boundary = True

                if is_boundary:
                    counts["boundary_adj"] += 1

            if s_word == 1 and (surah, s_ayah) in MUQATTAAT_VERSES:
                if not is_ignored_for(seg, "muqattaat"):
                    counts["muqattaat"] += 1

            last_letter = last_arabic_letter(seg.get("matched_text", ""))
            if last_letter in QALQALA_LETTERS and not is_ignored_for(seg, "qalqala"):
                counts["qalqala"] += 1

    # Missing words
    for (surah, ayah), seg_list in verse_segments.items():
        expected = word_counts.get((surah, ayah))
        if not expected:
            continue
        covered = set()
        for wf, wt in seg_list:
            covered.update(range(wf, wt + 1))
        missing = set(range(1, expected + 1)) - covered
        if missing:
            counts["missing_words"] += len(missing)

    return counts


def validate_reciter_segments(reciter: str) -> dict:
    """Validate all chapters for a reciter, returning issues grouped by category.

    Returns a plain dict suitable for ``jsonify()``.
    """
    entries = load_detailed(reciter)
    if not entries:
        return None  # caller returns 404

    word_counts = get_word_counts()
    canonical = get_canonical_phonemes(reciter)

    errors = []
    missing_verses = []
    missing_words = []
    failed = []
    low_confidence = []
    boundary_adj = []
    cross_verse = []
    audio_bleeding = []
    repetitions = []
    muqattaat = []
    qalqala = []
    chapter_seg_idx = {}

    single_word_verses = {k for k, v in word_counts.items() if v == 1}

    meta = cache.get_seg_meta(reciter)
    audio_source = meta.get("audio_source", "")
    is_by_ayah = "by_ayah" in audio_source

    # (surah, ayah) -> [(word_from, word_to, seg_index)]
    verse_segments: dict[tuple[int, int], list] = defaultdict(list)

    for entry in entries:
        chapter = chapter_from_ref(entry["ref"])
        entry_ref = entry.get("ref", "")
        raw_segments = entry.get("segments", [])

        for seg in raw_segments:
            i = chapter_seg_idx.get(chapter, 0)
            chapter_seg_idx[chapter] = i + 1
            matched_ref = seg.get("matched_ref", "")
            confidence = seg.get("confidence", 0.0)
            t_start = seg.get("time_start", 0)
            t_end = seg.get("time_end", 0)

            if not matched_ref:
                failed.append({
                    "chapter": chapter,
                    "seg_index": i,
                    "time": f"{format_ms(t_start)}-{format_ms(t_end)}",
                })
                continue

            if is_by_ayah and ":" in entry_ref and not seg_belongs_to_entry(matched_ref, entry_ref):
                seg_start = matched_ref.split("-")[0]
                seg_parts = seg_start.split(":")
                matched_verse = f"{seg_parts[0]}:{seg_parts[1]}" if len(seg_parts) >= 2 else matched_ref
                audio_bleeding.append({
                    "chapter": chapter,
                    "seg_index": i,
                    "entry_ref": entry_ref,
                    "matched_verse": matched_verse,
                    "ref": matched_ref,
                    "confidence": round(confidence, 4),
                    "time": f"{format_ms(t_start)}-{format_ms(t_end)}",
                    "msg": f"audio {entry_ref} contains segment matching verse {matched_verse}",
                })

            if seg.get("wrap_word_ranges"):
                parts = matched_ref.split("-")
                display_ref = matched_ref
                if len(parts) == 2:
                    s_parts = parts[0].split(":")
                    e_parts = parts[1].split(":")
                    if len(s_parts) >= 2 and len(e_parts) >= 2 and s_parts[1] == e_parts[1]:
                        display_ref = f"{s_parts[0]}:{s_parts[1]}"
                repetitions.append({
                    "chapter": chapter,
                    "seg_index": i,
                    "ref": matched_ref,
                    "display_ref": display_ref,
                    "confidence": round(confidence, 4),
                    "time": f"{format_ms(t_start)}-{format_ms(t_end)}",
                    "text": seg.get("matched_text", ""),
                })

            if confidence < 1.0:
                parts = matched_ref.split("-")
                display_ref = matched_ref
                if len(parts) == 2:
                    s = parts[0].split(":")
                    e = parts[1].split(":")
                    if len(s) >= 2 and len(e) >= 2:
                        if s[1] == e[1]:
                            display_ref = f"{s[0]}:{s[1]}"
                        else:
                            display_ref = f"{s[0]}:{s[1]}-{e[1]}"
                low_confidence.append({
                    "ref": display_ref,
                    "chapter": chapter,
                    "seg_index": i,
                    "confidence": round(confidence, 4),
                })

            parts = matched_ref.split("-")
            if len(parts) != 2:
                continue
            start_parts = parts[0].split(":")
            end_parts = parts[1].split(":")
            if len(start_parts) != 3 or len(end_parts) != 3:
                continue
            try:
                s_ayah = int(start_parts[1])
                e_ayah = int(end_parts[1])
                s_word = int(start_parts[2])
                e_word = int(end_parts[2])
                surah = int(start_parts[0])
            except (ValueError, IndexError):
                continue

            if s_ayah != e_ayah:
                if not is_ignored_for(seg, "cross_verse"):
                    cross_verse.append({
                        "chapter": chapter,
                        "seg_index": i,
                        "ref": matched_ref,
                    })
                for ayah in range(s_ayah, e_ayah + 1):
                    if ayah == s_ayah:
                        wc = word_counts.get((surah, ayah), s_word)
                        verse_segments[(surah, ayah)].append((s_word, wc, i))
                    elif ayah == e_ayah:
                        verse_segments[(surah, ayah)].append((1, e_word, i))
                    else:
                        wc = word_counts.get((surah, ayah), 1)
                        verse_segments[(surah, ayah)].append((1, wc, i))
            else:
                verse_segments[(surah, s_ayah)].append((s_word, e_word, i))

                is_boundary = False
                if (s_word == e_word
                    and not is_ignored_for(seg, "boundary_adj")
                    and (surah, s_ayah) not in MUQATTAAT_VERSES
                    and (surah, s_ayah) not in single_word_verses
                    and (surah, s_ayah, s_word) not in STANDALONE_REFS
                    and strip_quran_deco(seg.get("matched_text", "")) not in STANDALONE_WORDS):
                    is_boundary = True

                if (not is_boundary and canonical and not is_ignored_for(seg, "boundary_adj")
                    and seg.get("phonemes_asr")):
                    if tail_phoneme_mismatch(seg["phonemes_asr"], matched_ref,
                                             canonical, BOUNDARY_TAIL_K):
                        is_boundary = True

                if is_boundary:
                    item = {
                        "chapter": chapter,
                        "seg_index": i,
                        "ref": matched_ref,
                        "verse_key": f"{surah}:{s_ayah}",
                    }
                    if SHOW_BOUNDARY_PHONEMES and canonical and seg.get("phonemes_asr"):
                        display_n = BOUNDARY_TAIL_K + 2
                        tails = get_phoneme_tails(seg["phonemes_asr"], matched_ref,
                                                  canonical, display_n)
                        if tails:
                            item["gt_tail"] = " ".join(tails[0])
                            item["asr_tail"] = " ".join(tails[1])
                    boundary_adj.append(item)

            if s_word == 1 and (surah, s_ayah) in MUQATTAAT_VERSES:
                if not is_ignored_for(seg, "muqattaat"):
                    muqattaat.append({
                        "chapter": chapter,
                        "seg_index": i,
                        "ref": matched_ref,
                    })

            _last_ltr = last_arabic_letter(seg.get("matched_text", ""))
            if _last_ltr and _last_ltr in QALQALA_LETTERS and not is_ignored_for(seg, "qalqala"):
                qalqala.append({
                    "chapter": chapter,
                    "seg_index": i,
                    "ref": matched_ref,
                    "qalqala_letter": _last_ltr,
                })

    # Missing word pairs
    for (surah, ayah), seg_list in verse_segments.items():
        expected = word_counts.get((surah, ayah))
        if not expected:
            continue
        seg_list.sort(key=lambda x: x[0])
        covered = set()
        for wf, wt, _ in seg_list:
            covered.update(range(wf, wt + 1))
        missing = set(range(1, expected + 1)) - covered
        if not missing:
            continue

        gap_indices = set()
        for j in range(len(seg_list)):
            wf, wt, idx = seg_list[j]
            if j + 1 < len(seg_list):
                next_wf, _, next_idx = seg_list[j + 1]
                if next_wf > wt + 1:
                    gap_indices.add(idx)
                    gap_indices.add(next_idx)
            if j == len(seg_list) - 1 and wt < expected:
                gap_indices.add(idx)
            if j == 0 and wf > 1:
                gap_indices.add(idx)

        auto_fix = None
        if len(missing) == 1:
            mw = next(iter(missing))
            first_wf, first_wt, first_idx = seg_list[0]
            last_wf, last_wt, last_idx = seg_list[-1]

            if mw == 1 and first_wf > 1:
                auto_fix = {"target_seg_index": first_idx,
                            "new_ref_start": f"{surah}:{ayah}:1",
                            "new_ref_end": f"{surah}:{ayah}:{first_wt}"}
            elif mw == expected and last_wt < expected:
                auto_fix = {"target_seg_index": last_idx,
                            "new_ref_start": f"{surah}:{ayah}:{last_wf}",
                            "new_ref_end": f"{surah}:{ayah}:{expected}"}
            else:
                for j in range(len(seg_list) - 1):
                    wf, wt, idx = seg_list[j]
                    next_wf, next_wt, next_idx = seg_list[j + 1]
                    if wt + 1 == mw and mw + 1 == next_wf:
                        if word_has_stop(surah, ayah, wt):
                            auto_fix = {"target_seg_index": next_idx,
                                        "new_ref_start": f"{surah}:{ayah}:{mw}",
                                        "new_ref_end": f"{surah}:{ayah}:{next_wt}"}
                        elif word_has_stop(surah, ayah, mw):
                            auto_fix = {"target_seg_index": idx,
                                        "new_ref_start": f"{surah}:{ayah}:{wf}",
                                        "new_ref_end": f"{surah}:{ayah}:{mw}"}
                        break

        issue = {
            "verse_key": f"{surah}:{ayah}",
            "chapter": surah,
            "msg": f"missing words: {sorted(missing)}",
            "seg_indices": sorted(gap_indices),
        }
        if auto_fix:
            issue["auto_fix"] = auto_fix
        missing_words.append(issue)

    # Structural errors + stats from segments.json
    stats = None
    verses, pad_ms = load_seg_verses(reciter)
    if verses:
        total_segments = 0
        single_seg = 0
        multi_seg_verses = 0
        multi_seg_segs = 0
        max_segs = 0
        cross_verse_count = 0
        seg_durations = []
        pause_durations = []

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
                    errors.append({
                        "verse_key": verse_key, "chapter": surah,
                        "msg": "time_from >= time_to",
                    })
                if w_from < 1:
                    errors.append({
                        "verse_key": verse_key, "chapter": surah,
                        "msg": "word_from < 1",
                    })
                if not is_cross and w_to < w_from:
                    errors.append({
                        "verse_key": verse_key, "chapter": surah,
                        "msg": "word_to < word_from",
                    })
                elif is_cross and w_to < 1:
                    errors.append({
                        "verse_key": verse_key, "chapter": surah,
                        "msg": "word_to < 1",
                    })

                if idx + 1 < len(segs) and len(segs[idx + 1]) >= 4:
                    next_t_from = segs[idx + 1][2]
                    if next_t_from < t_to:
                        errors.append({
                            "verse_key": verse_key, "chapter": surah,
                            "msg": "time overlap",
                        })
                    else:
                        true_pause = (next_t_from - t_to) + 2 * pad_ms
                        pause_durations.append(true_pause)

        # Missing verses
        all_verse_keys_in_file = set()
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
                missing_verses.append({
                    "verse_key": f"{surah}:{ayah}", "chapter": surah,
                    "msg": "missing verse",
                })

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

    return {
        "errors": errors,
        "missing_verses": missing_verses,
        "missing_words": missing_words,
        "failed": failed,
        "low_confidence": low_confidence,
        "boundary_adj": boundary_adj,
        "cross_verse": cross_verse,
        "audio_bleeding": audio_bleeding,
        "repetitions": repetitions,
        "muqattaat": muqattaat,
        "qalqala": qalqala,
        "stats": stats,
    }


def run_validation_log(reciter_dir: Path) -> None:
    """Run segment validation and write validation.log without printing to console."""
    import io as _io
    from datetime import datetime as _dt
    from validators.validate_segments import validate_reciter, load_word_counts

    wc = load_word_counts(SURAH_INFO_PATH)
    report_path = reciter_dir / "validation.log"

    buf = _io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        validate_reciter(reciter_dir, wc, verbose=True)
    finally:
        sys.stdout = old_stdout

    content = f"Generated: {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n" + buf.getvalue()
    report_path.write_text(content, encoding="utf-8")
