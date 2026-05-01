"""Shared reciter eligibility check for HF dataset + GitHub releases.

A reciter is eligible when both `segments.json` and `timestamps.json` (in
either `by_ayah_audio` or `by_surah_audio`) are tracked by git.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_TRACKED_CACHE: dict[Path, set[str]] = {}


def git_tracked_data_files(repo_root: Path) -> set[str]:
    """Cached `git ls-files` for data/timestamps + data/recitation_segments."""
    repo_root = repo_root.resolve()
    if repo_root not in _TRACKED_CACHE:
        result = subprocess.run(
            ["git", "ls-files", "data/timestamps/", "data/recitation_segments/"],
            capture_output=True, text=True, cwd=repo_root,
        )
        _TRACKED_CACHE[repo_root] = set(result.stdout.strip().splitlines())
    return _TRACKED_CACHE[repo_root]


def tracked_timestamps_audio_type(slug: str, repo_root: Path) -> str | None:
    """Return the audio_type whose `timestamps.json` is tracked, else None."""
    tracked = git_tracked_data_files(repo_root)
    for audio_type in ("by_ayah_audio", "by_surah_audio"):
        if f"data/timestamps/{audio_type}/{slug}/timestamps.json" in tracked:
            return audio_type
    return None


def has_tracked_timestamps(slug: str, repo_root: Path) -> bool:
    return tracked_timestamps_audio_type(slug, repo_root) is not None


def expand_segment_ayahs(segments: dict) -> set[tuple[int, int]]:
    """Return {(surah, ayah)} from a segments.json dict, expanding compound keys.

    Compound cross-verse keys like "37:151:3-37:152:2" are expanded to all
    intermediate ayahs. Cross-surah ranges (rare) only count endpoints.
    """
    seen: set[tuple[int, int]] = set()
    for key in segments:
        if key == "_meta":
            continue
        if "-" in key:
            parts = key.split("-")
            if len(parts) == 2:
                sp = parts[0].split(":")
                ep = parts[1].split(":")
                if len(sp) >= 2 and len(ep) >= 2:
                    try:
                        s_surah, s_ayah = int(sp[0]), int(sp[1])
                        e_surah, e_ayah = int(ep[0]), int(ep[1])
                    except ValueError:
                        continue
                    if s_surah == e_surah:
                        for a in range(s_ayah, e_ayah + 1):
                            seen.add((s_surah, a))
                    else:
                        seen.add((s_surah, s_ayah))
                        seen.add((e_surah, e_ayah))
                    continue
        sp = key.split(":")
        if len(sp) >= 2:
            try:
                seen.add((int(sp[0]), int(sp[1])))
            except ValueError:
                pass
    return seen


def compute_coverage(segments: dict) -> dict[str, int]:
    """Return {"surahs": N, "ayahs": M} from a segments.json dict."""
    ayahs = expand_segment_ayahs(segments)
    return {"surahs": len({s for s, _ in ayahs}), "ayahs": len(ayahs)}


def find_eligible_reciters(repo_root: Path) -> list[str]:
    """Slugs with both segments.json and timestamps.json git-tracked."""
    tracked = git_tracked_data_files(repo_root)
    candidates = set()
    for path in tracked:
        if path.startswith("data/recitation_segments/") and path.endswith("/segments.json"):
            parts = path.split("/")
            if len(parts) == 4:
                candidates.add(parts[2])
    return sorted(s for s in candidates if has_tracked_timestamps(s, repo_root))
