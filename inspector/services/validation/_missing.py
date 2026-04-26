"""Missing-words detection helper.

Extracted from validate_reciter_segments. Given the verse_segments map
(built during the main pass), produces the missing_words detail list.
"""

from __future__ import annotations

from services.data_loader import word_has_stop


def _build_missing_words(
    verse_segments: dict[tuple[int, int], list],
    word_counts: dict[tuple[int, int], int],
) -> list[dict]:
    """Build a list of missing-word issue dicts from the verse coverage map.

    verse_segments maps (surah, ayah) → [(word_from, word_to, seg_index), ...].
    seg_index is the chapter-local segment index used for auto-fix targeting.
    """
    missing_words = []
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

        gap_indices: set[int] = set()
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
                auto_fix = {
                    "target_seg_index": first_idx,
                    "new_ref_start": f"{surah}:{ayah}:1",
                    "new_ref_end": f"{surah}:{ayah}:{first_wt}",
                }
            elif mw == expected and last_wt < expected:
                auto_fix = {
                    "target_seg_index": last_idx,
                    "new_ref_start": f"{surah}:{ayah}:{last_wf}",
                    "new_ref_end": f"{surah}:{ayah}:{expected}",
                }
            else:
                for j in range(len(seg_list) - 1):
                    wf, wt, idx = seg_list[j]
                    next_wf, next_wt, next_idx = seg_list[j + 1]
                    if wt + 1 == mw and mw + 1 == next_wf:
                        if word_has_stop(surah, ayah, wt):
                            auto_fix = {
                                "target_seg_index": next_idx,
                                "new_ref_start": f"{surah}:{ayah}:{mw}",
                                "new_ref_end": f"{surah}:{ayah}:{next_wt}",
                            }
                        elif word_has_stop(surah, ayah, mw):
                            auto_fix = {
                                "target_seg_index": idx,
                                "new_ref_start": f"{surah}:{ayah}:{wf}",
                                "new_ref_end": f"{surah}:{ayah}:{mw}",
                            }
                        break

        issue: dict = {
            "verse_key": f"{surah}:{ayah}",
            "chapter": surah,
            "msg": f"missing words: {sorted(missing)}",
            "seg_indices": sorted(gap_indices),
        }
        if auto_fix:
            issue["auto_fix"] = auto_fix
        missing_words.append(issue)

    return missing_words
