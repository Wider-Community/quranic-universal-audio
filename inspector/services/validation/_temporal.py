"""Temporal checks for timestamp data — duration sanity + verse-level gaps/overlaps.

Pure helpers consumed by :mod:`services.validation.timestamps`. Each helper
appends to caller-owned ``errors`` / ``warnings`` lists so the orchestrator
keeps the single source of truth for issue ordering.
"""

from __future__ import annotations

from collections import defaultdict


def _ms_to_hms(ms: float) -> str:
    """Convert milliseconds to ``h:mm:ss.s`` (or ``m:ss.s`` if under one hour)."""
    total_s = ms / 1000.0
    h = int(total_s // 3600)
    m = int((total_s % 3600) // 60)
    s = total_s % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:04.1f}"
    return f"{m}:{s:04.1f}"


def _ms_to_s(ms: float) -> str:
    """Two-decimal seconds string. Used in human-readable warning messages."""
    return f"{ms / 1000:.2f}s"


def check_per_word_temporal(
    words: list[list],
    verse_key: str,
    errors: list[dict],
    warnings: list[dict],
    word_durations: list[float],
) -> tuple[int, int]:
    """Per-word negative/zero/inverted-duration scan.

    Mutates ``errors`` / ``warnings`` / ``word_durations`` in place. Returns
    ``(zero_duration_count, negative_count)`` so the orchestrator can roll
    per-verse totals into reciter-level stats.
    """
    zero_duration = 0
    negative = 0
    for w in words:
        idx, start, end = w[0], w[1], w[2]
        if start < 0 or end < 0:
            negative += 1
            errors.append({
                "msg": f"word {idx}: negative timestamp start={start} end={end}",
                "verse_key": verse_key,
            })
        elif start == end:
            zero_duration += 1
            warnings.append({
                "msg": f"word {idx}: zero duration at {_ms_to_hms(start)}",
                "verse_key": verse_key,
            })
        elif start > end:
            errors.append({
                "msg": (f"word {idx}: start ({_ms_to_hms(start)}) > "
                        f"end ({_ms_to_hms(end)})"),
                "verse_key": verse_key,
            })
        else:
            word_durations.append(end - start)
    return zero_duration, negative


def check_full_format_letters_phones(
    full_verses: dict[str, dict],
    errors: list[dict],
    warnings: list[dict],
) -> tuple[int, int]:
    """Scan ``timestamps_full.json`` letter + phone arrays for negative or
    inverted durations and per-word phone ordering.

    Letter duration sums are intentionally not compared to word spans — MFA
    geminates, idgham, and cross-word assimilation cause letters to overlap
    or extend beyond word boundaries (expected behavior).

    Returns ``(letter_negative_count, phone_issue_count)``.
    """
    letter_negative = 0
    phone_issues = 0
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
                            "msg": (f"word {w[0]} letter '{lt[0]}': "
                                    f"start ({lt[1]}) > end ({lt[2]})"),
                            "verse_key": verse_key,
                        })
            if len(w) > 4:
                phones = w[4]
                for ph in phones:
                    if ph[1] is not None and ph[2] is not None:
                        if ph[1] < 0 or ph[2] < 0:
                            phone_issues += 1
                        elif ph[1] > ph[2]:
                            phone_issues += 1
                            errors.append({
                                "msg": (f"word {w[0]} phone '{ph[0]}': "
                                        f"start ({ph[1]}) > end ({ph[2]})"),
                                "verse_key": verse_key,
                            })
                for i in range(1, len(phones)):
                    if (phones[i][1] is not None and phones[i - 1][2] is not None
                            and phones[i][1] < phones[i - 1][1]):
                        phone_issues += 1
                        warnings.append({
                            "msg": (f"word {w[0]} phones out of order: "
                                    f"'{phones[i - 1][0]}' then '{phones[i][0]}'"),
                            "verse_key": verse_key,
                        })
                        break
    return letter_negative, phone_issues


def check_verse_overlaps_and_gaps(
    verse_spans: dict[tuple[int, int], tuple[int, int]],
    is_by_surah: bool,
    errors: list[dict],
    warnings: list[dict],
) -> tuple[int, int, list[dict], list[dict]]:
    """Inter-verse ordering checks (by_surah audio only — verses share one file).

    Flags consecutive-verse overlaps (verse N starts before verse N-1 ends)
    and large gaps (>10 s between consecutive verses).

    Returns ``(overlap_count, large_gap_count, overlap_details, large_gap_details)``.
    """
    verse_overlaps = 0
    large_gaps = 0
    overlap_details: list[dict] = []
    large_gap_details: list[dict] = []

    if not is_by_surah:
        return verse_overlaps, large_gaps, overlap_details, large_gap_details

    surah_verses: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for (surah, ayah), (v_start, v_end) in verse_spans.items():
        surah_verses[surah].append((ayah, v_start, v_end))

    for surah in sorted(surah_verses):
        by_ayah = sorted(surah_verses[surah], key=lambda x: x[0])
        for i in range(1, len(by_ayah)):
            prev_ayah, prev_start, prev_end = by_ayah[i - 1]
            cur_ayah, cur_start, cur_end = by_ayah[i]
            if cur_ayah != prev_ayah + 1:
                continue

            if cur_start < prev_end:
                overlap = prev_end - cur_start
                verse_overlaps += 1
                overlap_details.append({
                    "verse_key": f"{surah}:{cur_ayah}",
                    "prev_verse_key": f"{surah}:{prev_ayah}",
                    "overlap_ms": int(overlap),
                })
                errors.append({
                    "msg": (f"verse overlap with {surah}:{prev_ayah}: "
                            f"{surah}:{prev_ayah} ends {_ms_to_hms(prev_end)}, "
                            f"{surah}:{cur_ayah} starts {_ms_to_hms(cur_start)} "
                            f"(overlap {overlap}ms)"),
                    "verse_key": f"{surah}:{cur_ayah}",
                })

            gap = cur_start - prev_end
            if gap > 10000:
                large_gaps += 1
                large_gap_details.append({
                    "verse_key": f"{surah}:{cur_ayah}",
                    "prev_verse_key": f"{surah}:{prev_ayah}",
                    "gap_ms": int(gap),
                })
                warnings.append({
                    "msg": (f"large gap after {surah}:{prev_ayah}: "
                            f"{_ms_to_hms(prev_end)} to {_ms_to_hms(cur_start)} "
                            f"(gap {_ms_to_s(gap)})"),
                    "verse_key": f"{surah}:{cur_ayah}",
                })

    return verse_overlaps, large_gaps, overlap_details, large_gap_details
