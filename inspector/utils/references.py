"""Reference string parsing and segment classification utilities."""

from constants import AUDIO_SOURCE_AYAH_MARKER


def is_by_ayah_source(audio_source: str) -> bool:
    """Return True if audio_source indicates a by-ayah audio category."""
    return AUDIO_SOURCE_AYAH_MARKER in audio_source


def chapter_from_ref(ref: str) -> int:
    """Extract chapter (surah) number from a ref string.

    Handles both surah-level refs (e.g. ``"1"``) and verse-level refs
    (e.g. ``"1:1"``).
    """
    return int(ref.split(":")[0])


def seg_belongs_to_entry(seg_ref: str, entry_ref: str) -> bool:
    """Check if a segment's matched_ref falls within the verse of an entry's ref.

    For by_ayah, entry_ref is like ``"1:1"`` (surah:verse).
    seg_ref may be ``"1:1:1-1:1:4"`` (cross-word) or ``"1:1"`` etc.
    A segment belongs to an entry if the surah:verse prefix matches.
    """
    if not seg_ref or not entry_ref:
        return False
    # Extract surah:verse from the start of seg_ref
    seg_parts = seg_ref.split("-")[0].split(":")
    entry_parts = entry_ref.split(":")
    if len(entry_parts) >= 2 and len(seg_parts) >= 2:
        return seg_parts[0] == entry_parts[0] and seg_parts[1] == entry_parts[1]
    # Surah-level entry: match by chapter only
    return seg_parts[0] == entry_parts[0]


def normalize_ref(ref: str, word_counts: dict[tuple[int, int], int]) -> str:
    """Normalize a short ref to canonical surah:ayah:word-surah:ayah:word format.

    Handles: "1:7" -> "1:7:1-1:7:N", "1:7:3" -> "1:7:3-1:7:3",
             "1:7-1:8" -> "1:7:1-1:8:N"

    *word_counts* maps ``(surah, ayah)`` to the number of words in that verse.
    """
    if not ref:
        return ref
    parts = ref.split("-")
    if len(parts) == 2:
        start = parts[0].split(":")
        end = parts[1].split(":")
        if len(start) == 3 and len(end) == 3:
            return ref  # Already canonical
        if len(start) == 2 and len(end) == 2:
            # "1:7-1:8" -> "1:7:1-1:8:N"
            try:
                e_surah, e_ayah = int(end[0]), int(end[1])
                e_wc = word_counts.get((e_surah, e_ayah), 1)
                return f"{start[0]}:{start[1]}:1-{end[0]}:{end[1]}:{e_wc}"
            except ValueError:
                return ref
    elif len(parts) == 1:
        colons = ref.split(":")
        if len(colons) == 2:
            # "1:7" -> "1:7:1-1:7:N"
            try:
                surah, ayah = int(colons[0]), int(colons[1])
                n = word_counts.get((surah, ayah), 1)
                return f"{surah}:{ayah}:1-{surah}:{ayah}:{n}"
            except ValueError:
                return ref
        elif len(colons) == 3:
            # "1:7:3" -> "1:7:3-1:7:3"
            return f"{ref}-{ref}"
    return ref


def seg_sort_key(k):
    """Sort key for segments.json: regular 'sura:ayah' and cross-verse 'sura:ayah:word-sura:ayah:word'."""
    parts = k.split("-")
    start = parts[0].split(":")
    return tuple(int(x) for x in start)


def cross_verse_sections(
    matched_ref: str, verse_word_counts: dict[tuple[int, int], int]
) -> list[list[str]] | None:
    """Split a compound cross-verse ref into per-verse reading-order sections.

    For ``"S:A1:W1-S:AN:WN"`` (same surah, A1 < AN) returns::

        [
            ["S:A1:W1", "S:A1:total(A1)"],     # first verse, partial start
            ["S:Ai:1", "S:Ai:total(Ai)"],      # any full middle verses
            ...,
            ["S:AN:1",  "S:AN:WN"],            # last verse, partial end
        ]

    Output shape matches ``utils.repetitions.compute_reading_sequence`` so the
    same downstream helpers (``section_refs_canonical``,
    ``count_words_in_section``, the auto-split MFA word-counting pipeline)
    consume both kinds without branching.

    Returns ``None`` when the ref is malformed, cross-surah, not actually
    cross-verse (A1 == AN), or any verse total in ``[A1 .. AN-1]`` is missing
    from *verse_word_counts*.
    """
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return None
    a_parts = parts[0].split(":")
    b_parts = parts[1].split(":")
    if len(a_parts) != 3 or len(b_parts) != 3:
        return None
    try:
        s1, a1, w1 = int(a_parts[0]), int(a_parts[1]), int(a_parts[2])
        s2, a2, wN = int(b_parts[0]), int(b_parts[1]), int(b_parts[2])
    except ValueError:
        return None
    # Cross-surah unsupported; same-verse not cross-verse; reverse order invalid.
    if s1 != s2 or a1 >= a2:
        return None
    surah = s1
    # We need word totals for the first verse and any middle verse — but NOT
    # the last verse, since wN is given directly. Refuse if any required total
    # is missing.
    required_totals_ayahs = list(range(a1, a2))  # a1 .. aN-1 inclusive
    totals = {}
    for ayah in required_totals_ayahs:
        total = verse_word_counts.get((surah, ayah))
        if not total:
            return None
        totals[ayah] = total
    sections: list[list[str]] = []
    sections.append([f"{surah}:{a1}:{w1}", f"{surah}:{a1}:{totals[a1]}"])
    for ayah in range(a1 + 1, a2):
        sections.append([f"{surah}:{ayah}:1", f"{surah}:{ayah}:{totals[ayah]}"])
    sections.append([f"{surah}:{a2}:1", f"{surah}:{a2}:{wN}"])
    return sections
