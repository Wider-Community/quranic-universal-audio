"""Validate per-reciter segment output from extract_segments.py.

Reads ``segments.json`` (time/word validity, coverage) and optionally
``detailed.json`` (confidence stats, failed alignments).

Usage:
    python validate_segments.py <reciter_dir>        # single reciter → detailed report
    python validate_segments.py <parent_dir>         # all reciter subdirs → summary table
    python validate_segments.py <dir> --top 50       # show top 50 failures/low-conf
"""

import argparse
import io
import json
import statistics
import sys
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _rel_path(p: Path) -> str:
    """Return path relative to project root, or just the name as fallback."""
    try:
        return str(p.relative_to(_PROJECT_ROOT))
    except ValueError:
        return p.name


# ── Helpers ──────────────────────────────────────────────────────────────


def _ms_to_hms(ms: float) -> str:
    """Convert milliseconds to h:mm:ss.s format."""
    total_s = ms / 1000.0
    h = int(total_s // 3600)
    m = int((total_s % 3600) // 60)
    s = total_s % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:04.1f}"
    return f"{m}:{s:04.1f}"


def _ms_to_s(ms: float) -> str:
    """Convert ms to seconds string with 2 decimal places."""
    return f"{ms / 1000:.2f}s"


# ── Parsers ──────────────────────────────────────────────────────────────


def load_word_counts(surah_info_path: Path) -> dict[tuple[int, int], int]:
    """Build (surah, ayah) → num_words lookup from surah_info.json."""
    with open(surah_info_path, encoding="utf-8") as f:
        info = json.load(f)
    wc = {}
    for surah_str, data in info.items():
        surah = int(surah_str)
        for v in data["verses"]:
            wc[(surah, v["verse"])] = v["num_words"]
    return wc


def parse_segments(path: Path) -> tuple[dict[str, list[list]], dict]:
    """Parse segments.json → (verses, meta).

    verses: {verse_key: [[w_from, w_to, t_from_ms, t_to_ms], ...]}
    meta: dict from _meta line (e.g. pad_ms, min_silence_ms)
    """
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.pop("_meta", {})
    return doc, meta


def parse_detailed(path: Path) -> list[dict]:
    """Parse detailed.json → flat list of segment dicts with audio context."""
    segments = []
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    for entry in doc.get("entries", []):
        audio = entry.get("audio", "")
        ref = entry.get("ref", "")
        for seg in entry.get("segments", []):
            d = {
                "audio": audio,
                "ref": ref,
                "time_start": seg.get("time_start", 0),
                "time_end": seg.get("time_end", 0),
                "matched_ref": seg.get("matched_ref", ""),
                "matched_text": seg.get("matched_text", ""),
                "phonemes_asr": seg.get("phonemes_asr", ""),
                "confidence": seg.get("confidence", 0.0),
            }
            if seg.get("wrap_word_ranges"):
                d["wrap_word_ranges"] = seg["wrap_word_ranges"]
            segments.append(d)
    return segments


def parse_detailed_raw(path: Path) -> tuple[list[dict], dict]:
    """Parse detailed.json → (entries, meta) preserving entry structure."""
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.get("_meta", {})
    return doc.get("entries", []), meta


def _build_verse_audio_map(detailed_segs: list[dict]) -> dict[str, str]:
    """Build verse_key → audio path lookup from detailed segments."""
    mapping = {}
    for s in detailed_segs:
        ref = s.get("matched_ref", "")
        if not ref:
            continue
        parts = ref.split("-")
        if len(parts) == 2:
            start = parts[0].split(":")
            if len(start) >= 2:
                verse_key = f"{start[0]}:{start[1]}"
                if verse_key not in mapping:
                    mapping[verse_key] = s["audio"]
    return mapping


def _confidence_stats(detailed_segs: list[dict]) -> dict:
    """Compute confidence summary from detailed segments."""
    matched = [s for s in detailed_segs if s["matched_ref"]]
    failed = [s for s in detailed_segs if not s["matched_ref"]]
    empty_phonemes = [s for s in matched if not s.get("phonemes_asr", "").strip()]
    confidences = [s["confidence"] for s in matched]
    return {
        "confidences": confidences,
        "matched": matched,
        "failed": failed,
        "empty_phonemes": empty_phonemes,
        "conf_min": min(confidences) if confidences else 0,
        "conf_med": statistics.median(confidences) if confidences else 0,
        "conf_mean": statistics.mean(confidences) if confidences else 0,
        "conf_max": max(confidences) if confidences else 0,
        "conf_below_60": sum(1 for c in confidences if c < 0.60),
        "conf_below_80": sum(1 for c in confidences if c < 0.80),
        "failed_segments": len(failed),
        "empty_phonemes_count": len(empty_phonemes),
    }


# ── Core validation ─────────────────────────────────────────────────────


def validate_reciter(
    reciter_dir: Path,
    word_counts: dict[tuple[int, int], int],
    verbose: bool = False,
    top_n: int = 10,
) -> dict:
    """Validate a single reciter directory containing segments.json + detailed.json."""
    segments_path = reciter_dir / "segments.json"
    detailed_path = reciter_dir / "detailed.json"
    reciter = reciter_dir.name

    verses, meta = parse_segments(segments_path)
    pad_ms = meta.get("pad_ms", 0)

    # Structured errors/warnings with time and verse context
    errors = []      # list of {msg, verse_key, t_from, t_to}
    warnings = []    # list of {msg, verse_key, t_from, t_to}
    seg_durations = []
    pause_durations = []
    single_seg = 0
    multi_seg_verses = 0
    multi_seg_segs = 0
    max_segs = 0
    total_segments = 0
    cross_verse_keys = 0
    empty_verse_keys = 0

    # ── 0. Meta validation ──
    meta_fields = {"created_at", "asr_model", "vad_model", "pad_ms", "min_silence_ms", "min_speech_ms", "audio_source"}
    if not meta:
        errors.append({"msg": "_meta missing or empty", "verse_key": "", "t_from": 0, "t_to": 0})
    else:
        missing_meta = meta_fields - set(meta.keys())
        if missing_meta:
            warnings.append({"msg": f"_meta missing fields: {sorted(missing_meta)}",
                             "verse_key": "", "t_from": 0, "t_to": 0})

    # Per-verse word coverage (cross-verse keys expand across multiple verses)
    covered_per_verse: dict[tuple[int, int], set[int]] = defaultdict(set)

    for verse_key, segs in verses.items():
        is_cross_verse = "-" in verse_key
        if is_cross_verse:
            cross_verse_keys += 1
        n_segs = len(segs)
        total_segments += n_segs
        max_segs = max(max_segs, n_segs)

        # Empty verse key check
        if n_segs == 0:
            empty_verse_keys += 1
            errors.append({"msg": "verse key with zero segments",
                           "verse_key": verse_key, "t_from": 0, "t_to": 0})
            continue

        if n_segs == 1:
            single_seg += 1
        else:
            multi_seg_verses += 1
            multi_seg_segs += n_segs

        verse_t_from = segs[0][2]
        verse_t_to = segs[-1][3]

        # Duration, pause, and time/word validity checks (same for both key types)
        for i, seg in enumerate(segs):
            w_from, w_to, t_from, t_to = seg
            dur = t_to - t_from
            seg_durations.append(dur)

            if t_from >= t_to:
                errors.append({"msg": f"seg[{i}] time_from ({_ms_to_hms(t_from)}) >= time_to ({_ms_to_hms(t_to)})",
                               "verse_key": verse_key, "t_from": t_from, "t_to": t_to})
            if w_from < 1:
                errors.append({"msg": f"seg[{i}] word_from ({w_from}) < 1",
                               "verse_key": verse_key, "t_from": t_from, "t_to": t_to})
            if not is_cross_verse and w_to < w_from:
                errors.append({"msg": f"seg[{i}] word_to ({w_to}) < word_from ({w_from})",
                               "verse_key": verse_key, "t_from": t_from, "t_to": t_to})
            elif is_cross_verse and w_to < 1:
                errors.append({"msg": f"seg[{i}] word_to ({w_to}) < 1",
                               "verse_key": verse_key, "t_from": t_from, "t_to": t_to})

            if i + 1 < n_segs:
                next_t_from = segs[i + 1][2]
                if next_t_from < t_to:
                    errors.append({"msg": f"time overlap: seg[{i}] ends {_ms_to_hms(t_to)}, seg[{i+1}] starts {_ms_to_hms(next_t_from)}",
                                   "verse_key": verse_key, "t_from": t_from, "t_to": segs[i + 1][3]})
                else:
                    true_pause = (next_t_from - t_to) + 2 * pad_ms
                    pause_durations.append(true_pause)

        # Word coverage
        if is_cross_verse:
            # Cross-verse key: "37:151:3-37:152:2"
            kparts = verse_key.split("-")
            start_kparts = kparts[0].split(":")
            end_kparts = kparts[1].split(":")
            try:
                start_sura = int(start_kparts[0])
                start_ayah = int(start_kparts[1])
                start_word = int(start_kparts[2])
                end_ayah = int(end_kparts[1])
                end_word = int(end_kparts[2])
            except (ValueError, IndexError):
                continue

            for ayah in range(start_ayah, end_ayah + 1):
                wc = word_counts.get((start_sura, ayah))
                if wc is None:
                    errors.append({
                        "msg": f"cross-verse key references unknown verse {start_sura}:{ayah}",
                        "verse_key": verse_key, "t_from": verse_t_from, "t_to": verse_t_to})
                    continue
                if ayah == start_ayah:
                    covered_per_verse[(start_sura, ayah)].update(range(start_word, wc + 1))
                elif ayah == end_ayah:
                    covered_per_verse[(start_sura, ayah)].update(range(1, end_word + 1))
                else:
                    covered_per_verse[(start_sura, ayah)].update(range(1, wc + 1))
        else:
            # Regular key: "37:151"
            parts = verse_key.split(":")
            surah, ayah = int(parts[0]), int(parts[1])
            for seg in segs:
                covered_per_verse[(surah, ayah)].update(range(seg[0], seg[1] + 1))

    # Word coverage validation across all verses
    all_verses_in_file: set[tuple[int, int]] = set()
    for verse_key in verses:
        if "-" in verse_key:
            kparts = verse_key.split("-")
            start_kparts = kparts[0].split(":")
            end_kparts = kparts[1].split(":")
            try:
                s = int(start_kparts[0])
                for a in range(int(start_kparts[1]), int(end_kparts[1]) + 1):
                    all_verses_in_file.add((s, a))
            except (ValueError, IndexError):
                pass
        else:
            parts = verse_key.split(":")
            all_verses_in_file.add((int(parts[0]), int(parts[1])))

    for (surah, ayah) in sorted(all_verses_in_file):
        expected_words = word_counts.get((surah, ayah))
        if expected_words is not None:
            covered_words = covered_per_verse.get((surah, ayah), set())
            expected_set = set(range(1, expected_words + 1))
            missing = expected_set - covered_words
            extra = covered_words - expected_set
            vk = f"{surah}:{ayah}"
            # Find time range for context (from any key covering this verse)
            vk_t_from = 0
            vk_t_to = 0
            for k, s in verses.items():
                if vk == k or (("-" in k) and any(
                    f"{surah}:{ayah}" in p for p in k.split("-")
                )):
                    if s:
                        vk_t_from = s[0][2]
                        vk_t_to = s[-1][3]
                    break
            if missing:
                warnings.append({"msg": f"missing words: {sorted(missing)}",
                                 "verse_key": vk, "t_from": vk_t_from, "t_to": vk_t_to})
            if extra:
                warnings.append({"msg": f"extra words beyond {expected_words}: {sorted(extra)}",
                                 "verse_key": vk, "t_from": vk_t_from, "t_to": vk_t_to})

    missing_verses = []
    for (surah, ayah) in sorted(word_counts):
        if (surah, ayah) not in all_verses_in_file:
            missing_verses.append(f"{surah}:{ayah}")

    word_gap_count = sum(1 for w in warnings if "missing words" in w["msg"])

    stats = {
        "reciter": reciter,
        "verses": len(all_verses_in_file),
        "total_verses": len(word_counts),
        "segments": total_segments,
        "single": single_seg,
        "multi_verses": multi_seg_verses,
        "multi_segs": multi_seg_segs,
        "max_segs": max_segs,
        "cross_verse": cross_verse_keys,
        "empty_verse_keys": empty_verse_keys,
        "seg_dur_min": min(seg_durations) if seg_durations else 0,
        "seg_dur_med": statistics.median(seg_durations) if seg_durations else 0,
        "seg_dur_mean": statistics.mean(seg_durations) if seg_durations else 0,
        "seg_dur_max": max(seg_durations) if seg_durations else 0,
        "pause_dur_min": min(pause_durations) if pause_durations else 0,
        "pause_dur_med": statistics.median(pause_durations) if pause_durations else 0,
        "pause_dur_mean": statistics.mean(pause_durations) if pause_durations else 0,
        "pause_dur_max": max(pause_durations) if pause_durations else 0,
        "missing": len(missing_verses),
        "word_gaps": word_gap_count,
        "errors": len(errors),
        "warnings": len(warnings),
    }

    # Confidence stats from detailed.json
    has_detailed = detailed_path.exists()
    detailed_segs = []
    if has_detailed:
        detailed_segs = parse_detailed(detailed_path)
        cstats = _confidence_stats(detailed_segs)
        for k in ["conf_min", "conf_med", "conf_mean", "conf_max",
                   "conf_below_60", "conf_below_80", "failed_segments",
                   "empty_phonemes_count"]:
            stats[k] = cstats[k]
    else:
        stats["conf_min"] = stats["conf_med"] = stats["conf_mean"] = stats["conf_max"] = 0
        stats["conf_below_60"] = stats["conf_below_80"] = stats["failed_segments"] = 0
        stats["empty_phonemes_count"] = 0

    # ── Cross-file consistency: detailed.json ↔ segments.json ──
    consistency_mismatches = 0
    if has_detailed:
        raw_entries, _ = parse_detailed_raw(detailed_path)
        # Rebuild expected segments.json from detailed.json (same logic as
        # extract_segments / server rebuild): group matched segments by verse key
        rebuilt: dict[str, list[tuple[int, int, int, int]]] = defaultdict(list)
        for entry in raw_entries:
            for seg in entry.get("segments", []):
                matched_ref = seg.get("matched_ref", "")
                if not matched_ref:
                    continue
                parts = matched_ref.split("-")
                if len(parts) != 2:
                    continue
                sp = parts[0].split(":")
                ep = parts[1].split(":")
                if len(sp) != 3 or len(ep) != 3:
                    continue
                try:
                    s_ayah, e_ayah = int(sp[1]), int(ep[1])
                    w_from, w_to = int(sp[2]), int(ep[2])
                except ValueError:
                    continue
                if s_ayah == e_ayah:
                    vk = f"{sp[0]}:{sp[1]}"
                else:
                    vk = matched_ref  # compound key
                t_from = round(seg.get("time_start", 0))
                t_to = round(seg.get("time_end", 0))
                rebuilt[vk].append((w_from, w_to, t_from, t_to))

        # Compare verse counts
        seg_only = set(verses.keys()) - set(rebuilt.keys())
        det_only = set(rebuilt.keys()) - set(verses.keys())
        if seg_only:
            consistency_mismatches += len(seg_only)
            for vk in sorted(seg_only):
                warnings.append({"msg": f"in segments.json but not in detailed.json",
                                 "verse_key": vk, "t_from": 0, "t_to": 0})
        if det_only:
            consistency_mismatches += len(det_only)
            for vk in sorted(det_only):
                warnings.append({"msg": f"in detailed.json but not in segments.json",
                                 "verse_key": vk, "t_from": 0, "t_to": 0})

        # Compare segment counts per shared verse key
        for vk in sorted(set(verses.keys()) & set(rebuilt.keys())):
            n_seg = len(verses[vk])
            n_det = len(rebuilt[vk])
            if n_seg != n_det:
                consistency_mismatches += 1
                warnings.append({
                    "msg": f"segment count mismatch: segments.json has {n_seg}, detailed.json has {n_det}",
                    "verse_key": vk, "t_from": 0, "t_to": 0})

    stats["consistency_mismatches"] = consistency_mismatches

    if verbose:
        _print_verbose(reciter, reciter_dir, stats, meta, errors, warnings,
                       missing_verses, word_counts, pause_durations,
                       has_detailed, detailed_segs, top_n)

    return stats


# ── Verbose single-reciter report ────────────────────────────────────────


def _print_verbose(reciter, reciter_dir, stats, meta, errors, warnings,
                   missing_verses, word_counts, pause_durations,
                   has_detailed, detailed_segs, top_n):
    """Pretty-print a detailed single-reciter report."""
    W = 72
    print("=" * W)
    print(f"  {reciter}")
    print(f"  {_rel_path(reciter_dir)}")
    print("=" * W)

    # ── VAD Settings ──
    if meta:
        print(f"\n--- VAD Settings ---")
        print(f"  Min silence:   {meta.get('min_silence_ms', '?')} ms")
        print(f"  Min speech:    {meta.get('min_speech_ms', '?')} ms")
        print(f"  Padding:       {meta.get('pad_ms', '?')} ms")

    # ── Coverage ──
    print(f"\n--- Coverage ---")
    print(f"  Verses found:       {stats['verses']} / {stats['total_verses']}")
    print(f"  Missing verses:     {stats['missing']}")
    print(f"  Partial words:      {stats['word_gaps']} verses with word gaps")

    # ── Segments ──
    print(f"\n--- Segments ---")
    print(f"  Total segments:     {stats['segments']}")
    print(f"  Single-seg verses:  {stats['single']}")
    print(f"  Multi-seg verses:   {stats['multi_verses']} ({stats['multi_segs']} segments)")
    print(f"  Cross-verse segs:   {stats['cross_verse']}")
    print(f"  Empty verse keys:   {stats['empty_verse_keys']}")
    print(f"  Max segs/verse:     {stats['max_segs']}")

    # ── Durations ──
    print(f"\n--- Segment Duration ---")
    print(f"  Min:      {_ms_to_s(stats['seg_dur_min'])}")
    print(f"  Median:   {_ms_to_s(stats['seg_dur_med'])}")
    print(f"  Mean:     {_ms_to_s(stats['seg_dur_mean'])}")
    print(f"  Max:      {_ms_to_s(stats['seg_dur_max'])}")

    print(f"\n--- True Silence Duration (padding reversed) ---")
    if pause_durations:
        print(f"  Min:      {_ms_to_s(stats['pause_dur_min'])}")
        print(f"  Median:   {_ms_to_s(stats['pause_dur_med'])}")
        print(f"  Mean:     {_ms_to_s(stats['pause_dur_mean'])}")
        print(f"  Max:      {_ms_to_s(stats['pause_dur_max'])}")
    else:
        print(f"  (no multi-segment verses)")

    # ── Confidence ──
    if has_detailed:
        cstats = _confidence_stats(detailed_segs)
        verse_audio = _build_verse_audio_map(detailed_segs)

        print(f"\n--- Alignment Confidence ---")
        print(f"  Min:        {stats['conf_min']:.4f}")
        print(f"  Median:     {stats['conf_med']:.4f}")
        print(f"  Mean:       {stats['conf_mean']:.4f}")
        print(f"  Max:        {stats['conf_max']:.4f}")
        print(f"  Below 60%:  {stats['conf_below_60']}")
        print(f"  Below 80%:  {stats['conf_below_80']}")
        print(f"  Failed:     {stats['failed_segments']} (no alignment)")
        print(f"  Empty ASR:  {stats['empty_phonemes_count']} (matched but no phonemes)")

        # ── Empty phonemes detail ──
        empty_ph = cstats["empty_phonemes"]
        if empty_ph:
            n_show = min(top_n, len(empty_ph))
            print(f"\n--- First {n_show} of {len(empty_ph)} Segments with Empty Phonemes ---")
            for i, s in enumerate(empty_ph[:n_show], 1):
                print(f"  {i:>2}. [{s['confidence']:.4f}]  {s['matched_ref']}  @ {_ms_to_hms(s['time_start'])} - {_ms_to_hms(s['time_end'])}")
                print(f"      audio: {s['audio']}")
                print(f"      text:  {s['matched_text']}")
                print()

        # ── Failed alignments (before low-confidence) ──
        failed = cstats["failed"]
        if failed:
            n_show = min(top_n, len(failed))
            print(f"\n--- First {n_show} of {len(failed)} Alignment Failures ---")
            for i, s in enumerate(failed[:n_show], 1):
                print(f"  {i:>2}. {_ms_to_hms(s['time_start'])} - {_ms_to_hms(s['time_end'])}  ({_ms_to_s(s['time_end'] - s['time_start'])})")
                print(f"      audio: {s['audio']}")
                print(f"      asr:   {s['phonemes_asr']}")
                print()

        # ── Lowest confidence (below 0.8 only) ──
        matched = cstats["matched"]
        below_80 = [s for s in matched if s["confidence"] < 0.80]
        if below_80:
            by_conf = sorted(below_80, key=lambda s: s["confidence"])
            n_show = min(top_n, len(by_conf))
            print(f"\n--- Lowest {n_show} of {len(below_80)} Segments Below 80% Confidence ---")
            for i, s in enumerate(by_conf[:n_show], 1):
                print(f"  {i:>2}. [{s['confidence']:.4f}]  {s['matched_ref']}  @ {_ms_to_hms(s['time_start'])} - {_ms_to_hms(s['time_end'])}")
                print(f"      audio: {s['audio']}")
                print(f"      text:  {s['matched_text']}")
                print(f"      asr:   {s['phonemes_asr']}")
                print()
    else:
        print(f"\n--- Alignment Confidence ---")
        print(f"  (no detailed.json)")

    # ── Cross-file Consistency ──
    if has_detailed:
        print(f"\n--- Cross-file Consistency (detailed.json ↔ segments.json) ---")
        print(f"  Mismatches:     {stats.get('consistency_mismatches', 0)}")
    else:
        print(f"\n--- Cross-file Consistency ---")
        print(f"  (no detailed.json)")

    # ── Detected Repetitions ──
    if has_detailed:
        rep_segs = [s for s in detailed_segs if s.get("wrap_word_ranges")]
        if rep_segs:
            print(f"\n--- Detected Repetitions ({len(rep_segs)}) ---")
            for i, s in enumerate(rep_segs, 1):
                print(f"  {i:>2}. [{s['confidence']:.4f}]  {s['matched_ref']}  @ {_ms_to_hms(s['time_start'])} - {_ms_to_hms(s['time_end'])}")
                print(f"      audio: {s['audio']}")
                print(f"      text:  {s['matched_text']}")
                print()

    # ── Errors & Warnings ──
    # Build audio lookup for error/warning context
    if has_detailed:
        verse_audio = _build_verse_audio_map(detailed_segs)
    else:
        verse_audio = {}

    print(f"\n--- Validation Issues ---")
    print(f"  Errors:     {stats['errors']}")
    print(f"  Warnings:   {stats['warnings']}")

    if missing_verses:
        n_show = min(top_n, len(missing_verses))
        print(f"\n  Missing verses (first {n_show} of {len(missing_verses)}):")
        for v in missing_verses[:n_show]:
            nw = word_counts.get(tuple(int(x) for x in v.split(":")), "?")
            print(f"    MISS   {v}  ({nw} words)")
        if len(missing_verses) > n_show:
            print(f"    ... and {len(missing_verses) - n_show} more")
    if warnings:
        print(f"\n  Warnings:")
        for w in warnings:
            audio = verse_audio.get(w["verse_key"], "")
            print(f"    WARN   {w['verse_key']}  @ {_ms_to_hms(w['t_from'])} - {_ms_to_hms(w['t_to'])}")
            print(f"           {w['msg']}")
            if audio:
                print(f"           audio: {audio}")
            print()
    if errors:
        print(f"\n  Errors:")
        for e in errors:
            audio = verse_audio.get(e["verse_key"], "")
            print(f"    ERROR  {e['verse_key']}  @ {_ms_to_hms(e['t_from'])} - {_ms_to_hms(e['t_to'])}")
            print(f"           {e['msg']}")
            if audio:
                print(f"           audio: {audio}")
            print()

    print()


# ── Summary table (multi-reciter) ───────────────────────────────────────


def _print_row(reciter: str, cols: list[str], widths: list[int]):
    parts = [f"{reciter:<35}"]
    for val, w in zip(cols, widths):
        parts.append(f"{val:>{w}}")
    print(" ".join(parts))


def print_table(all_stats: list[dict]):
    """Print summary tables: segments, segment durations, pause durations, confidence."""
    sorted_stats = sorted(all_stats, key=lambda x: x["reciter"])
    total_label = f"TOTAL ({len(all_stats)} reciters)"

    # --- Table 1: Segments ---
    print("=== Segments ===\n")
    seg_hdrs = ["Verses", "Total Segs", "Single", "Multi (segs)", "Cross-V", "Max/Verse", "No Verse", "Word Gaps", "Errors"]
    seg_ws = [6, 10, 6, 16, 7, 9, 8, 9, 6]
    _print_row("Reciter", seg_hdrs, seg_ws)
    print("-" * (35 + sum(w + 1 for w in seg_ws)))

    totals = {k: 0 for k in ["verses", "segments", "single", "multi_verses", "multi_segs", "cross_verse", "missing", "word_gaps", "errors"]}
    for s in sorted_stats:
        multi_str = f"{s['multi_verses']} ({s['multi_segs']})"
        _print_row(s["reciter"], [
            str(s["verses"]), str(s["segments"]), str(s["single"]),
            multi_str, str(s["cross_verse"]), str(s["max_segs"]),
            str(s["missing"]), str(s["word_gaps"]), str(s["errors"]),
        ], seg_ws)
        for k in totals:
            totals[k] += s[k]

    print("-" * (35 + sum(w + 1 for w in seg_ws)))
    multi_total = f"{totals['multi_verses']} ({totals['multi_segs']})"
    _print_row(total_label, [
        str(totals["verses"]), str(totals["segments"]), str(totals["single"]),
        multi_total, str(totals["cross_verse"]), "",
        str(totals["missing"]), str(totals["word_gaps"]), str(totals["errors"]),
    ], seg_ws)

    # --- Table 2: Segment Duration ---
    print("\n\n=== Segment Duration (ms) ===\n")
    dur_hdrs = ["Min", "Median", "Mean", "Max"]
    dur_ws = [8, 8, 8, 8]
    _print_row("Reciter", dur_hdrs, dur_ws)
    print("-" * (35 + sum(w + 1 for w in dur_ws)))

    all_med = []
    for s in sorted_stats:
        _print_row(s["reciter"], [
            f"{s['seg_dur_min']:.1f}", f"{s['seg_dur_med']:.1f}",
            f"{s['seg_dur_mean']:.1f}", f"{s['seg_dur_max']:.1f}",
        ], dur_ws)
        all_med.append(s["seg_dur_med"])

    print("-" * (35 + sum(w + 1 for w in dur_ws)))
    med_of_med = statistics.median(all_med) if all_med else 0
    _print_row(total_label, ["", f"{med_of_med:.1f}", "", ""], dur_ws)

    # --- Table 3: True Silence Duration (ms) ---
    print("\n\n=== True Silence Duration (ms, padding reversed) ===\n")
    _print_row("Reciter", dur_hdrs, dur_ws)
    print("-" * (35 + sum(w + 1 for w in dur_ws)))

    all_pause_med = []
    for s in sorted_stats:
        if s["pause_dur_med"] > 0:
            _print_row(s["reciter"], [
                f"{s['pause_dur_min']:.1f}", f"{s['pause_dur_med']:.1f}",
                f"{s['pause_dur_mean']:.1f}", f"{s['pause_dur_max']:.1f}",
            ], dur_ws)
            all_pause_med.append(s["pause_dur_med"])
        else:
            _print_row(s["reciter"], ["n/a", "n/a", "n/a", "n/a"], dur_ws)

    print("-" * (35 + sum(w + 1 for w in dur_ws)))
    med_of_pause = statistics.median(all_pause_med) if all_pause_med else 0
    _print_row(total_label, ["", f"{med_of_pause:.1f}", "", ""], dur_ws)

    # --- Table 4: Confidence ---
    has_any_detailed = any(s["conf_mean"] > 0 for s in sorted_stats)
    if has_any_detailed:
        print("\n\n=== Alignment Confidence ===\n")
        conf_hdrs = ["Min", "Median", "Mean", "Max", "Below 60%", "Below 80%", "Failed", "Empty ASR"]
        conf_ws = [6, 6, 6, 6, 9, 9, 6, 9]
        _print_row("Reciter", conf_hdrs, conf_ws)
        print("-" * (35 + sum(w + 1 for w in conf_ws)))

        all_conf_med = []
        total_below_60 = 0
        total_below_80 = 0
        total_failed = 0
        total_empty_ph = 0
        for s in sorted_stats:
            if s["conf_mean"] > 0:
                _print_row(s["reciter"], [
                    f"{s['conf_min']:.2f}", f"{s['conf_med']:.2f}",
                    f"{s['conf_mean']:.2f}", f"{s['conf_max']:.2f}",
                    str(s["conf_below_60"]), str(s["conf_below_80"]),
                    str(s["failed_segments"]), str(s["empty_phonemes_count"]),
                ], conf_ws)
                all_conf_med.append(s["conf_med"])
            else:
                _print_row(s["reciter"], ["n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a"], conf_ws)
            total_below_60 += s["conf_below_60"]
            total_below_80 += s["conf_below_80"]
            total_failed += s["failed_segments"]
            total_empty_ph += s["empty_phonemes_count"]

        print("-" * (35 + sum(w + 1 for w in conf_ws)))
        med_conf = statistics.median(all_conf_med) if all_conf_med else 0
        _print_row(total_label, [
            "", f"{med_conf:.2f}", "", "",
            str(total_below_60), str(total_below_80), str(total_failed),
            str(total_empty_ph),
        ], conf_ws)

    # --- Table 5: Consistency ---
    has_any_consistency = any(s.get("consistency_mismatches", 0) > 0 or s.get("empty_verse_keys", 0) > 0 for s in sorted_stats)
    if has_any_consistency:
        print("\n\n=== Cross-file Consistency ===\n")
        con_hdrs = ["Empty Keys", "Det↔Seg MM"]
        con_ws = [10, 10]
        _print_row("Reciter", con_hdrs, con_ws)
        print("-" * (35 + sum(w + 1 for w in con_ws)))

        total_empty = 0
        total_mm = 0
        for s in sorted_stats:
            _print_row(s["reciter"], [
                str(s.get("empty_verse_keys", 0)),
                str(s.get("consistency_mismatches", 0)),
            ], con_ws)
            total_empty += s.get("empty_verse_keys", 0)
            total_mm += s.get("consistency_mismatches", 0)

        print("-" * (35 + sum(w + 1 for w in con_ws)))
        _print_row(total_label, [str(total_empty), str(total_mm)], con_ws)


# ── Report I/O ────────────────────────────────────────────────────────


@contextmanager
def _tee_to_file(path: Path):
    """Copy stdout to *path* (overwritten) while still printing to console."""
    buf = io.StringIO()
    orig = sys.stdout

    class _Tee:
        def write(self, s):
            orig.write(s)
            buf.write(s)

        def flush(self):
            orig.flush()

    sys.stdout = _Tee()
    try:
        yield
    finally:
        sys.stdout = orig
        content = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n" + buf.getvalue()
        path.write_text(content, encoding="utf-8")


# ── CLI ──────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path, help="Single reciter directory or parent directory of reciter subdirs")
    parser.add_argument(
        "--surah-info",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "surah_info.json",
        help="Path to surah_info.json",
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=30,
        help="Number of failures / lowest-confidence segments to show (default: 30)",
    )
    args = parser.parse_args()

    word_counts = load_word_counts(args.surah_info)
    target = args.path.resolve()

    if not target.is_dir():
        print(f"Path not found or not a directory: {_rel_path(target)}")
        return

    # Single reciter dir: contains segments.json directly
    if (target / "segments.json").exists():
        report_path = target / "validation.log"
        with _tee_to_file(report_path):
            validate_reciter(target, word_counts, verbose=True, top_n=args.top)
        print(f"Report saved to {_rel_path(report_path)}")
        print(f"Run  python inspector/server.py  to visually inspect and edit segments in the browser.")
        return

    # Parent dir: find subdirectories with segments.json
    subdirs = sorted(d for d in target.iterdir() if d.is_dir() and (d / "segments.json").exists())
    if not subdirs:
        print(f"No reciter subdirectories with segments.json found in {_rel_path(target)}")
        return

    # Per-reciter detailed reports (saved to each reciter's folder)
    all_stats = []
    for d in subdirs:
        per_report = d / "validation.log"
        with _tee_to_file(per_report):
            stats = validate_reciter(d, word_counts, verbose=True, top_n=args.top)
        all_stats.append(stats)
        print(f"  {d.name}: saved to {_rel_path(per_report)}")

    # Summary table across all reciters
    report_path = target / "validation.log"
    with _tee_to_file(report_path):
        print_table(all_stats)
    print(f"\nSummary saved to {_rel_path(report_path)}")
    print(f"Run  python inspector/server.py  to visually inspect and edit segments in the browser.")


if __name__ == "__main__":
    main()
