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
