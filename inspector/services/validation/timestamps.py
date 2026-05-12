"""Timestamps validation — MFA forced-alignment output checks.

Public:
    validate_reciter_timestamps(reciter: str) -> dict | None

Returns the JSON-ready response shape consumed by ``GET /api/ts/validate/<reciter>``,
or ``None`` when no on-disk timestamps tree exists for the reciter.

Local-mode only: reads `timestamps.json` + optional `timestamps_full.json`
from `TIMESTAMPS_PATH/<audio_type>/<reciter>/`. Deployed Spaces flip
`INSPECTOR_TS_VALIDATE_ENABLED=0` and never reach this code.

Ported from the former `validators/validate_timestamps.py` CLI; logic
preserved, structure split to mirror `_structural.py` / `_missing.py`.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from config import (
    MISSING_WORD_DIFF_MS_WEIGHT,
    SURAH_INFO_PATH,
    TIMESTAMPS_PATH,
    TS_BOUNDARY_TOLERANCE_MS,
)
from constants import TS_AUDIO_CATEGORIES
from scripts.lib.boundary_check import compute_boundary_mismatches
from services.data_loader import get_word_counts

from services.validation._coverage import (
    accumulate_word_coverage,
    check_forward_gaps,
    collect_verse_keys,
    parse_verse_key,
    report_word_coverage,
)
from services.validation._temporal import (
    check_full_format_letters_phones,
    check_per_word_temporal,
    check_verse_overlaps_and_gaps,
)


# ── Parsers ────────────────────────────────────────────────────────────────


def _parse_timestamps(path: Path) -> tuple[dict[str, list[list]], dict]:
    """``timestamps.json`` → ``(verses, meta)``.

    ``verses``: ``{verse_key: [[word_idx, start_ms, end_ms], ...]}``.
    ``meta``: dict pulled from the ``_meta`` key.
    """
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.pop("_meta", {})
    return doc, meta


def _parse_timestamps_full(path: Path) -> tuple[dict[str, dict], dict]:
    """``timestamps_full.json`` → ``(verses, meta)``.

    ``verses``: ``{verse_key: {"words": [[idx, start, end, letters, phones], ...]}}``
    where ``letters = [[char, start, end], ...]`` and phones are nested per word.
    """
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.pop("_meta", {})
    return doc, meta


# ── Slug → directory resolution ────────────────────────────────────────────


def _resolve_ts_dir(reciter: str) -> Path | None:
    """Find the timestamps directory for ``reciter``.

    Walks ``TIMESTAMPS_PATH/<audio_type>/<reciter>/`` in reverse-priority
    order (matching the legacy route behaviour: by_surah_audio wins over
    by_ayah_audio). Returns the first match with a ``timestamps.json``, or
    ``None``.
    """
    for audio_type in reversed(TS_AUDIO_CATEGORIES):
        candidate = TIMESTAMPS_PATH / audio_type / reciter
        if (candidate / "timestamps.json").exists():
            return candidate
    return None


# ── Word-counts loader ─────────────────────────────────────────────────────


def _load_word_counts_from_surah_info() -> dict[tuple[int, int], int]:
    """Build ``(surah, ayah) → num_words`` from ``surah_info.json``.

    Equivalent to ``services.data_loader.get_word_counts()`` but reads the
    raw file rather than the cached entries. Used as a fallback when
    ``get_word_counts()`` returns an empty dict (e.g. before any reciter has
    been loaded into the in-memory cache).
    """
    cached = get_word_counts()
    if cached:
        return cached
    with open(SURAH_INFO_PATH, encoding="utf-8") as f:
        info = json.load(f)
    wc: dict[tuple[int, int], int] = {}
    for surah_str, data in info.items():
        surah = int(surah_str)
        for v in data["verses"]:
            wc[(surah, v["verse"])] = v["num_words"]
    return wc


# ── Core validator ─────────────────────────────────────────────────────────


def _validate_ts_dir(ts_dir: Path, word_counts: dict[tuple[int, int], int]) -> dict:
    """Run every check pass on a resolved timestamps directory.

    Returns the same structured stats dict the former CLI produced. Inspector
    route reshapes it for the wire response.
    """
    ts_path = ts_dir / "timestamps.json"
    ts_full_path = ts_dir / "timestamps_full.json"
    reciter = ts_dir.name

    verses, meta = _parse_timestamps(ts_path)
    has_full = ts_full_path.exists()
    full_verses: dict = {}
    if has_full:
        full_verses, _ = _parse_timestamps_full(ts_full_path)

    errors: list[dict] = []
    warnings: list[dict] = []
    word_durations: list[float] = []

    # ── 1. Meta + MFA failures (structural) ──
    meta_fields = {"created_at", "aligner_model", "audio_source", "method",
                   "beam", "shared_cmvn", "padding"}
    if not meta:
        errors.append({"msg": "_meta line missing or empty", "verse_key": ""})
    else:
        missing_meta = meta_fields - set(meta.keys())
        if missing_meta:
            warnings.append({"msg": f"_meta missing fields: {sorted(missing_meta)}",
                            "verse_key": ""})

    mfa_failures = meta.get("mfa_failures", []) if meta else []
    for fail in mfa_failures:
        errors.append({
            "msg": (f"MFA failed: seg {fail.get('seg', '?')} "
                    f"ref={fail.get('ref', '?')} error={fail.get('error', '?')}"),
            "verse_key": fail.get("verse", ""),
        })

    # ── 2. Verse coverage ──
    all_verse_keys = collect_verse_keys(verses, errors)
    missing_verses = [f"{sa[0]}:{sa[1]}"
                      for sa in sorted(word_counts)
                      if sa not in all_verse_keys]

    # ── 3. Per-verse temporal + word-coverage accumulation ──
    covered_per_verse: dict[tuple[int, int], set[int]] = {}
    forward_gap_verses = 0
    zero_duration_words = 0
    negative_timestamps = 0

    for verse_key, words in verses.items():
        is_compound = "-" in verse_key
        accumulate_word_coverage(verse_key, words, is_compound, covered_per_verse)
        if check_forward_gaps(verse_key, words, is_compound, warnings):
            forward_gap_verses += 1
        zd, neg = check_per_word_temporal(words, verse_key, errors, warnings,
                                          word_durations)
        zero_duration_words += zd
        negative_timestamps += neg

    word_coverage_issues = report_word_coverage(covered_per_verse, word_counts,
                                                 warnings)

    # ── 4. Full-format letter/phone temporal ──
    letter_negative, phone_issues = check_full_format_letters_phones(
        full_verses, errors, warnings,
    )

    # ── 5. Cross-file consistency vs segments.json ──
    seg_dir = ts_dir.parent.parent.parent / "recitation_segments" / reciter
    seg_path = seg_dir / "segments.json"
    boundary = compute_boundary_mismatches(verses, seg_path)
    seg_pad_ms = boundary["pad_ms"]
    tolerance = boundary["tolerance_ms"]
    seg_boundary_mismatches = len(boundary["mismatches"])
    seg_boundary_details = [
        (m["verse_key"], m["side"], m["diff_ms"], m["msg"])
        for m in boundary["mismatches"]
    ]
    for m in boundary["mismatches"]:
        warnings.append({"msg": m["msg"], "verse_key": m["verse_key"]})

    # ── 6. Verse-level timestamps (by_surah only) ──
    audio_source = meta.get("audio_source", "") if meta else ""
    is_by_surah = "by_surah" in audio_source

    short_verses = 0
    verse_durations: list[int] = []
    verse_spans: dict[tuple[int, int], tuple[int, int]] = {}
    for verse_key, words in verses.items():
        if "-" in verse_key or not words:
            continue
        sa = parse_verse_key(verse_key)
        if sa is None:
            continue
        full_entry = full_verses.get(verse_key, {}) if has_full else {}
        v_start = full_entry.get("verse_start_ms")
        v_end = full_entry.get("verse_end_ms")
        if v_start is None or v_end is None:
            continue
        verse_spans[sa] = (v_start, v_end)
        dur = v_end - v_start
        verse_durations.append(dur)
        if 0 < dur < 500:
            short_verses += 1
            warnings.append({
                "msg": f"very short verse duration: {dur}ms",
                "verse_key": verse_key,
            })

    verse_overlaps, large_gaps, overlap_details, large_gap_details = (
        check_verse_overlaps_and_gaps(verse_spans, is_by_surah, errors, warnings)
    )

    # ── Stats ──
    words_total = sum(len(ws) for ws in verses.values())

    return {
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
        "seg_tolerance_ms": tolerance if seg_pad_ms > 0 else 500,
        "seg_boundary_mismatches": seg_boundary_mismatches,
        "errors": len(errors),
        "warnings": len(warnings),
        # Structured detail lists for the route layer.
        "_mfa_failures": mfa_failures,
        "_missing_words": [
            {"surah": sa[0], "ayah": sa[1],
             "missing": sorted(set(range(1, word_counts[sa] + 1))
                              - covered_per_verse.get(sa, set()))}
            for sa in sorted(word_counts)
            if covered_per_verse.get(sa) and (set(range(1, word_counts[sa] + 1))
                                              - covered_per_verse.get(sa, set()))
        ],
        "_boundary_mismatches": [
            {"verse_key": vk, "side": side, "diff_ms": round(diff)}
            for vk, side, diff, _msg in seg_boundary_details
        ],
        "_missing_verses": list(missing_verses),
        "_verse_overlaps": overlap_details,
        "_large_gaps": large_gap_details,
    }


# ── Public entrypoint ──────────────────────────────────────────────────────


def validate_reciter_timestamps(reciter: str) -> dict | None:
    """Validate ``reciter``'s timestamp data and return a JSON-ready dict.

    Returns ``None`` when no on-disk timestamps tree exists for the slug
    (caller should 404). Otherwise returns the route-shape dict consumed by
    ``GET /api/ts/validate/<reciter>``.
    """
    ts_dir = _resolve_ts_dir(reciter)
    if ts_dir is None:
        return None

    word_counts = _load_word_counts_from_surah_info()
    stats = _validate_ts_dir(ts_dir, word_counts)

    # Reshape structured detail lists into the response surface the frontend
    # consumes. Kept in this module (not the route) so the validation engine
    # owns its public shape, matching ``validate_reciter_segments``.
    mfa_failures = []
    for fail in stats.get("_mfa_failures", []):
        vk = fail.get("verse", "")
        ch = int(vk.split(":")[0]) if vk and ":" in vk else 0
        ref = fail.get("ref", "?")
        mfa_failures.append({
            "verse_key": vk, "chapter": ch,
            "ref": ref, "seg": fail.get("seg", "?"),
            "error": fail.get("error", "?"),
            "diff_ms": 0,
            "label": f"{vk} [{ref}]",
        })

    missing_words = []
    for mw in stats.get("_missing_words", []):
        vk = f"{mw['surah']}:{mw['ayah']}"
        count = len(mw["missing"])
        missing_words.append({
            "verse_key": vk, "chapter": mw["surah"],
            "missing": mw["missing"], "count": count,
            "diff_ms": count * MISSING_WORD_DIFF_MS_WEIGHT,
            "label": f"{vk} [-{count}w]",
        })
    missing_words.sort(key=lambda x: (
        x["chapter"],
        int(x["verse_key"].split(":")[1]) if ":" in x["verse_key"] else 0,
    ))

    boundary_mismatches = []
    for bm in stats.get("_boundary_mismatches", []):
        parts = bm["verse_key"].split(":")
        ch = int(parts[0]) if parts else 0
        boundary_mismatches.append({
            "verse_key": bm["verse_key"], "chapter": ch,
            "side": bm["side"], "diff_ms": bm["diff_ms"],
            "label": f"{bm['verse_key']} [{bm['diff_ms']}ms {bm['side']}]",
        })
    boundary_mismatches.sort(key=lambda x: x["diff_ms"], reverse=True)

    missing_verses = []
    for vk in stats.get("_missing_verses", []):
        parts = vk.split(":")
        ch = int(parts[0]) if parts and parts[0].isdigit() else 0
        missing_verses.append({"verse_key": vk, "chapter": ch, "label": vk})
    missing_verses.sort(key=lambda x: (
        x["chapter"],
        int(x["verse_key"].split(":")[1]) if ":" in x["verse_key"] else 0,
    ))

    verse_overlaps = []
    for ov in stats.get("_verse_overlaps", []):
        parts = ov["verse_key"].split(":")
        ch = int(parts[0]) if parts else 0
        verse_overlaps.append({
            "verse_key": ov["verse_key"], "chapter": ch,
            "prev_verse_key": ov["prev_verse_key"],
            "overlap_ms": ov["overlap_ms"],
            "label": f"{ov['verse_key']} [-{ov['overlap_ms']}ms]",
        })
    verse_overlaps.sort(key=lambda x: x["overlap_ms"], reverse=True)

    large_gaps_out = []
    for g in stats.get("_large_gaps", []):
        parts = g["verse_key"].split(":")
        ch = int(parts[0]) if parts else 0
        large_gaps_out.append({
            "verse_key": g["verse_key"], "chapter": ch,
            "prev_verse_key": g["prev_verse_key"],
            "gap_ms": g["gap_ms"],
            "label": f"{g['verse_key']} [{g['gap_ms'] / 1000:.1f}s gap]",
        })
    large_gaps_out.sort(key=lambda x: x["gap_ms"], reverse=True)

    return {
        "mfa_failures": mfa_failures,
        "missing_verses": missing_verses,
        "missing_words": missing_words,
        "verse_overlaps": verse_overlaps,
        "boundary_mismatches": boundary_mismatches,
        "large_gaps": large_gaps_out,
        "meta": {
            "has_segments": stats.get("has_segments", False),
            "tolerance_ms": stats.get("seg_tolerance_ms", TS_BOUNDARY_TOLERANCE_MS),
        },
    }
