"""Shared bootstrap for the cutover seed scripts.

Locates the repo-root ``.env`` and loads it into ``os.environ``, sets
``INSPECTOR_BACKEND=bucket`` so service-layer helpers route through the
real bucket, and configures UTF-8 stdout for Windows hosts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _candidate_env_files() -> list[Path]:
    """Return .env locations to try, in priority order.

    1. Worktree-local (cwd or any ancestor up to its .git marker).
    2. Main repo root — when running inside a linked git worktree, the
       worktree's `.git` is a file pointing at `<main>/.git/worktrees/<name>`;
       walk that to find the main checkout's `.env` so secrets live in one
       place across worktrees.
    """
    out: list[Path] = []
    here = Path(__file__).resolve()
    seen_worktree = False
    for parent in here.parents:
        env = parent / ".env"
        if env.exists():
            out.append(env)
        marker = parent / ".git"
        if marker.exists():
            seen_worktree = True
            # Linked worktree → .git is a file containing `gitdir: <path>`.
            try:
                if marker.is_file():
                    text = marker.read_text(encoding="utf-8").strip()
                    if text.startswith("gitdir:"):
                        gitdir = Path(text.split(":", 1)[1].strip()).resolve()
                        # gitdir points to <main>/.git/worktrees/<name> → up 3
                        # to get the main repo root.
                        main_root = gitdir.parent.parent.parent
                        candidate = main_root / ".env"
                        if candidate.exists():
                            out.append(candidate)
            except Exception:
                pass
            break
    if not seen_worktree:
        # Fallback: walk all the way up.
        for parent in here.parents:
            env = parent / ".env"
            if env.exists() and env not in out:
                out.append(env)
    return out


def load_repo_env() -> None:
    for env in _candidate_env_files():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(
                k.strip(), v.strip().strip('"').strip("'")
            )

    os.environ.setdefault("INSPECTOR_BACKEND", "bucket")

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def repo_root() -> Path:
    # ``.git`` lives at the worktree root only (as a directory in the main
    # checkout, as a file in linked worktrees). Sub-dirs may have their own
    # ``.gitignore`` so that marker is unreliable.
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    return here.parents[1]
