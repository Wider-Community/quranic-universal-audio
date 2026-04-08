"""Validate MFA forced alignment timestamp output.

Reads ``timestamps.json`` (word-level) and optionally ``timestamps_full.json``
(word + letter + phone level) for structural correctness, duration plausibility,
and cross-file consistency with the segment pipeline output.

Usage:
    python validate_timestamps.py <reciter_dir>        # single reciter → detailed report
    python validate_timestamps.py <parent_dir>         # all reciter subdirs → summary table
    python validate_timestamps.py <dir> --top 50       # show top 50 issues
"""

import argparse
import io
import json
import statistics
import sys
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


def parse_timestamps(path: Path) -> tuple[dict[str, list[list]], dict]:
    """Parse timestamps.json → (verses, meta).

    verses: {verse_key: [[word_idx, start_ms, end_ms], ...]}
    meta: dict from _meta line
    """
    with open(path, encoding="utf-8-sig") as f:
        doc = json.load(f)
    meta = doc.pop("_meta", {})
    return doc, meta


def parse_timestamps_full(path: Path) -> tuple[dict[str, dict], dict]:
    """Parse timestamps_full.json → (verses, meta).

    verses: {verse_key: {"words": [[idx, start, end, letters, phones], ...]}}
    where letters = [[char, start, end], ...] and phones = [[phone, start, end], ...]
    (phones nested per word; legacy format with verse-level "phones" also supported)
    meta: dict from _meta line
    """
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.pop("_meta", {})
    return doc, meta


def parse_segments(path: Path) -> tuple[dict[str, list[list]], dict]:
    """Parse segments.json → (verses, meta).

    verses: {verse_key: [[w_from, w_to, t_from_ms, t_to_ms], ...]}
    meta: dict from _meta line
    """
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.pop("_meta", {})
    return doc, meta


# ── Core validation ─────────────────────────────────────────────────────


def validate_reciter(
    reciter_dir: Path,
    word_counts: dict[tuple[int, int], int],
    verbose: bool = False,
    top_n: int = 30,
) -> dict:
    """Validate a single reciter directory containing timestamps files."""
    ts_path = reciter_dir / "timestamps.json"
    ts_full_path = reciter_dir / "timestamps_full.json"
    reciter = reciter_dir.name

    if not ts_path.exists():
        if verbose:
            print(f"  {reciter}: timestamps.json not found, skipping")
        return {"reciter": reciter, "skipped": True}

    verses, meta = parse_timestamps(ts_path)

    has_full = ts_full_path.exists()
    full_verses = {}
    if has_full:
        full_verses, _ = parse_timestamps_full(ts_full_path)

    errors = []
    warnings = []
    word_durations = []

    # ── 1. Structural / Integrity ──

    # Meta check
    meta_fields = {"created_at", "aligner_model", "audio_source", "method", "beam", "retry_beam", "shared_cmvn", "padding"}
    missing_meta = meta_fields - set(meta.keys())
    if not meta:
        errors.append({"msg": "_meta line missing or empty", "verse_key": ""})
    elif missing_meta:
        warnings.append({"msg": f"_meta missing fields: {sorted(missing_meta)}", "verse_key": ""})

    # MFA failures recorded during extraction
    mfa_failures = meta.get("mfa_failures", [])
    for fail in mfa_failures:
        errors.append({
            "msg": f"MFA failed: seg {fail.get('seg', '?')} "
                   f"ref={fail.get('ref', '?')} error={fail.get('error', '?')}",
            "verse_key": fail.get("verse", ""),
        })

    # Verse coverage — handle both regular "surah:ayah" and compound
    # "surah:ayah:word-surah:ayah:word" keys (cross-verse segments)
    all_verse_keys = set()
    for vk in verses:
        if "-" in vk:
            # Compound key like "37:151:3-37:152:2"
            try:
                start_part, end_part = vk.split("-", 1)
                sp = start_part.split(":")
                ep = end_part.split(":")
                start_surah, start_ayah = int(sp[0]), int(sp[1])
                end_surah, end_ayah = int(ep[0]), int(ep[1])
                for a in range(start_ayah, end_ayah + 1):
                    all_verse_keys.add((start_surah, a))
            except (ValueError, IndexError):
                errors.append({"msg": f"invalid compound key format: {vk}", "verse_key": vk})
        else:
            parts = vk.split(":")
            if len(parts) == 2:
                try:
                    all_verse_keys.add((int(parts[0]), int(parts[1])))
                except ValueError:
                    errors.append({"msg": f"invalid verse key format: {vk}", "verse_key": vk})

    missing_verses = []
    for sa in sorted(word_counts):
        if sa not in all_verse_keys:
            missing_verses.append(f"{sa[0]}:{sa[1]}")

    # Per-verse checks — two phases:
    # Phase 1: temporal checks on all keys + accumulate word coverage
    # Phase 2: evaluate coverage per verse after all keys processed
    word_coverage_issues = 0
    forward_gap_verses = 0
    zero_duration_words = 0
    negative_timestamps = 0

    # Accumulated coverage across all keys (regular + compound)
    covered_per_verse: dict[tuple[int, int], set[int]] = {}

    for verse_key, words in verses.items():
        is_compound = "-" in verse_key

        # Parse verse key
        if is_compound:
            try:
                start_part, end_part = verse_key.split("-", 1)
                sp = start_part.split(":")
                ep = end_part.split(":")
                start_surah, start_ayah = int(sp[0]), int(sp[1])
                end_ayah = int(ep[1])
            except (ValueError, IndexError):
                continue
        else:
            parts = verse_key.split(":")
            if len(parts) != 2:
                continue
            try:
                start_surah, start_ayah = int(parts[0]), int(parts[1])
                end_ayah = start_ayah
            except ValueError:
                continue

        indices = [w[0] for w in words]

        # Accumulate word coverage per verse
        if is_compound:
            # Walk word list detecting verse boundary crossings
            # (word_idx drops indicate new verse)
            cur_ayah = start_ayah
            prev_idx = -1
            for w in words:
                idx = w[0]
                if prev_idx >= 0 and idx <= prev_idx and cur_ayah < end_ayah:
                    cur_ayah += 1
                sa = (start_surah, cur_ayah)
                if sa not in covered_per_verse:
                    covered_per_verse[sa] = set()
                covered_per_verse[sa].add(idx)
                prev_idx = idx
        else:
            sa = (start_surah, start_ayah)
            if sa not in covered_per_verse:
                covered_per_verse[sa] = set()
            covered_per_verse[sa].update(indices)

        # Forward gap detection
        if is_compound:
            # For compound keys, run gap detection per-verse (reset hwm at boundaries)
            cur_ayah = start_ayah
            prev_idx = -1
            hwm = None
            all_gaps = []
            for w in words:
                idx = w[0]
                if prev_idx >= 0 and idx <= prev_idx and cur_ayah < end_ayah:
                    cur_ayah += 1
                    hwm = None  # reset at verse boundary
                if hwm is None:
                    hwm = idx
                elif idx > hwm:
                    if idx > hwm + 1:
                        all_gaps.append((hwm, idx))
                    hwm = idx
                prev_idx = idx
            if all_gaps:
                forward_gap_verses += 1
                gap_strs = [f"{a}→{b}" for a, b in all_gaps[:3]]
                suffix = f" (+{len(all_gaps) - 3} more)" if len(all_gaps) > 3 else ""
                warnings.append({
                    "msg": f"forward gaps in word indices: {', '.join(gap_strs)}{suffix}",
                    "verse_key": verse_key,
                })
        else:
            if indices:
                hwm = indices[0]
                gaps = []
                for idx in indices[1:]:
                    if idx > hwm:
                        if idx > hwm + 1:
                            gaps.append((hwm, idx))
                        hwm = idx
                if gaps:
                    forward_gap_verses += 1
                    gap_strs = [f"{a}→{b}" for a, b in gaps[:3]]
                    suffix = f" (+{len(gaps) - 3} more)" if len(gaps) > 3 else ""
                    warnings.append({
                        "msg": f"forward gaps in word indices: {', '.join(gap_strs)}{suffix}",
                        "verse_key": verse_key,
                    })

        # Temporal checks per word (key-format-agnostic)
        for w in words:
            idx, start, end = w[0], w[1], w[2]
            if start < 0 or end < 0:
                negative_timestamps += 1
                errors.append({
                    "msg": f"word {idx}: negative timestamp start={start} end={end}",
                    "verse_key": verse_key,
                })
            elif start == end:
                zero_duration_words += 1
                warnings.append({
                    "msg": f"word {idx}: zero duration at {_ms_to_hms(start)}",
                    "verse_key": verse_key,
                })
            elif start > end:
                errors.append({
                    "msg": f"word {idx}: start ({_ms_to_hms(start)}) > end ({_ms_to_hms(end)})",
                    "verse_key": verse_key,
                })
            else:
                word_durations.append(end - start)

    # Phase 2: Word coverage validation (after all keys processed)
    for sa in sorted(word_counts):
        expected = word_counts[sa]
        covered = covered_per_verse.get(sa, set())
        if not covered:
            continue  # entirely missing verse — already in missing_verses
        expected_set = set(range(1, expected + 1))
        missing_idx = sorted(expected_set - covered)
        extra_idx = sorted(covered - expected_set)
        verse_key_label = f"{sa[0]}:{sa[1]}"
        if missing_idx:
            word_coverage_issues += 1
            warnings.append({
                "msg": f"missing word indices: {missing_idx}",
                "verse_key": verse_key_label,
            })
        if extra_idx:
            word_coverage_issues += 1
            warnings.append({
                "msg": f"extra word indices beyond {expected}: {extra_idx}",
                "verse_key": verse_key_label,
            })

    # ── 3. Temporal checks on full format (letters/phones) ──
    # NOTE: Letter duration sums intentionally not compared to word spans.
    # MFA geminates, idgham, and cross-word assimilation cause letters to
    # overlap or extend beyond word boundaries — this is expected behavior.

    letter_negative = 0
    phone_issues = 0
    if has_full:
        for verse_key, data in full_verses.items():
            for w in data.get("words", []):
                if len(w) < 4:
                    continue
                for lt in w[3]:
                    if lt[1] is not None and lt[2] is not None:
                        if lt[1] < 0 or lt[2] < 0:
                            letter_negative += 1
                        elif lt[1] > lt[2]:
                            letter_negative += 1
                            errors.append({
                                "msg": f"word {w[0]} letter '{lt[0]}': "
                                       f"start ({lt[1]}) > end ({lt[2]})",
                                "verse_key": verse_key,
                            })
                # Per-word phone checks (new nested format: w[4])
                if len(w) > 4:
                    phones = w[4]
                    for ph in phones:
                        if ph[1] is not None and ph[2] is not None:
                            if ph[1] < 0 or ph[2] < 0:
                                phone_issues += 1
                            elif ph[1] > ph[2]:
                                phone_issues += 1
                                errors.append({
                                    "msg": f"word {w[0]} phone '{ph[0]}': "
                                           f"start ({ph[1]}) > end ({ph[2]})",
                                    "verse_key": verse_key,
                                })
                    # Check phone ordering within word
                    for i in range(1, len(phones)):
                        if (phones[i][1] is not None and phones[i-1][2] is not None
                                and phones[i][1] < phones[i-1][1]):
                            phone_issues += 1
                            warnings.append({
                                "msg": f"word {w[0]} phones out of order: "
                                       f"'{phones[i-1][0]}' then '{phones[i][0]}'",
                                "verse_key": verse_key,
                            })
                            break  # one warning per word

    # ── 4. Cross-file Consistency ──

    seg_boundary_mismatches = 0
    seg_boundary_details = []  # [(verse_key, side, diff_ms, msg), ...] for top-N display
    seg_pad_ms = 0
    # Look for segments.json alongside (in parent recitation_segments dir)
    # The timestamps dir is data/timestamps/<category>/<reciter>/
    # The segments dir is data/recitation_segments/<reciter>/
    seg_dir = reciter_dir.parent.parent.parent / "recitation_segments" / reciter
    seg_path = seg_dir / "segments.json"
    if seg_path.exists():
        seg_verses, seg_meta = parse_segments(seg_path)
        seg_pad_ms = seg_meta.get("pad_ms", 0)
        # Tolerance = 2x pad duration (words can start/end anywhere within the pad)
        tolerance = 2 * seg_pad_ms if seg_pad_ms > 0 else 500
        for verse_key in verses:
            if verse_key not in seg_verses:
                continue
            ts_words = verses[verse_key]
            segs = seg_verses[verse_key]
            if not ts_words or not segs:
                continue
            ts_first_start = ts_words[0][1]
            ts_last_end = ts_words[-1][2]
            seg_first_start = segs[0][2]
            seg_last_end = segs[-1][3]

            start_diff = abs(ts_first_start - seg_first_start)
            if start_diff > tolerance:
                seg_boundary_mismatches += 1
                msg = (f"start mismatch: timestamps {_ms_to_hms(ts_first_start)} "
                       f"vs segments {_ms_to_hms(seg_first_start)} "
                       f"(diff {start_diff}ms)")
                warnings.append({"msg": msg, "verse_key": verse_key})
                seg_boundary_details.append((verse_key, "start", start_diff, msg))

            end_diff = abs(ts_last_end - seg_last_end)
            if end_diff > tolerance:
                seg_boundary_mismatches += 1
                msg = (f"end mismatch: timestamps {_ms_to_hms(ts_last_end)} "
                       f"vs segments {_ms_to_hms(seg_last_end)} "
                       f"(diff {end_diff}ms)")
                warnings.append({"msg": msg, "verse_key": verse_key})
                seg_boundary_details.append((verse_key, "end", end_diff, msg))

    # ── 5. Verse-level timestamp checks ──
    # Use verse_start_ms/verse_end_ms from timestamps_full.json when available,
    # otherwise fall back to first word start / last word end.

    audio_source = meta.get("audio_source", "") if meta else ""
    is_by_surah = "by_surah" in audio_source

    short_verses = 0
    verse_overlaps = 0
    large_gaps = 0
    verse_durations = []

    # Build {(surah, ayah): (start_ms, end_ms)} for all regular verse keys
    verse_spans: dict[tuple[int, int], tuple[int, int]] = {}
    for verse_key, words in verses.items():
        if "-" in verse_key or not words:
            continue  # skip compound keys
        parts = verse_key.split(":")
        if len(parts) != 2:
            continue
        try:
            sa = (int(parts[0]), int(parts[1]))
        except ValueError:
            continue

        # Use explicit verse boundaries from timestamps_full.json
        full_entry = full_verses.get(verse_key, {}) if has_full else {}
        v_start = full_entry.get("verse_start_ms")
        v_end = full_entry.get("verse_end_ms")
        if v_start is None or v_end is None:
            continue  # no verse timestamps available, skip

        verse_spans[sa] = (v_start, v_end)
        dur = v_end - v_start
        verse_durations.append(dur)
        if 0 < dur < 500:
            short_verses += 1
            warnings.append({
                "msg": f"very short verse duration: {dur}ms",
                "verse_key": verse_key,
            })

    # Inter-verse ordering and gap checks (by_surah only — verses share one audio)
    if is_by_surah:
        # Group by surah, check consecutive ayahs
        from collections import defaultdict as _defaultdict
        surah_verses: dict[int, list[tuple[int, int, int]]] = _defaultdict(list)
        for (surah, ayah), (v_start, v_end) in verse_spans.items():
            surah_verses[surah].append((ayah, v_start, v_end))

        for surah in sorted(surah_verses):
            by_ayah = sorted(surah_verses[surah], key=lambda x: x[0])
            for i in range(1, len(by_ayah)):
                prev_ayah, prev_start, prev_end = by_ayah[i - 1]
                cur_ayah, cur_start, cur_end = by_ayah[i]
                if cur_ayah != prev_ayah + 1:
                    continue  # non-consecutive, skip

                # Overlap: current verse starts before previous verse ends
                if cur_start < prev_end:
                    overlap = prev_end - cur_start
                    verse_overlaps += 1
                    errors.append({
                        "msg": f"verse overlap with {surah}:{prev_ayah}: "
                               f"{surah}:{prev_ayah} ends {_ms_to_hms(prev_end)}, "
                               f"{surah}:{cur_ayah} starts {_ms_to_hms(cur_start)} "
                               f"(overlap {overlap}ms)",
                        "verse_key": f"{surah}:{cur_ayah}",
                    })

                # Large gap: > 10 seconds between consecutive verses
                gap = cur_start - prev_end
                if gap > 10000:
                    large_gaps += 1
                    warnings.append({
                        "msg": f"large gap after {surah}:{prev_ayah}: "
                               f"{_ms_to_hms(prev_end)} to {_ms_to_hms(cur_start)} "
                               f"(gap {_ms_to_s(gap)})",
                        "verse_key": f"{surah}:{cur_ayah}",
                    })

    # ── Build stats dict ──

    words_total = sum(len(ws) for ws in verses.values())

    stats = {
        "reciter": reciter,
        "verses": len(verses),
        "total_verses": len(word_counts),
        "missing": len(missing_verses),
        "words_total": words_total,
        "word_coverage_issues": word_coverage_issues,
        "forward_gap_verses": forward_gap_verses,
        "zero_duration_words": zero_duration_words,
        "negative_timestamps": negative_timestamps,
        "mfa_failures": len(mfa_failures),
        "word_dur_min": min(word_durations) if word_durations else 0,
        "word_dur_med": statistics.median(word_durations) if word_durations else 0,
        "word_dur_mean": statistics.mean(word_durations) if word_durations else 0,
        "word_dur_max": max(word_durations) if word_durations else 0,
        "short_verses": short_verses,
        "verse_overlaps": verse_overlaps,
        "large_gaps": large_gaps,
        "verse_dur_min": min(verse_durations) if verse_durations else 0,
        "verse_dur_med": statistics.median(verse_durations) if verse_durations else 0,
        "verse_dur_mean": statistics.mean(verse_durations) if verse_durations else 0,
        "verse_dur_max": max(verse_durations) if verse_durations else 0,
        "has_full": has_full,
        "letter_negative": letter_negative,
        "phone_issues": phone_issues,
        "has_segments": seg_path.exists(),
        "seg_tolerance_ms": 2 * seg_pad_ms if seg_pad_ms > 0 else 500,
        "seg_boundary_mismatches": seg_boundary_mismatches,
        "errors": len(errors),
        "warnings": len(warnings),
    }

    if verbose:
        _print_verbose(reciter, reciter_dir, stats, meta, errors, warnings,
                       missing_verses, word_counts, word_durations,
                       has_full, seg_path.exists(), seg_boundary_details, top_n)

    return stats


# ── Verbose single-reciter report ────────────────────────────────────────


def _print_verbose(reciter, reciter_dir, stats, meta, errors, warnings,
                   missing_verses, word_counts, word_durations,
                   has_full, has_segments, seg_boundary_details, top_n):
    """Pretty-print a detailed single-reciter report."""
    W = 72
    print("=" * W)
    print(f"  Timestamps: {reciter}")
    print(f"  {_rel_path(reciter_dir)}")
    print("=" * W)

    # ── MFA Settings ──
    if meta:
        print(f"\n--- MFA Settings ---")
        print(f"  Audio source:  {meta.get('audio_source', '?')}")
        print(f"  Method:        {meta.get('method', '?')}")
        print(f"  Beam:          {meta.get('beam', '?')}")
        print(f"  Retry beam:    {meta.get('retry_beam', '?')}")
        print(f"  Shared CMVN:   {meta.get('shared_cmvn', '?')}")

    # ── Coverage ──
    print(f"\n--- Coverage ---")
    print(f"  Verses found:       {stats['verses']} / {stats['total_verses']}")
    print(f"  Missing verses:     {stats['missing']}")
    print(f"  Total words:        {stats['words_total']}")
    print(f"  Coverage issues:    {stats['word_coverage_issues']}")
    print(f"  Forward gap verses: {stats['forward_gap_verses']}")

    # ── Word Duration ──
    print(f"\n--- Word Duration ---")
    if word_durations:
        print(f"  Min:      {_ms_to_s(stats['word_dur_min'])}")
        print(f"  Median:   {_ms_to_s(stats['word_dur_med'])}")
        print(f"  Mean:     {_ms_to_s(stats['word_dur_mean'])}")
        print(f"  Max:      {_ms_to_s(stats['word_dur_max'])}")
    else:
        print(f"  (no words with valid durations)")

    # ── MFA Failures ──
    if stats['mfa_failures'] > 0:
        print(f"\n--- MFA Alignment Failures ---")
        print(f"  Failed segments:  {stats['mfa_failures']}")
        mfa_failures = meta.get("mfa_failures", [])
        n_show = min(top_n, len(mfa_failures))
        for f in mfa_failures[:n_show]:
            print(f"    {f.get('verse', '?')}  seg {f.get('seg', '?')}  "
                  f"ref={f.get('ref', '?')}  error={f.get('error', '?')}")
        if len(mfa_failures) > n_show:
            print(f"    ... and {len(mfa_failures) - n_show} more")

    # ── Temporal Issues ──
    print(f"\n--- Temporal Issues ---")
    print(f"  Negative timestamps:  {stats['negative_timestamps']}")
    print(f"  Zero-duration words:  {stats['zero_duration_words']}")

    # ── Verse Timestamps ──
    print(f"\n--- Verse Timestamps ---")
    if stats['verse_dur_med'] > 0:
        print(f"  Duration min:     {_ms_to_s(stats['verse_dur_min'])}")
        print(f"  Duration median:  {_ms_to_s(stats['verse_dur_med'])}")
        print(f"  Duration mean:    {_ms_to_s(stats['verse_dur_mean'])}")
        print(f"  Duration max:     {_ms_to_s(stats['verse_dur_max'])}")
        print(f"  Short (<500ms):   {stats['short_verses']}")
        if stats['verse_overlaps'] > 0 or stats['large_gaps'] > 0:
            print(f"  Verse overlaps:   {stats['verse_overlaps']}")
            print(f"  Large gaps (>10s):{stats['large_gaps']}")
    else:
        print(f"  (no verse durations computed)")

    # ── Full format (letters/phones) ──
    print(f"\n--- Full Format (letters/phones) ---")
    if has_full:
        print(f"  Negative/inverted letters:  {stats['letter_negative']}")
        print(f"  Phone issues:              {stats['phone_issues']}")
    else:
        print(f"  (no timestamps_full.json)")

    # ── Cross-file Consistency ──
    print(f"\n--- Cross-file Consistency (segments.json) ---")
    if has_segments:
        tol = stats.get('seg_tolerance_ms', 500)
        print(f"  Boundary mismatches (>{tol}ms):  {stats['seg_boundary_mismatches']}")
        if seg_boundary_details:
            ranked = sorted(seg_boundary_details, key=lambda x: x[2], reverse=True)
            n_show = min(top_n, len(ranked))
            print(f"\n  Top {n_show} boundary violations (by diff):")
            for vk, side, diff, msg in ranked[:n_show]:
                print(f"    {vk:<12} {msg}")
            if len(ranked) > n_show:
                print(f"    ... and {len(ranked) - n_show} more")
    else:
        print(f"  (segments.json not found)")

    # ── Errors & Warnings ──
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

    if errors:
        n_show = min(top_n, len(errors))
        print(f"\n  Errors (first {n_show} of {len(errors)}):")
        for e in errors[:n_show]:
            print(f"    ERROR  {e['verse_key']}  {e['msg']}")
        if len(errors) > n_show:
            print(f"    ... and {len(errors) - n_show} more")

    if warnings:
        n_show = min(top_n, len(warnings))
        print(f"\n  Warnings (first {n_show} of {len(warnings)}):")
        for w in warnings[:n_show]:
            print(f"    WARN   {w['verse_key']}  {w['msg']}")
        if len(warnings) > n_show:
            print(f"    ... and {len(warnings) - n_show} more")

    print()


# ── Summary table (multi-reciter) ───────────────────────────────────────


def _print_row(reciter: str, cols: list[str], widths: list[int]):
    parts = [f"{reciter:<30}"]
    for val, w in zip(cols, widths):
        parts.append(f"{val:>{w}}")
    print(" ".join(parts))


def print_table(all_stats: list[dict]):
    """Print summary tables across all reciters."""
    sorted_stats = sorted(all_stats, key=lambda x: x["reciter"])
    # Filter out skipped reciters
    sorted_stats = [s for s in sorted_stats if not s.get("skipped")]
    if not sorted_stats:
        print("No reciters with timestamp data found.")
        return

    total_label = f"TOTAL ({len(sorted_stats)} reciters)"

    # --- Table 1: Coverage ---
    print("=== Timestamp Coverage ===\n")
    cov_hdrs = ["Verses", "Missing", "Words", "Cov Issues", "Fwd Gaps", "MFA Fail", "Errors", "Warnings"]
    cov_ws = [6, 7, 7, 10, 8, 8, 6, 8]
    _print_row("Reciter", cov_hdrs, cov_ws)
    print("-" * (30 + sum(w + 1 for w in cov_ws)))

    totals = {k: 0 for k in ["verses", "missing", "words_total",
                              "word_coverage_issues", "forward_gap_verses",
                              "mfa_failures", "errors", "warnings"]}
    for s in sorted_stats:
        _print_row(s["reciter"], [
            str(s["verses"]), str(s["missing"]), str(s["words_total"]),
            str(s["word_coverage_issues"]), str(s["forward_gap_verses"]),
            str(s.get("mfa_failures", 0)),
            str(s["errors"]), str(s["warnings"]),
        ], cov_ws)
        for k in totals:
            totals[k] += s.get(k, 0)

    print("-" * (30 + sum(w + 1 for w in cov_ws)))
    _print_row(total_label, [
        str(totals["verses"]), str(totals["missing"]), str(totals["words_total"]),
        str(totals["word_coverage_issues"]), str(totals["forward_gap_verses"]),
        str(totals["mfa_failures"]),
        str(totals["errors"]), str(totals["warnings"]),
    ], cov_ws)

    # --- Table 2: Word Duration ---
    print("\n\n=== Word Duration (ms) ===\n")
    dur_hdrs = ["Min", "Median", "Mean", "Max", "Zero-Dur", "Negative"]
    dur_ws = [8, 8, 8, 8, 8, 8]
    _print_row("Reciter", dur_hdrs, dur_ws)
    print("-" * (30 + sum(w + 1 for w in dur_ws)))

    all_med = []
    for s in sorted_stats:
        if s["words_total"] > 0:
            _print_row(s["reciter"], [
                f"{s['word_dur_min']:.0f}", f"{s['word_dur_med']:.0f}",
                f"{s['word_dur_mean']:.0f}", f"{s['word_dur_max']:.0f}",
                str(s["zero_duration_words"]), str(s["negative_timestamps"]),
            ], dur_ws)
            all_med.append(s["word_dur_med"])
        else:
            _print_row(s["reciter"], ["n/a"] * 6, dur_ws)

    print("-" * (30 + sum(w + 1 for w in dur_ws)))
    med_of_med = statistics.median(all_med) if all_med else 0
    _print_row(total_label, ["", f"{med_of_med:.0f}", "", "", "", ""], dur_ws)

    # --- Table 3: Verse Duration ---
    print("\n\n=== Verse Duration (ms) ===\n")
    vdur_hdrs = ["Min", "Median", "Mean", "Max", "Short", "Overlaps", "Lg Gaps"]
    vdur_ws = [8, 8, 8, 8, 6, 8, 7]
    _print_row("Reciter", vdur_hdrs, vdur_ws)
    print("-" * (30 + sum(w + 1 for w in vdur_ws)))

    all_vmed = []
    for s in sorted_stats:
        if s.get("verse_dur_med", 0) > 0:
            _print_row(s["reciter"], [
                f"{s['verse_dur_min']:.0f}", f"{s['verse_dur_med']:.0f}",
                f"{s['verse_dur_mean']:.0f}", f"{s['verse_dur_max']:.0f}",
                str(s.get("short_verses", 0)),
                str(s.get("verse_overlaps", 0)),
                str(s.get("large_gaps", 0)),
            ], vdur_ws)
            all_vmed.append(s["verse_dur_med"])
        else:
            _print_row(s["reciter"], ["n/a"] * 7, vdur_ws)

    print("-" * (30 + sum(w + 1 for w in vdur_ws)))
    med_of_vmed = statistics.median(all_vmed) if all_vmed else 0
    _print_row(total_label, ["", f"{med_of_vmed:.0f}", "", "", "", "", ""], vdur_ws)

    # --- Table 4: Consistency ---
    has_any_consistency = any(s.get("has_full") or s.get("has_segments") for s in sorted_stats)
    if has_any_consistency:
        print("\n\n=== Consistency ===\n")
        con_hdrs = ["Full File", "Ltr Errors", "Ph Issues", "Seg File", "Boundary MM"]
        con_ws = [9, 10, 9, 8, 11]
        _print_row("Reciter", con_hdrs, con_ws)
        print("-" * (30 + sum(w + 1 for w in con_ws)))

        for s in sorted_stats:
            _print_row(s["reciter"], [
                "yes" if s.get("has_full") else "no",
                str(s.get("letter_negative", 0)) if s.get("has_full") else "n/a",
                str(s.get("phone_issues", 0)) if s.get("has_full") else "n/a",
                "yes" if s.get("has_segments") else "no",
                str(s.get("seg_boundary_mismatches", 0)) if s.get("has_segments") else "n/a",
            ], con_ws)


# ── CLI ──────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path", type=Path,
        help="Single reciter directory or parent directory of reciter subdirs",
    )
    parser.add_argument(
        "--surah-info", type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "surah_info.json",
        help="Path to surah_info.json",
    )
    parser.add_argument(
        "--top", "-n", type=int, default=30,
        help="Number of issues to show per category (default: 30)",
    )
    args = parser.parse_args()

    word_counts = load_word_counts(args.surah_info)
    target = args.path.resolve()

    if not target.is_dir():
        print(f"Path not found or not a directory: {_rel_path(target)}")
        return

    # Single reciter dir: contains timestamps.json directly
    if (target / "timestamps.json").exists():
        report_path = target / "validation.log"
        with _tee_to_file(report_path):
            validate_reciter(target, word_counts, verbose=True, top_n=args.top)
        print(f"Report saved to {_rel_path(report_path)}")
        return

    # Parent dir: find subdirectories with timestamps.json (search up to 2 levels deep)
    subdirs = sorted(
        d for d in target.iterdir()
        if d.is_dir() and (d / "timestamps.json").exists()
    )
    if not subdirs:
        # Try one level deeper (e.g. data/timestamps/by_ayah_audio/<reciter>/)
        subdirs = sorted(
            dd for d in target.iterdir() if d.is_dir()
            for dd in d.iterdir()
            if dd.is_dir() and (dd / "timestamps.json").exists()
        )
    if not subdirs:
        print(f"No reciter subdirectories with timestamps.json found in {_rel_path(target)}")
        return

    # Per-reciter detailed reports
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


if __name__ == "__main__":
    main()
