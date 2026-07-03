#!/usr/bin/env python3
"""Fast worktree bootstrap — mirror `.env` + `node_modules` from the main checkout.

A freshly-added linked git worktree has no `.env` and empty `node_modules`, so
`npm run test`/`check`/`lint`/`build` and `/launch` all fail until deps exist.
Re-running the full `setup.sh` (`npm ci` + `pip`) per worktree is slow; this
copies the already-installed trees from the main worktree instead:

  - `.env`                              (root env file)
  - `node_modules`                      (root — husky + lint-staged for git hooks)
  - `inspector/frontend/node_modules`   (the SPA toolchain: vite / svelte / vitest)

Idempotent: skips anything already present in the worktree, never clobbers an
existing `.env`. If the main checkout itself has no `node_modules` to copy, it
falls back to `scripts/devenv/setup.sh frontend` so a first-ever setup still
works. Cross-platform: robocopy on Windows, `cp -a` elsewhere. Invoked by the
`wt` skill; safe to run from any worktree (a no-op from the main one).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _main_worktree_root(here: Path) -> Path:
    """Root of the main worktree (the one holding the shared `.git` dir)."""
    common = Path(_git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=here))
    return common.parent


def _copy_dir(src: Path, dst: Path) -> None:
    """Recursively copy `src` → `dst` using the fastest tool per OS."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        # robocopy exit codes 0-7 are success (8+ is a real failure).
        code = subprocess.run(
            [
                "robocopy",
                str(src),
                str(dst),
                "/E",
                "/MT:16",
                "/NFL",
                "/NDL",
                "/NJH",
                "/NJS",
                "/NP",
                "/R:1",
                "/W:1",
            ],
        ).returncode
        if code >= 8:
            raise RuntimeError(f"robocopy failed ({code}) copying {src} -> {dst}")
    else:
        dst.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cp", "-a", f"{src}/.", str(dst)], check=True)


def _has_entries(p: Path) -> bool:
    return p.is_dir() and any(p.iterdir())


def _mirror(main: Path, here: Path) -> None:
    env_src, env_dst = main / ".env", here / ".env"
    if env_dst.exists():
        print("  .env: present, kept")
    elif env_src.is_file():
        env_dst.write_bytes(env_src.read_bytes())
        print("  .env: copied from main")
    else:
        print("  .env: none in main, skipped")

    fe = Path("inspector/frontend/node_modules")
    for rel in (Path("node_modules"), fe):
        src, dst = main / rel, here / rel
        if _has_entries(dst):
            print(f"  {rel.as_posix()}: present, kept")
        elif _has_entries(src):
            print(f"  {rel.as_posix()}: copying from main ...")
            _copy_dir(src, dst)
            print(f"  {rel.as_posix()}: done")
        elif rel == fe:
            print("  inspector/frontend/node_modules: none in main; running setup.sh frontend")
            subprocess.run(["bash", str(here / "scripts/devenv/setup.sh"), "frontend"], check=True)
        else:
            print(f"  {rel.as_posix()}: none in main, skipped")


def main() -> int:
    here = Path(_git("rev-parse", "--show-toplevel")).resolve()
    main_root = _main_worktree_root(here).resolve()
    if main_root == here:
        print("Already in the main worktree — nothing to mirror.")
        return 0
    print(f"Bootstrapping worktree from {main_root} ...")
    _mirror(main_root, here)
    print("Worktree ready. Use the pinned npm scripts (npm run check / build / test).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
