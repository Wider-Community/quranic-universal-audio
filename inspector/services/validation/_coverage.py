"""Word coverage + verse-key parsing helpers for timestamp validation.

Pure helpers consumed by :mod:`services.validation.timestamps`. Mirrors the
``_missing.py`` pattern: small, single-purpose, no Flask / no I/O.
"""

from __future__ import annotations


def parse_verse_key(verse_key: str) -> tuple[int, int] | None:
    """Parse a ``"surah:ayah"`` key into a tuple, or None on malformed input."""
    parts = verse_key.split(":")
    if len(parts) != 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def parse_compound_key(verse_key: str) -> tuple[int, int, int] | None:
    """Parse a compound key like ``"37:151:3-37:152:2"`` → ``(surah, start_ayah, end_ayah)``.

    Returns None on malformed input.
    """
    try:
        start_part, end_part = verse_key.split("-", 1)
        sp = start_part.split(":")
        ep = end_part.split(":")
        return (int(sp[0]), int(sp[1]), int(ep[1]))
    except (ValueError, IndexError):
        return None


def collect_verse_keys(
    verses: dict[str, list[list]],
    errors: list[dict],
) -> set[tuple[int, int]]:
    """Return every ``(surah, ayah)`` referenced by ``verses``.

    Handles both regular ``"surah:ayah"`` keys and compound
    ``"surah:ayah:word-surah:ayah:word"`` keys (cross-verse segments).
    Appends to ``errors`` for unparseable keys.
    """
    all_keys: set[tuple[int, int]] = set()
    for vk in verses:
        if "-" in vk:
            parsed = parse_compound_key(vk)
            if parsed is None:
                errors.append({"msg": f"invalid compound key format: {vk}",
                              "verse_key": vk})
                continue
            start_surah, start_ayah, end_ayah = parsed
            for a in range(start_ayah, end_ayah + 1):
                all_keys.add((start_surah, a))
        else:
            parsed = parse_verse_key(vk)
            if parsed is None:
                # Skip silently for non-":"-separated keys; only error on
                # well-formed-but-invalid (parse_verse_key already filtered the
                # len-!= 2 case to None) so we only flag broken integer parts.
                if ":" in vk:
                    errors.append({"msg": f"invalid verse key format: {vk}",
                                  "verse_key": vk})
                continue
            all_keys.add(parsed)
    return all_keys


def accumulate_word_coverage(
    verse_key: str,
    words: list[list],
    is_compound: bool,
    covered_per_verse: dict[tuple[int, int], set[int]],
) -> None:
    """Add the word indices in ``words`` to ``covered_per_verse``.

    Compound keys walk word-index drops to detect verse boundary crossings
    (word_idx restarting from 1 marks a new verse). Mutates the dict in place.
    """
    if is_compound:
        parsed = parse_compound_key(verse_key)
        if parsed is None:
            return
        start_surah, start_ayah, end_ayah = parsed
        cur_ayah = start_ayah
        prev_idx = -1
        for w in words:
            idx = w[0]
            if prev_idx >= 0 and idx <= prev_idx and cur_ayah < end_ayah:
                cur_ayah += 1
            sa = (start_surah, cur_ayah)
            covered_per_verse.setdefault(sa, set()).add(idx)
            prev_idx = idx
    else:
        parsed = parse_verse_key(verse_key)
        if parsed is None:
            return
        indices = [w[0] for w in words]
        covered_per_verse.setdefault(parsed, set()).update(indices)


def check_forward_gaps(
    verse_key: str,
    words: list[list],
    is_compound: bool,
    warnings: list[dict],
) -> bool:
    """Detect non-contiguous word indices ("forward gaps") in ``words``.

    Walks the index sequence; whenever the high-water mark advances by more
    than one, records a gap. For compound keys, resets the hwm at verse
    boundaries (index drop). Returns True iff at least one gap was found.
    Appends one warning per gappy verse (truncated to first three gaps).
    """
    if is_compound:
        parsed = parse_compound_key(verse_key)
        if parsed is None:
            return False
        _start_surah, start_ayah, end_ayah = parsed
        cur_ayah = start_ayah
        prev_idx = -1
        hwm: int | None = None
        gaps: list[tuple[int, int]] = []
        for w in words:
            idx = w[0]
            if prev_idx >= 0 and idx <= prev_idx and cur_ayah < end_ayah:
                cur_ayah += 1
                hwm = None
            if hwm is None:
                hwm = idx
            elif idx > hwm:
                if idx > hwm + 1:
                    gaps.append((hwm, idx))
                hwm = idx
            prev_idx = idx
    else:
        indices = [w[0] for w in words]
        if not indices:
            return False
        hwm = indices[0]
        gaps = []
        for idx in indices[1:]:
            if idx > hwm:
                if idx > hwm + 1:
                    gaps.append((hwm, idx))
                hwm = idx

    if not gaps:
        return False

    gap_strs = [f"{a}→{b}" for a, b in gaps[:3]]
    suffix = f" (+{len(gaps) - 3} more)" if len(gaps) > 3 else ""
    warnings.append({
        "msg": f"forward gaps in word indices: {', '.join(gap_strs)}{suffix}",
        "verse_key": verse_key,
    })
    return True


def report_word_coverage(
    covered_per_verse: dict[tuple[int, int], set[int]],
    word_counts: dict[tuple[int, int], int],
    warnings: list[dict],
) -> int:
    """Compare covered word indices against expected counts.

    For each verse with at least one covered word, flag missing indices and
    extra indices (beyond ``word_counts[verse]``). Verses with zero coverage
    are skipped — they're already counted in ``missing_verses``.

    Returns the count of coverage-issue warnings appended.
    """
    issues = 0
    for sa in sorted(word_counts):
        expected = word_counts[sa]
        covered = covered_per_verse.get(sa, set())
        if not covered:
            continue
        expected_set = set(range(1, expected + 1))
        missing_idx = sorted(expected_set - covered)
        extra_idx = sorted(covered - expected_set)
        verse_key_label = f"{sa[0]}:{sa[1]}"
        if missing_idx:
            issues += 1
            warnings.append({
                "msg": f"missing word indices: {missing_idx}",
                "verse_key": verse_key_label,
            })
        if extra_idx:
            issues += 1
            warnings.append({
                "msg": f"extra word indices beyond {expected}: {extra_idx}",
                "verse_key": verse_key_label,
            })
    return issues
