"""Validate per-reciter segment output from extract_segments.py.

Checks segments.json (structural, coverage) and optionally detailed.json
(confidence, alignment quality). Categories mirror the inspector's accordion
panels in the same order:

  1.  Failed Alignments
  2.  Missing Verses
  3.  Missing Words
  4.  Structural Errors
  5.  Low Confidence
  6.  Detected Repetitions
  7.  May Require Boundary Adjustment
  8.  Cross-verse
  9.  Audio Bleeding
  10. Muqatta'at
  11. Qalqala

Usage:
    python validators/validate_segments.py <reciter_dir>        # single reciter → detailed report
    python validators/validate_segments.py <parent_dir>         # all reciter subdirs → summary table
    python validators/validate_segments.py <dir> --top 50       # show top 50 per category
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

# Make ``inspector/`` packages importable so the CLI shares the unified
# classifier with the backend / tests.
_INSPECTOR_DIR = _PROJECT_ROOT / "inspector"
if str(_INSPECTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_INSPECTOR_DIR))

from services.validation import (  # noqa: E402  — sys.path setup must precede imports
    classify_segment_full,
    is_ignored_for,
)
from utils.arabic_text import last_arabic_letter as _last_arabic_letter  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────


def _rel_path(p: Path) -> str:
    try:
        return str(p.relative_to(_PROJECT_ROOT))
    except ValueError:
        return p.name


def _ms_to_hms(ms: float) -> str:
    total_s = ms / 1000.0
    h = int(total_s // 3600)
    m = int((total_s % 3600) // 60)
    s = total_s % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:04.1f}"
    return f"{m}:{s:04.1f}"


def _ms_to_s(ms: float) -> str:
    return f"{ms / 1000:.2f}s"


# ── Parsers ──────────────────────────────────────────────────────────────


def load_word_counts(surah_info_path: Path) -> dict[tuple[int, int], int]:
    with open(surah_info_path, encoding="utf-8") as f:
        info = json.load(f)
    wc = {}
    for surah_str, data in info.items():
        surah = int(surah_str)
        for v in data["verses"]:
            wc[(surah, v["verse"])] = v["num_words"]
    return wc


def parse_segments(path: Path) -> tuple[dict[str, list[list]], dict]:
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.pop("_meta", {})
    return doc, meta


def parse_detailed(path: Path) -> list[dict]:
    segments = []
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    for entry in doc.get("entries", []):
        audio = entry.get("audio", "")
        ref = entry.get("ref", "")  # entry-level ref ("1:1" for by_ayah, "1" for by_surah)
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
            if seg.get("ignored_categories"):
                d["ignored_categories"] = list(seg["ignored_categories"])
            elif seg.get("ignored"):
                d["ignored_categories"] = ["_all"]
            segments.append(d)
    return segments


def parse_detailed_raw(path: Path) -> tuple[list[dict], dict]:
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.get("_meta", {})
    return doc.get("entries", []), meta


def _build_verse_audio_map(detailed_segs: list[dict]) -> dict[str, str]:
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
    matched = [s for s in detailed_segs if s["matched_ref"]]
    failed = [s for s in detailed_segs if not s["matched_ref"]]
    empty_phonemes = [s for s in matched if not s.get("phonemes_asr", "").strip()]
    confidences = [s["confidence"] for s in matched]
    lc_visible = [s for s in matched if not is_ignored_for(s, "low_confidence")]
    return {
        "matched": matched,
        "failed": failed,
        "empty_phonemes": empty_phonemes,
        "conf_min": min(confidences) if confidences else 0,
        "conf_med": statistics.median(confidences) if confidences else 0,
        "conf_mean": statistics.mean(confidences) if confidences else 0,
        "conf_max": max(confidences) if confidences else 0,
        "conf_below_60": sum(1 for s in lc_visible if s["confidence"] < 0.60),
        "conf_below_80": sum(1 for s in lc_visible if s["confidence"] < 0.80),
        "failed_segments": len(failed),
        "empty_phonemes_count": len(empty_phonemes),
    }


def _classify_detailed_segs(
    detailed_segs: list[dict],
    word_counts: dict[tuple[int, int], int],
    is_by_ayah: bool,
) -> dict[str, list[dict]]:
    """Classify segments into inspector accordion category buckets.

    Routes through the unified ``services.validation.classify_segment_full``
    so the CLI shares the same predicates as the backend route and history
    snapshots. Output buckets match the legacy CLI shape so the report
    formatter below stays unchanged.
    """
    single_word_verses = {k for k, v in word_counts.items() if v == 1}

    buckets: dict[str, list[dict]] = {
        "repetitions": [],
        "boundary_adj": [],
        "cross_verse_det": [],
        "audio_bleeding": [],
        "muqattaat": [],
        "qalqala": [],
    }

    for seg in detailed_segs:
        if not seg.get("matched_ref"):
            continue  # failed alignments tracked via _confidence_stats

        info = classify_segment_full(
            seg,
            entry_ref=seg.get("ref", ""),
            is_by_ayah=is_by_ayah,
            single_word_verses=single_word_verses,
        )
        cats = set(info["categories"])
        if "repetitions" in cats:
            buckets["repetitions"].append(seg)
        if "boundary_adj" in cats:
            buckets["boundary_adj"].append(seg)
        if "cross_verse" in cats:
            buckets["cross_verse_det"].append(seg)
        if "audio_bleeding" in cats:
            # Build the same enriched display dict the backend route emits.
            sp = seg["matched_ref"].split("-")[0].split(":")
            matched_verse = f"{sp[0]}:{sp[1]}" if len(sp) >= 2 else seg["matched_ref"]
            buckets["audio_bleeding"].append({**seg, "matched_verse": matched_verse})
        if "muqattaat" in cats:
            buckets["muqattaat"].append(seg)
        if "qalqala" in cats:
            buckets["qalqala"].append(seg)

    return buckets


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
    is_by_ayah = "by_ayah" in meta.get("audio_source", "")

    errors = []
    warnings = []
    seg_durations = []
    pause_durations = []
    single_seg = 0
    multi_seg_verses = 0
    multi_seg_segs = 0
    max_segs = 0
    total_segments = 0
    cross_verse_keys = 0
    empty_verse_keys = 0

    # ── Meta validation ──
    meta_fields = {"created_at", "asr_model", "vad_model", "pad_ms", "min_silence_ms", "min_speech_ms", "audio_source"}
    if not meta:
        errors.append({"msg": "_meta missing or empty", "verse_key": "", "t_from": 0, "t_to": 0})
    else:
        missing_meta = meta_fields - set(meta.keys())
        if missing_meta:
            warnings.append({"msg": f"_meta missing fields: {sorted(missing_meta)}",
                             "verse_key": "", "t_from": 0, "t_to": 0})

    covered_per_verse: dict[tuple[int, int], set[int]] = defaultdict(set)

    for verse_key, segs in verses.items():
        is_cross_verse = "-" in verse_key
        if is_cross_verse:
            cross_verse_keys += 1
        n_segs = len(segs)
        total_segments += n_segs
        max_segs = max(max_segs, n_segs)

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

        for i, seg in enumerate(segs):
            w_from, w_to, t_from, t_to = seg[0], seg[1], seg[2], seg[3]
            seg_durations.append(t_to - t_from)

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

        if is_cross_verse:
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
            parts = verse_key.split(":")
            surah, ayah = int(parts[0]), int(parts[1])
            for seg in segs:
                covered_per_verse[(surah, ayah)].update(range(seg[0], seg[1] + 1))

    # Build full verse set from all keys
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

    # Word coverage warnings
    for (surah, ayah) in sorted(all_verses_in_file):
        expected_words = word_counts.get((surah, ayah))
        if expected_words is None:
            continue
        covered_words = covered_per_verse.get((surah, ayah), set())
        expected_set = set(range(1, expected_words + 1))
        missing = expected_set - covered_words
        extra = covered_words - expected_set
        vk = f"{surah}:{ayah}"
        vk_t_from = vk_t_to = 0
        for k, s in verses.items():
            if vk == k or (("-" in k) and any(f"{surah}:{ayah}" in p for p in k.split("-"))):
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

    # Missing verses — only within surahs that have at least one verse present
    covered_surahs = {surah for (surah, _) in all_verses_in_file}
    missing_verses = []
    for (surah, ayah) in sorted(word_counts):
        if surah not in covered_surahs:
            continue
        if (surah, ayah) not in all_verses_in_file:
            missing_verses.append(f"{surah}:{ayah}")

    word_gap_warnings = [w for w in warnings if "missing words" in w["msg"]]

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
        "word_gaps": len(word_gap_warnings),
        "errors": len(errors),
        "warnings": len(warnings),
    }

    # ── detailed.json: confidence stats + accordion categories ──
    has_detailed = detailed_path.exists()
    detailed_segs = []
    categories: dict[str, list] = {}
    if has_detailed:
        detailed_segs = parse_detailed(detailed_path)
        cstats = _confidence_stats(detailed_segs)
        for k in ["conf_min", "conf_med", "conf_mean", "conf_max",
                   "conf_below_60", "conf_below_80", "failed_segments",
                   "empty_phonemes_count"]:
            stats[k] = cstats[k]
        categories = _classify_detailed_segs(detailed_segs, word_counts, is_by_ayah)
        stats["repetitions"] = len(categories["repetitions"])
        stats["boundary_adj"] = len(categories["boundary_adj"])
        stats["cross_verse_det"] = len(categories["cross_verse_det"])
        stats["audio_bleeding"] = len(categories["audio_bleeding"])
        stats["muqattaat"] = len(categories["muqattaat"])
        stats["qalqala"] = len(categories["qalqala"])
    else:
        for k in ["conf_min", "conf_med", "conf_mean", "conf_max",
                   "conf_below_60", "conf_below_80", "failed_segments",
                   "empty_phonemes_count", "repetitions", "boundary_adj",
                   "cross_verse_det", "audio_bleeding", "muqattaat", "qalqala"]:
            stats[k] = 0

    # ── Cross-file consistency: detailed.json ↔ segments.json ──
    consistency_mismatches = 0
    if has_detailed:
        raw_entries, _ = parse_detailed_raw(detailed_path)
        rebuilt: dict[str, list] = defaultdict(list)
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
                except ValueError:
                    continue
                vk = f"{sp[0]}:{sp[1]}" if s_ayah == e_ayah else matched_ref
                rebuilt[vk].append(seg)

        seg_only = set(verses.keys()) - set(rebuilt.keys())
        det_only = set(rebuilt.keys()) - set(verses.keys())
        consistency_mismatches += len(seg_only) + len(det_only)
        for vk in sorted(set(verses.keys()) & set(rebuilt.keys())):
            if len(verses[vk]) != len(rebuilt[vk]):
                consistency_mismatches += 1

    stats["consistency_mismatches"] = consistency_mismatches

    if verbose:
        _print_verbose(reciter, reciter_dir, stats, meta, errors, warnings,
                       missing_verses, word_gap_warnings, word_counts,
                       pause_durations, has_detailed, detailed_segs, categories, top_n)

    return stats


# ── Verbose single-reciter report ────────────────────────────────────────


def _print_verbose(reciter, reciter_dir, stats, meta, errors, warnings,
                   missing_verses, word_gap_warnings, word_counts,
                   pause_durations, has_detailed, detailed_segs, categories, top_n):
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
    print(f"  Verses found:   {stats['verses']} / {stats['total_verses']}")
    print(f"  Missing verses: {stats['missing']}")
    print(f"  Word gaps:      {stats['word_gaps']} verses")

    # ── Segments ──
    print(f"\n--- Segments ---")
    print(f"  Total:            {stats['segments']}")
    print(f"  Single-seg:       {stats['single']}")
    print(f"  Multi-seg verses: {stats['multi_verses']} ({stats['multi_segs']} segs)")
    print(f"  Cross-verse keys: {stats['cross_verse']}")
    print(f"  Max segs/verse:   {stats['max_segs']}")

    # ── Durations ──
    print(f"\n--- Segment Duration ---")
    print(f"  Min:    {_ms_to_s(stats['seg_dur_min'])}")
    print(f"  Median: {_ms_to_s(stats['seg_dur_med'])}")
    print(f"  Mean:   {_ms_to_s(stats['seg_dur_mean'])}")
    print(f"  Max:    {_ms_to_s(stats['seg_dur_max'])}")

    print(f"\n--- True Silence Duration (padding reversed) ---")
    if pause_durations:
        print(f"  Min:    {_ms_to_s(stats['pause_dur_min'])}")
        print(f"  Median: {_ms_to_s(stats['pause_dur_med'])}")
        print(f"  Mean:   {_ms_to_s(stats['pause_dur_mean'])}")
        print(f"  Max:    {_ms_to_s(stats['pause_dur_max'])}")
    else:
        print(f"  (no multi-segment verses)")

    # ── Confidence summary ──
    if has_detailed:
        print(f"\n--- Alignment Confidence ---")
        print(f"  Min:       {stats['conf_min']:.4f}")
        print(f"  Median:    {stats['conf_med']:.4f}")
        print(f"  Mean:      {stats['conf_mean']:.4f}")
        print(f"  Max:       {stats['conf_max']:.4f}")
        print(f"  Below 60%: {stats['conf_below_60']}")
        print(f"  Below 80%: {stats['conf_below_80']}")
        print(f"  Failed:    {stats['failed_segments']} (no alignment)")
        print(f"  Empty ASR: {stats['empty_phonemes_count']} (matched but no phonemes)")
    else:
        print(f"\n--- Alignment Confidence ---")
        print(f"  (no detailed.json)")

    # ── Inspector Accordion Sections ─────────────────────────────────────

    verse_audio: dict[str, str] = _build_verse_audio_map(detailed_segs) if has_detailed else {}

    def _seg_line(s: dict, label: str | None = None) -> None:
        ref = label or s.get("matched_ref", s.get("ref", ""))
        conf = s.get("confidence", 0.0)
        print(f"  [{conf:.4f}]  {ref}  @ {_ms_to_hms(s['time_start'])} - {_ms_to_hms(s['time_end'])}")
        if s.get("audio"):
            print(f"           audio: {s['audio']}")
        if s.get("matched_text"):
            print(f"           text:  {s['matched_text']}")

    # 1. Failed Alignments
    if has_detailed:
        cstats = _confidence_stats(detailed_segs)
        failed = cstats["failed"]
        n = len(failed)
        print(f"\n--- Failed Alignments ({n}) ---")
        for s in failed[:top_n]:
            print(f"  {_ms_to_hms(s['time_start'])} - {_ms_to_hms(s['time_end'])}  ({_ms_to_s(s['time_end'] - s['time_start'])})")
            if s.get("audio"):
                print(f"    audio: {s['audio']}")
            if s.get("phonemes_asr"):
                print(f"    asr:   {s['phonemes_asr']}")
        if n > top_n:
            print(f"  ... and {n - top_n} more")

    # 2. Missing Verses
    n = len(missing_verses)
    if n:
        print(f"\n--- Missing Verses ({n}) ---")
        for v in missing_verses[:top_n]:
            nw = word_counts.get(tuple(int(x) for x in v.split(":")), "?")
            print(f"  MISS  {v}  ({nw} words)")
        if n > top_n:
            print(f"  ... and {n - top_n} more")

    # 3. Missing Words
    n = len(word_gap_warnings)
    if n:
        print(f"\n--- Missing Words ({n}) ---")
        for w in word_gap_warnings[:top_n]:
            audio = verse_audio.get(w["verse_key"], "")
            print(f"  {w['verse_key']}  @ {_ms_to_hms(w['t_from'])} - {_ms_to_hms(w['t_to'])}")
            print(f"    {w['msg']}")
            if audio:
                print(f"    audio: {audio}")
        if n > top_n:
            print(f"  ... and {n - top_n} more")

    # 4. Structural Errors
    n = len(errors)
    if n:
        print(f"\n--- Structural Errors ({n}) ---")
        for e in errors[:top_n]:
            audio = verse_audio.get(e["verse_key"], "")
            print(f"  ERROR  {e['verse_key']}  @ {_ms_to_hms(e['t_from'])} - {_ms_to_hms(e['t_to'])}")
            print(f"    {e['msg']}")
            if audio:
                print(f"    audio: {audio}")
        if n > top_n:
            print(f"  ... and {n - top_n} more")

    if has_detailed:
        cstats = _confidence_stats(detailed_segs)

        # 5. Low Confidence (<80%)
        below_80 = sorted(
            [
                s for s in cstats["matched"]
                if s["confidence"] < 0.80 and not is_ignored_for(s, "low_confidence")
            ],
            key=lambda s: s["confidence"],
        )
        n = len(below_80)
        if n:
            print(f"\n--- Low Confidence <80% ({n}) ---")
            for s in below_80[:top_n]:
                _seg_line(s)
            if n > top_n:
                print(f"  ... and {n - top_n} more")

        # 6. Detected Repetitions
        rep = categories.get("repetitions", [])
        n = len(rep)
        if n:
            print(f"\n--- Detected Repetitions ({n}) ---")
            for s in rep[:top_n]:
                _seg_line(s)
            if n > top_n:
                print(f"  ... and {n - top_n} more")

        # 7. May Require Boundary Adjustment
        ba = categories.get("boundary_adj", [])
        n = len(ba)
        if n:
            print(f"\n--- May Require Boundary Adjustment ({n}) ---")
            for s in ba[:top_n]:
                _seg_line(s)
            if n > top_n:
                print(f"  ... and {n - top_n} more")

        # 8. Cross-verse
        cv = categories.get("cross_verse_det", [])
        n = len(cv)
        if n:
            print(f"\n--- Cross-verse ({n}) ---")
            for s in cv[:top_n]:
                _seg_line(s)
            if n > top_n:
                print(f"  ... and {n - top_n} more")

        # 9. Audio Bleeding
        ab = categories.get("audio_bleeding", [])
        n = len(ab)
        if n:
            print(f"\n--- Audio Bleeding ({n}) ---")
            for s in ab[:top_n]:
                entry_ref = s.get("ref", "?")
                matched_v = s.get("matched_verse", "?")
                _seg_line(s, label=f"{entry_ref} → {matched_v}  ({s.get('matched_ref', '')})")
            if n > top_n:
                print(f"  ... and {n - top_n} more")

        # 10. Muqatta'at
        mq = categories.get("muqattaat", [])
        n = len(mq)
        if n:
            print(f"\n--- Muqatta'at ({n}) ---")
            for s in mq[:top_n]:
                _seg_line(s)
            if n > top_n:
                print(f"  ... and {n - top_n} more")

        # 11. Qalqala
        ql = categories.get("qalqala", [])
        n = len(ql)
        if n:
            print(f"\n--- Qalqala ({n}) ---")
            for s in ql[:top_n]:
                last_ltr = _last_arabic_letter(s.get("matched_text", "")) or "?"
                _seg_line(s, label=f"{s.get('matched_ref', '')}  [{last_ltr}]")
            if n > top_n:
                print(f"  ... and {n - top_n} more")

        # Empty ASR (not an accordion, but useful diagnostic)
        empty_ph = cstats["empty_phonemes"]
        if empty_ph:
            n = len(empty_ph)
            print(f"\n--- Empty ASR Phonemes ({n}) ---")
            for s in empty_ph[:top_n]:
                _seg_line(s)
            if n > top_n:
                print(f"  ... and {n - top_n} more")

    # ── Cross-file Consistency ──
    if has_detailed:
        print(f"\n--- Cross-file Consistency (detailed.json ↔ segments.json) ---")
        print(f"  Mismatches: {stats.get('consistency_mismatches', 0)}")

    # Machine-readable category-counts footer. Each line has the canonical
    # registry-key form (matches the backend route's ``category_counts``)
    # so cross-stack parity tests can grep one stable shape.
    if has_detailed:
        print("\n--- Category Counts (machine-readable) ---")
        cat_count_pairs = [
            ("failed", stats.get("failed_segments", 0)),
            ("missing_verses", len(missing_verses)),
            ("missing_words", stats.get("word_gaps", 0)),
            ("structural_errors", len(errors)),
            ("low_confidence", stats.get("conf_below_80", 0)),
            ("repetitions", stats.get("repetitions", 0)),
            ("audio_bleeding", stats.get("audio_bleeding", 0)),
            ("boundary_adj", stats.get("boundary_adj", 0)),
            ("cross_verse", stats.get("cross_verse_det", 0)),
            ("qalqala", stats.get("qalqala", 0)),
            ("muqattaat", stats.get("muqattaat", 0)),
        ]
        for key, count in cat_count_pairs:
            print(f"  {key} {count}")

    # ── Other Warnings (extra words, meta, etc.) ──
    other_warnings = [w for w in warnings if "missing words" not in w["msg"]]
    if other_warnings:
        print(f"\n--- Other Warnings ({len(other_warnings)}) ---")
        for w in other_warnings[:top_n]:
            print(f"  WARN  {w['verse_key']}  {w['msg']}")
        if len(other_warnings) > top_n:
            print(f"  ... and {len(other_warnings) - top_n} more")

    print()


# ── Summary table (multi-reciter) ───────────────────────────────────────


def _print_row(reciter: str, cols: list[str], widths: list[int]):
    parts = [f"{reciter:<35}"]
    for val, w in zip(cols, widths):
        parts.append(f"{val:>{w}}")
    print(" ".join(parts))


def print_table(all_stats: list[dict]):
    """Print summary tables across all reciters."""
    sorted_stats = sorted(all_stats, key=lambda x: x["reciter"])
    total_label = f"TOTAL ({len(all_stats)} reciters)"

    # --- Table 1: Segments ---
    print("=== Segments ===\n")
    seg_hdrs = ["Verses", "Total Segs", "Single", "Multi (segs)", "Cross-V", "Max/V", "Missing", "Wrd Gaps", "Errors"]
    seg_ws = [6, 10, 6, 12, 7, 5, 7, 8, 6]
    _print_row("Reciter", seg_hdrs, seg_ws)
    print("-" * (35 + sum(w + 1 for w in seg_ws)))

    totals = {k: 0 for k in ["verses", "segments", "single", "multi_verses", "multi_segs",
                               "cross_verse", "missing", "word_gaps", "errors"]}
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
    _print_row(total_label, [
        str(totals["verses"]), str(totals["segments"]), str(totals["single"]),
        f"{totals['multi_verses']} ({totals['multi_segs']})", str(totals["cross_verse"]), "",
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
    _print_row(total_label, ["", f"{statistics.median(all_med) if all_med else 0:.1f}", "", ""], dur_ws)

    # --- Table 3: True Silence Duration ---
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
    _print_row(total_label, ["", f"{statistics.median(all_pause_med) if all_pause_med else 0:.1f}", "", ""], dur_ws)

    # --- Table 4: Confidence ---
    has_any_detailed = any(s["conf_mean"] > 0 for s in sorted_stats)
    if has_any_detailed:
        print("\n\n=== Alignment Confidence ===\n")
        conf_hdrs = ["Min", "Median", "Mean", "Max", "Below 60%", "Below 80%", "Failed", "Empty ASR"]
        conf_ws = [6, 6, 6, 6, 9, 9, 6, 9]
        _print_row("Reciter", conf_hdrs, conf_ws)
        print("-" * (35 + sum(w + 1 for w in conf_ws)))
        all_conf_med = []
        tot = {k: 0 for k in ["conf_below_60", "conf_below_80", "failed_segments", "empty_phonemes_count"]}
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
                _print_row(s["reciter"], ["n/a"] * 8, conf_ws)
            for k in tot:
                tot[k] += s[k]
        print("-" * (35 + sum(w + 1 for w in conf_ws)))
        _print_row(total_label, [
            "", f"{statistics.median(all_conf_med) if all_conf_med else 0:.2f}", "", "",
            str(tot["conf_below_60"]), str(tot["conf_below_80"]),
            str(tot["failed_segments"]), str(tot["empty_phonemes_count"]),
        ], conf_ws)

    # --- Table 5: Validation Categories (from detailed.json) ---
    if has_any_detailed:
        print("\n\n=== Validation Categories ===\n")
        cat_hdrs = ["Failed", "Rep", "BndAdj", "CrossV", "Bleed", "Muqt", "Qalq"]
        cat_ws = [6, 5, 6, 6, 5, 5, 5]
        _print_row("Reciter", cat_hdrs, cat_ws)
        print("-" * (35 + sum(w + 1 for w in cat_ws)))
        cat_totals = {k: 0 for k in ["failed_segments", "repetitions", "boundary_adj",
                                       "cross_verse_det", "audio_bleeding", "muqattaat", "qalqala"]}
        for s in sorted_stats:
            _print_row(s["reciter"], [
                str(s["failed_segments"]), str(s["repetitions"]),
                str(s["boundary_adj"]), str(s["cross_verse_det"]),
                str(s["audio_bleeding"]), str(s["muqattaat"]), str(s["qalqala"]),
            ], cat_ws)
            for k in cat_totals:
                cat_totals[k] += s[k]
        print("-" * (35 + sum(w + 1 for w in cat_ws)))
        _print_row(total_label, [
            str(cat_totals["failed_segments"]), str(cat_totals["repetitions"]),
            str(cat_totals["boundary_adj"]), str(cat_totals["cross_verse_det"]),
            str(cat_totals["audio_bleeding"]), str(cat_totals["muqattaat"]),
            str(cat_totals["qalqala"]),
        ], cat_ws)

    # --- Table 6: Cross-file Consistency ---
    has_any_consistency = any(
        s.get("consistency_mismatches", 0) > 0 or s.get("empty_verse_keys", 0) > 0
        for s in sorted_stats
    )
    if has_any_consistency:
        print("\n\n=== Cross-file Consistency ===\n")
        con_hdrs = ["Empty Keys", "Det↔Seg MM"]
        con_ws = [10, 10]
        _print_row("Reciter", con_hdrs, con_ws)
        print("-" * (35 + sum(w + 1 for w in con_ws)))
        total_empty = total_mm = 0
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
    buf = io.StringIO()
    orig = sys.stdout

    # Console encoding fallback: on Windows, ``sys.stdout`` defaults to
    # cp1252 and chokes on Arabic text in matched_text output. Coerce to
    # utf-8 with replacement so the CLI never crashes on terminal encoding —
    # the on-disk validation.log still receives the unmodified text.
    orig_encoding = (getattr(orig, "encoding", None) or "").lower()

    def _safe_write_to_orig(s: str) -> None:
        try:
            orig.write(s)
        except UnicodeEncodeError:
            orig.write(s.encode(orig_encoding or "ascii", errors="replace").decode(orig_encoding or "ascii", errors="replace"))

    class _Tee:
        def write(self, s):
            _safe_write_to_orig(s)
            buf.write(s)
        def flush(self):
            try:
                orig.flush()
            except Exception:
                pass

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
    )
    parser.add_argument("--top", "-n", type=int, default=30,
                        help="Items to show per category (default: 30)")
    args = parser.parse_args()

    word_counts = load_word_counts(args.surah_info)
    target = args.path.resolve()

    # Slug fallback: if the positional argument doesn't resolve to an
    # existing directory, look it up under
    # ``$INSPECTOR_DATA_DIR/recitation_segments/<slug>``. Lets callers
    # invoke the CLI with a bare reciter slug when the data dir is
    # configured via the standard inspector env var.
    if not target.is_dir():
        import os
        data_dir = os.environ.get("INSPECTOR_DATA_DIR")
        if data_dir:
            candidate = Path(data_dir) / "recitation_segments" / str(args.path)
            if candidate.is_dir():
                target = candidate.resolve()

    if not target.is_dir():
        print(f"Path not found or not a directory: {_rel_path(target)}")
        return

    if (target / "segments.json").exists():
        report_path = target / "validation.log"
        with _tee_to_file(report_path):
            validate_reciter(target, word_counts, verbose=True, top_n=args.top)
        print(f"Report saved to {_rel_path(report_path)}")
        print(f"Run  python inspector/server.py  to visually inspect and edit segments in the browser.")
        return

    subdirs = sorted(d for d in target.iterdir() if d.is_dir() and (d / "segments.json").exists())
    if not subdirs:
        print(f"No reciter subdirectories with segments.json found in {_rel_path(target)}")
        return

    all_stats = []
    for d in subdirs:
        per_report = d / "validation.log"
        with _tee_to_file(per_report):
            stats = validate_reciter(d, word_counts, verbose=True, top_n=args.top)
        all_stats.append(stats)
        print(f"  {d.name}: saved to {_rel_path(per_report)}")

    report_path = target / "validation.log"
    with _tee_to_file(report_path):
        print_table(all_stats)
    print(f"\nSummary saved to {_rel_path(report_path)}")
    print(f"Run  python inspector/server.py  to visually inspect and edit segments in the browser.")


if __name__ == "__main__":
    main()
