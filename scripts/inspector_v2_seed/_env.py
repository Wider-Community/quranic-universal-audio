"""Shared bootstrap for the cutover seed scripts.

Locates the repo-root ``.env`` and loads it into ``os.environ``, sets
``INSPECTOR_BACKEND=bucket`` so service-layer helpers route through the
real bucket, and configures UTF-8 stdout for Windows hosts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def load_repo_env() -> None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        env = parent / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(
                    k.strip(), v.strip().strip('"').strip("'")
                )
            break
        if (parent / ".git").exists():
            break

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
    return here.parents[2]
