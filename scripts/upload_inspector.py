#!/usr/bin/env python3
"""Upload the Inspector to its target Hugging Face Space.

Usage::
https://huggingface.co/hetchyy

    python -m scripts.upload_inspector dev   # → hetchyy/quranic-inspector-dev
    python -m scripts.upload_inspector prod  # → hetchyy/quranic-universal-audio

Build steps:

1. Stage the Space build context: every git-tracked file, copied verbatim,
   plus two Space-specific overlays (root ``Dockerfile`` + frontmatter
   ``README.md``). The image's contents are defined solely by
   ``inspector/Dockerfile`` + ``.dockerignore`` (both tracked, both consumed
   identically here and by ``docker-publish.yml``'s repo-root build), so there
   is no hand-maintained file allowlist to drift from the Dockerfile's ``COPY``
   set — ``.dockerignore`` prunes at build time. The frontend ``dist/`` is
   built inside the image (Dockerfile stage 1); nothing is pre-built here.
2. ``upload_folder`` to the Space repo (Hugging Face git+xet under the hood),
   with ``delete_patterns="*"`` so the Space tree mirrors the staged tree.

Because the staged tree is the whole tracked repo, the Space build context
equals the ``context: .`` context that ``docker-publish.yml`` builds on every
push — a green CI image build is a faithful guarantee the Space will compile.

Auth: reads ``HF_TOKEN`` (or ``INSPECTOR_HF_TOKEN``) from ``$REPO/.env`` via
``scripts.lib._env.load_repo_env``.

Idempotent: re-running uploads only the changed files (the Hub diffs by
content hash). Safe to run from a fresh checkout.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

# Bring in the .env loader so HF_TOKEN is available.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib._env import load_repo_env, repo_root  # noqa: E402

SPACE_REPOS = {
    "dev": "hetchyy/quranic-inspector-dev",
    "prod": "hetchyy/quranic-universal-audio",
}

# README frontmatter shipped to the Space. Mirrors the runbook §1 setup.
SPACE_README = """---
title: Quranic Universal Audio{suffix}
emoji: 🎙️
colorFrom: yellow
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
hf_oauth: true
hf_oauth_expiration_minutes: 480
---
"""


def _git_tracked_files(repo: Path) -> list[str]:
    """Repo-relative paths of every git-tracked file (the Space build context)."""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return [p for p in out.stdout.split("\0") if p]


def _stage(repo: Path, stage_root: Path, env: str, branch: str) -> None:
    """Stage the Space build context: every git-tracked file, verbatim.

    The image's contents are defined solely by ``inspector/Dockerfile`` +
    ``.dockerignore`` (both tracked, both consumed identically here and by
    ``docker-publish.yml``'s ``context: .`` build), so there is no hand-curated
    allowlist to drift from the Dockerfile's ``COPY`` set — ``.dockerignore``
    prunes at build time. Two Space-specific overlays are written on top of the
    tracked tree:

    * ``Dockerfile`` at the root — the Hub docker SDK reads it there, but ours
      lives under ``inspector/``.
    * ``README.md`` — the Space frontmatter, written last so it wins over the
      repo's tracked root ``README.md``.

    The frontend ``dist/`` is built inside the image (Dockerfile stage 1), so
    nothing is pre-built here.
    """
    for rel in _git_tracked_files(repo):
        src = repo / rel
        if not src.is_file():
            continue  # tracked but absent in the worktree (e.g. deleted)
        dst = stage_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    shutil.copy2(repo / "inspector" / "Dockerfile", stage_root / "Dockerfile")

    suffix = " (dev)" if env == "dev" else ""
    (stage_root / "README.md").write_text(
        SPACE_README.format(suffix=suffix, branch=branch),
        encoding="utf-8",
    )


def _upload(stage_root: Path, repo_id: str, token: str, commit_msg: str) -> str:
    api = HfApi(token=token)
    api.create_repo(
        repo_id=repo_id,
        repo_type="space",
        space_sdk="docker",
        private=True,
        exist_ok=True,
    )
    api.upload_folder(
        folder_path=str(stage_root),
        repo_id=repo_id,
        repo_type="space",
        commit_message=commit_msg,
        delete_patterns="*",
    )
    # Code-only pushes don't change the Dockerfile hash, so HF doesn't
    # rebuild the container automatically — the new commit shows up in
    # the Space repo but the running container still serves the previous
    # bundle. Force a factory reboot so the new code actually runs.
    api.restart_space(repo_id=repo_id, factory_reboot=True)
    return f"https://huggingface.co/spaces/{repo_id}"


def _commit_sha(repo: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("env", choices=("dev", "prod"))
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Stage but don't upload. Prints stage path and exits.",
    )
    p.add_argument(
        "--verify-boot",
        action="store_true",
        help=(
            "Before uploading, build the staged context and boot it offline "
            "(filesystem fixtures), asserting /healthz is 200. Aborts the "
            "deploy if the image won't build or boot. Needs Docker."
        ),
    )
    args = p.parse_args(argv)

    load_repo_env()
    token = (
        os.environ.get("INSPECTOR_HF_TOKEN")
        or os.environ.get("HF_TOKEN")
    )
    if not token:
        print(
            "ERROR: HF_TOKEN / INSPECTOR_HF_TOKEN missing in env. "
            "Add it to .env at the worktree root.",
            file=sys.stderr,
        )
        return 2

    repo = repo_root()
    repo_id = SPACE_REPOS[args.env]
    branch = "dev" if args.env == "dev" else "main"

    print(f"==> Deploying Inspector to {args.env} ({repo_id})")
    sha = _commit_sha(repo)
    commit_msg = f"deploy: inspector {args.env} @ {sha}"

    with tempfile.TemporaryDirectory(prefix=f"inspector-stage-{args.env}-") as tmp:
        stage_root = Path(tmp)
        print(f"==> Staging Space tree in {stage_root}")
        _stage(repo, stage_root, args.env, branch)

        if args.verify_boot:
            print("==> Verifying the staged image builds and boots...")
            smoke = repo / "inspector" / "scripts" / "smoke_boot.py"
            subprocess.run(
                [sys.executable, str(smoke), "--context", str(stage_root)],
                check=True,
            )

        if args.dry_run:
            print(f"==> Dry run; stage at {stage_root} (not deleted on dry-run)")
            # Move out of the temp context so it survives.
            keep = repo / ".local" / "inspector-stage" / args.env
            keep.parent.mkdir(parents=True, exist_ok=True)
            if keep.exists():
                shutil.rmtree(keep)
            shutil.copytree(stage_root, keep)
            print(f"    Copied to {keep}")
            return 0

        print(f"==> Uploading to {repo_id}")
        url = _upload(stage_root, repo_id, token, commit_msg)
        print(f"==> Done. Space: {url}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
