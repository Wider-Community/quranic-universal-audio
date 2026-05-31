"""Shared recitation eligibility checks.

v2: the canonical store for lifecycle is the Inspector SQLite DB. v1 gated
eligibility on ``git ls-files data/timestamps/ data/recitation_segments/`` —
that worked because legacy releases committed both files to the repo when a
reciter shipped. v2 publish tracks (``per_recitation_releases``) keep state
in the DB; the legacy data/ paths are dropped post-Phase-3.

Public entry points keep their v1 signatures so the offline callers
(``.github/scripts/*`` and the new ``scripts/jobs/cut_release.py``) don't
churn. Internally, when an Inspector DB connection is available we use it;
when running outside Inspector (e.g. legacy GitHub Actions still in flight
during the migration window), we fall back to the git-tracked check so the
old release.yml keeps working until Phase 2 deletes it.

Both backends produce the same set of slugs at the cutover boundary
(Phase-1 acceptance test in ``inspector/scripts/check_eligibility_parity.py``).
"""

from __future__ import annotations

import functools
import os
import subprocess
from pathlib import Path
from typing import Iterable

_TRACKED_CACHE: dict[Path, set[str]] = {}
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------------
# Backend selection
# ----------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _has_inspector_db() -> bool:
    """True iff an Inspector DB connection is reachable from this process.

    Cached: the answer doesn't change within one process run, and the
    public API (``has_tracked_timestamps``) is called per-slug across
    hundreds of recitations from offline scripts. Force a re-check with
    ``_has_inspector_db.cache_clear()``.

    Imports are deferred so the offline callers (which never set up the
    Inspector boot path) don't trip on missing optional deps.
    """
    if os.environ.get("INSPECTOR_ELIGIBILITY_BACKEND") == "git":
        return False
    try:
        from inspector.services.db import connection as _conn  # noqa: F401
    except Exception:
        return False
    try:
        _conn.get_conn()
    except Exception:
        return False
    return True


# ----------------------------------------------------------------------
# Git backend (legacy fallback)
# ----------------------------------------------------------------------


def _resolve_root(repo_root: Path | None) -> Path:
    return (repo_root or _DEFAULT_REPO_ROOT).resolve()


def git_tracked_data_files(repo_root: Path | None = None) -> set[str]:
    """Cached ``git ls-files`` for data/timestamps + data/recitation_segments.

    Legacy fallback only. Returns an empty set when neither path is tracked.
    """
    repo_root = _resolve_root(repo_root)
    if repo_root not in _TRACKED_CACHE:
        result = subprocess.run(
            ["git", "ls-files", "data/timestamps/", "data/recitation_segments/"],
            capture_output=True, text=True, cwd=repo_root,
        )
        _TRACKED_CACHE[repo_root] = set(result.stdout.strip().splitlines())
    return _TRACKED_CACHE[repo_root]


def tracked_timestamps_audio_type(slug: str, repo_root: Path | None = None) -> str | None:
    """Return the audio_type whose ``timestamps.json`` is git-tracked, else None."""
    tracked = git_tracked_data_files(repo_root)
    for audio_type in ("by_ayah_audio", "by_surah_audio"):
        if f"data/timestamps/{audio_type}/{slug}/timestamps.json" in tracked:
            return audio_type
    return None


def _git_eligible_set(repo_root: Path | None = None) -> set[str]:
    tracked = git_tracked_data_files(repo_root)
    candidates: set[str] = set()
    for path in tracked:
        if path.startswith("data/recitation_segments/") and path.endswith("/segments.json"):
            parts = path.split("/")
            if len(parts) == 4:
                candidates.add(parts[2])
    return {s for s in candidates if tracked_timestamps_audio_type(s, repo_root)}


# ----------------------------------------------------------------------
# DB backend (v2 canonical)
# ----------------------------------------------------------------------


def _db_eligible_set() -> set[str]:
    """Slugs whose delivery is RELEASED and publicly visible — the v2 equivalent of the v1 set.

    The legacy git-tracked set was exactly the slugs that had been published
    (segments+timestamps committed when a reciter went live). ``state =
    'released' AND visibility = 'public'`` is the same set in the DB; a
    discarded released row isn't shipped, so it doesn't appear here either.
    """
    from inspector.services.db import connection as _conn
    rows = _conn.get_conn().execute(
        "SELECT slug FROM delivery_states "
        "WHERE state = 'released' AND visibility = 'public' "
        "ORDER BY slug"
    ).fetchall()
    return {r["slug"] for r in rows}


# ----------------------------------------------------------------------
# Public API (unchanged signatures)
# ----------------------------------------------------------------------


def has_tracked_timestamps(slug: str, repo_root: Path | None = None) -> bool:
    """True iff ``slug`` is eligible — has shipped TS available.

    Passing ``repo_root`` forces the git backend (callers explicitly asking
    "is this slug git-tracked under this repo") — keeps offline scripts'
    semantics intact even when an Inspector DB happens to be reachable.
    """
    if repo_root is None and _has_inspector_db():
        return slug in _db_eligible_set()
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


def find_eligible_reciters(repo_root: Path | None = None) -> list[str]:
    """Sorted list of eligible slugs (v2: state='released' in DB; v1 fallback: git-tracked).

    Passing ``repo_root`` forces the git backend.
    """
    if repo_root is None and _has_inspector_db():
        return sorted(_db_eligible_set())
    return sorted(_git_eligible_set(repo_root))


def eligible_set_via(backend: str, repo_root: Path | None = None) -> set[str]:
    """Phase-1 acceptance helper — returns the set under a specific backend.

    ``backend`` ∈ {"db", "git"}. Used by ``check_eligibility_parity.py`` to
    assert the two backends agree at cutover.
    """
    if backend == "db":
        return _db_eligible_set()
    if backend == "git":
        return _git_eligible_set(repo_root)
    raise ValueError(f"unknown backend: {backend!r}")
