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
