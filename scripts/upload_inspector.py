#!/usr/bin/env python3
"""Upload the Inspector to its target Hugging Face Space.

Usage::

    python -m scripts.upload_inspector dev   # → hetchyy/quranic-inspector-dev
    python -m scripts.upload_inspector prod  # → hetchyy/quranic-universal-audio

Build steps:

1. Build the frontend (``inspector/frontend`` → ``dist/``).
2. Stage the Space-shaped tree in a temp dir:
     - ``Dockerfile``               (copied from ``inspector/Dockerfile``)
     - ``inspector/...``            (code + frontend ``dist/``)
     - ``scripts/__init__.py`` + ``scripts/lib/...``
     - ``data/{surah_info,qpc_hafs,digital_khatt_v2_script,phoneme_sub_costs}.json``
     - ``.dockerignore``
     - ``README.md`` (Space frontmatter)
3. ``upload_folder`` to the Space repo (Hugging Face git+xet under the hood).

Auth: reads ``HF_TOKEN`` (or ``INSPECTOR_HF_TOKEN``) from ``$REPO/.env`` via
``scripts.inspector_v2_seed._env.load_repo_env``.

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

# Bring in the Inspector v2 .env loader so HF_TOKEN is available.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspector_v2_seed._env import load_repo_env, repo_root  # noqa: E402

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

# Quranic Universal Audio{suffix}

Read-only public surface (Phase 2). Anonymous browsers can view all reciters
across the Audio, Segments, and Timestamps tabs. Editing requires Hugging
Face sign-in (Phase 3, not yet wired) and an active claim.

This Space mirrors the `{branch}` branch of
[Wider-Community/quranic-universal-audio](https://github.com/Wider-Community/quranic-universal-audio).
Container builds on every push to that branch via the `inspector-deploy.yml`
GitHub workflow.
"""


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def _build_frontend(repo: Path) -> None:
    fe = repo / "inspector" / "frontend"
    if not (fe / "node_modules").is_dir():
        _run(["npm", "ci"], cwd=fe)
    _run(["npm", "run", "build"], cwd=fe)


def _stage(repo: Path, stage_root: Path, env: str, branch: str) -> None:
    suffix = " (dev)" if env == "dev" else ""
    (stage_root / "README.md").write_text(
        SPACE_README.format(suffix=suffix, branch=branch),
        encoding="utf-8",
    )

    # Dockerfile sits at the Space root.
    shutil.copy2(repo / "inspector" / "Dockerfile", stage_root / "Dockerfile")
    shutil.copy2(repo / ".dockerignore", stage_root / ".dockerignore")

    # Code trees.
    for src_rel in ("inspector",):
        src = repo / src_rel
        dst = stage_root / src_rel
        shutil.copytree(
            src,
            dst,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                "tests",
                ".pytest_cache",
                ".mypy_cache",
                "node_modules",
                ".vite",
                # Keep dist/ — that's the built frontend.
            ),
        )

    # scripts/lib/ only (top-level CLIs not needed at runtime).
    scripts_dst = stage_root / "scripts"
    scripts_dst.mkdir()
    shutil.copy2(repo / "scripts" / "__init__.py", scripts_dst / "__init__.py")
    shutil.copytree(
        repo / "scripts" / "lib",
        scripts_dst / "lib",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    # Data — only the four linguistic JSON files. Everything else lives in the
    # bucket mounted at /data/inspector-bucket inside the Space.
    data_dst = stage_root / "data"
    data_dst.mkdir()
    for name in (
        "surah_info.json",
        "qpc_hafs.json",
        "digital_khatt_v2_script.json",
        "phoneme_sub_costs.json",
    ):
        shutil.copy2(repo / "data" / name, data_dst / name)


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
        "--skip-build",
        action="store_true",
        help="Skip `npm run build` (use the existing dist/).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Stage but don't upload. Prints stage path and exits.",
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

    print(f"==> Building Inspector for {args.env} ({repo_id})")
    if not args.skip_build:
        _build_frontend(repo)
    else:
        print("  (skip-build) using existing dist/")

    sha = _commit_sha(repo)
    commit_msg = f"deploy: inspector {args.env} @ {sha}"

    with tempfile.TemporaryDirectory(prefix=f"inspector-stage-{args.env}-") as tmp:
        stage_root = Path(tmp)
        print(f"==> Staging Space tree in {stage_root}")
        _stage(repo, stage_root, args.env, branch)

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
