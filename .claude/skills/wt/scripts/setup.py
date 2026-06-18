#!/usr/bin/env python3
"""Provision a fresh git worktree for minimal-friction dev.

A worktree shares .git but only checks out tracked files, so everything
gitignored is absent. Only three things actually differ from the main
worktree and block local dev; this script restores exactly those:

  1. .env + inspector/.env  — secrets (HF_TOKEN gates the bucket mount;
     QF creds; dev-owner attribution). Copied from the main worktree.
  2. root node_modules       — `npm ci` runs `prepare: husky`, regenerating
     .husky/_ so pre-commit/pre-push fire (core.hooksPath is relative,
     resolved per-worktree).
  3. inspector/frontend/node_modules — `npm ci`, the app's FE deps.

Deliberately NOT done (they take care of themselves):
  - backend pip deps   — installed into global site-packages, shared across
    worktrees via the same python3; no per-worktree reinstall.
  - inspector/.bucket  — FUSE-mounted on app boot from HF_TOKEN.
  - inspector.db       — pulled from the bucket + migrated on app boot.
  - dist/              — only the Flask :5000 server needs it; the dev loop
    is Vite HMR (:5173). Build manually if you need full-stack serving.

Idempotent and background-friendly: skips work already done, never aborts the
whole run on one failure. Run from inside the new worktree.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> bool:
    print(f"==> {' '.join(cmd)}  (in {cwd})", flush=True)
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"    FAILED: {exc}", file=sys.stderr, flush=True)
        return False


def _worktree_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(out)


def _main_root() -> Path:
    """The main worktree root — parent of the shared git common dir."""
    out = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(out).resolve().parent


def _copy_env(here: Path, main: Path) -> None:
    if here == main:
        print("==> in the main worktree; nothing to copy", flush=True)
        return
    for rel in (".env", "inspector/.env"):
        dst, src = here / rel, main / rel
        if dst.exists():
            print(f"==> {rel} already present; skipping", flush=True)
            continue
        if not src.exists():
            print(f"==> {rel} missing in main ({src}); skipping", flush=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"==> copied {rel} from main worktree", flush=True)


def main() -> int:
    here = _worktree_root()
    main = _main_root()
    print(f"worktree: {here}\nmain:     {main}\n", flush=True)

    _copy_env(here, main)

    ok = True
    ok &= _run(["npm", "ci"], cwd=here)                              # root: husky hooks
    ok &= _run(["npm", "ci"], cwd=here / "inspector" / "frontend")  # FE deps

    print("\nsetup complete." if ok else "\nsetup finished with errors (see above).",
          flush=True)
    return 0  # background-friendly: surface errors in logs, don't fail the run


if __name__ == "__main__":
    raise SystemExit(main())
