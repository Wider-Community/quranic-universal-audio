"""Per-verse word counts from ``surah_info``.

The single pure helper the release/publish jobs need out of the (offline-only)
auto-split precompute: a ``(surah, ayah) -> num_words`` map. Lives here so it
ships in the qua_jobs image without dragging in any inspector-tree or MFA deps.
"""

from __future__ import annotations


def word_counts_from_surah_info(surah_info: dict) -> dict[tuple[int, int], int]:
    """Build the ``(surah, ayah) -> word_count`` map from a loaded surah_info dict.

    ``surah_info`` is ``{surah_str: {"verses": [{"verse": int, "num_words": int},
    ...]}}`` — the in-memory shape both publish/release jobs already hold.
    """
    counts: dict[tuple[int, int], int] = {}
    for surah_str, info in surah_info.items():
        surah = int(surah_str)
        for v in info.get("verses", []):
            counts[(surah, int(v["verse"]))] = int(v["num_words"])
    return counts


def word_counts_for(riwayah: str, surah_info: dict) -> dict[tuple[int, int], int]:
    """The ``(surah, ayah) -> word_count`` map for one edition.

    Hafs reads ``surah_info`` — byte-identical to ``qua_domain``'s Hafs index
    (6,236 verses, 77,433 words, zero diffs) and available with the package
    absent, which is what a Hafs-only runtime needs. Every other edition comes
    from ``qua_domain``: Warsh and Qalun renumber 50 of the 114 surahs, so
    reusing the Hafs map would gate the wrong verses as incomplete.
    """
    from qua_shared.riwayat import DEFAULT_SDK_RIWAYAH

    if riwayah == DEFAULT_SDK_RIWAYAH:
        return word_counts_from_surah_info(surah_info)

    from qua_domain import load_edition_index

    counts: dict[tuple[int, int], int] = {}
    for word in load_edition_index(riwayah).words:
        key = (word.surah, word.ayah)
        counts[key] = max(counts.get(key, 0), word.word)
    return counts


def surah_info_for(riwayah: str, surah_info: dict) -> dict:
    """``surah_info`` re-expressed in one edition's counting profile.

    Consumers walk ``surah_info`` to enumerate verses in order and to look up a
    verse's word count. Both facts differ per edition — Warsh and Qalun
    renumber 50 of the 114 surahs — so handing them the Hafs file would make a
    Warsh publish enumerate verses that do not exist and clip segments against
    another verse's length.

    ``verses`` and ``num_verses`` are rebuilt — the latter because
    ``qua_shared.coverage.verse_counts_from_surah_info`` reads it, and an
    edition's ayah count is exactly what differs (al-Baqarah ends at 285 in
    Warsh and Qalun, 286 in Hafs). Nothing downstream reads the other keys, and
    inventing per-edition surah names here would be a second, unverified source
    for them.
    """
    from qua_shared.riwayat import DEFAULT_SDK_RIWAYAH

    if riwayah == DEFAULT_SDK_RIWAYAH:
        return surah_info

    counts = word_counts_for(riwayah, surah_info)
    out: dict[str, dict] = {}
    for (surah, ayah), num_words in sorted(counts.items()):
        out.setdefault(str(surah), {"verses": []})["verses"].append(
            {"verse": ayah, "num_words": num_words}
        )
    for info in out.values():
        info["num_verses"] = len(info["verses"])
    return out
