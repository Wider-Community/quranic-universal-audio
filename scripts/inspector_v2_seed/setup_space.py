"""Idempotently set up the Inspector Hugging Face Space.

Creates the Space (private) if absent, attaches the bucket volume, sets all
required secrets + variables, and writes the README frontmatter. Replaces
the manual runbook §1/§2 steps.

Usage::

    python -m scripts.inspector_v2_seed.setup_space dev          # dry-run
    python -m scripts.inspector_v2_seed.setup_space dev --apply   # mutate

Auto-generated values (printed once on creation, then read back from the
existing secret):

- ``INSPECTOR_SESSION_SECRET``  — 32-byte hex (signs cookies, Phase 3+)
- ``INSPECTOR_JOB_CALLBACK_SECRET`` — 32-byte hex (HF Job webhook auth, Phase 5+)

Caller-supplied values:

- ``INSPECTOR_HF_TOKEN`` — copied from local ``.env`` (write scope on bucket).
  Migrate to a dedicated ``hetchyy-bot`` token before prod cutover.
- ``INSPECTOR_GITHUB_DISPATCH_TOKEN`` — placeholder; replace with a real
  fine-grained PAT (``actions: write`` on the project repo) before Phase 5.

Idempotent. Safe to re-run on every config change.
"""

from __future__ import annotations

import argparse
import os
import secrets as _secrets
import sys
from pathlib import Path

from huggingface_hub import HfApi, Volume

from ._env import load_repo_env

SPACE_REPOS = {
    "dev": "hetchyy/quranic-inspector-dev",
    "prod": "hetchyy/quranic-inspector",
}

BUCKET_REPOS = {
    "dev": "hetchyy/quranic-inspector-bucket-dev",
    "prod": "hetchyy/quranic-inspector-bucket",
}

MOUNT_PATH = "/data/inspector-bucket"


def _readme(env: str, branch: str) -> str:
    suffix = " (dev)" if env == "dev" else ""
    return f"""---
title: Quranic Inspector{suffix}
emoji: 🎙️
colorFrom: yellow
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
hf_oauth: true
hf_oauth_expiration_minutes: 480
---

# Quranic Inspector{suffix}

Read-only public surface (Phase 2). Anonymous browsers can view all reciters
across the Audio, Segments, and Timestamps tabs. Editing requires Hugging
Face sign-in (Phase 3, not yet wired) and an active claim.

This Space mirrors the `{branch}` branch of
[Wider-Community/quranic-universal-audio](https://github.com/Wider-Community/quranic-universal-audio)
and rebuilds on every push via the `inspector-deploy.yml` GitHub workflow.
"""


def _existing_secrets(api: HfApi, repo_id: str) -> set[str]:
    """Names only — values are write-only."""
    try:
        runtime = api.get_space_runtime(repo_id=repo_id)
        return {s.key for s in (runtime.secrets or [])}
    except Exception:
        return set()


def _existing_variables(api: HfApi, repo_id: str) -> dict[str, str]:
    try:
        return {k: v.value for k, v in api.get_space_variables(repo_id=repo_id).items()}
    except Exception:
        return {}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("env", choices=("dev", "prod"))
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually mutate. Default is dry-run (prints planned actions).",
    )
    args = p.parse_args(argv)

    load_repo_env()
    token = os.environ.get("HF_TOKEN") or os.environ.get("INSPECTOR_HF_TOKEN")
    if not token:
        print("ERROR: HF_TOKEN missing in env (.env at repo root).", file=sys.stderr)
        return 2

    api = HfApi(token=token)
    repo_id = SPACE_REPOS[args.env]
    bucket_repo = BUCKET_REPOS[args.env]
    branch = "dev" if args.env == "dev" else "main"
    apply = args.apply

    print(f"==> Target Space:  {repo_id}  (private)")
    print(f"==> Target bucket: {bucket_repo}  → {MOUNT_PATH}")
    print(f"==> Mode:          {'APPLY' if apply else 'DRY-RUN'}")

    # --- 1. Create the Space if absent ---
    print("\n[1/4] Create Space (idempotent)...")
    if apply:
        api.create_repo(
            repo_id=repo_id,
            repo_type="space",
            space_sdk="docker",
            private=True,
            exist_ok=True,
        )
        print(f"  OK — {repo_id}")
    else:
        print(f"  (dry-run) would create {repo_id} private docker Space")

    # --- 2. Write README.md frontmatter ---
    print("\n[2/4] Write README frontmatter (hf_oauth: true)...")
    readme = _readme(args.env, branch)
    if apply:
        api.upload_file(
            path_or_fileobj=readme.encode("utf-8"),
            path_in_repo="README.md",
            repo_id=repo_id,
            repo_type="space",
            commit_message="chore(space): refresh README frontmatter (setup_space)",
        )
        print("  OK")
    else:
        print(f"  (dry-run) would upload README.md ({len(readme)} bytes)")

    # --- 3. Attach the bucket volume ---
    print(f"\n[3/4] Attach bucket volume {bucket_repo} -> {MOUNT_PATH}...")
    if apply:
        api.set_space_volumes(
            repo_id=repo_id,
            volumes=[
                Volume(
                    type="bucket",
                    source=bucket_repo,
                    mount_path=MOUNT_PATH,
                ),
            ],
        )
        print("  OK")
    else:
        print(
            f"  (dry-run) would set_space_volumes(volumes=[Volume(bucket, "
            f"{bucket_repo}, {MOUNT_PATH})])"
        )

    # --- 4. Secrets + variables ---
    print("\n[4/4] Set secrets + variables (idempotent; auto-gen if absent)...")

    existing_secrets = _existing_secrets(api, repo_id) if apply else set()
    existing_vars = _existing_variables(api, repo_id) if apply else {}

    # variables (non-secret, set every run so changes propagate)
    variables = {
        "INSPECTOR_BUCKET_REPO": bucket_repo,
        "INSPECTOR_BUCKET_MOUNT": MOUNT_PATH,
        "INSPECTOR_TS_SOURCE": "bucket",
        "INSPECTOR_AUDIO_PROXY_ENABLED": "0",
        "INSPECTOR_TS_VALIDATE_ENABLED": "0",
        "INSPECTOR_PARSED_CACHE_BYTES": "134217728",
        "GUNICORN_WORKERS": "1",
    }
    for k, v in variables.items():
        if existing_vars.get(k) == v and apply:
            print(f"  variable {k:38s}  unchanged")
            continue
        if apply:
            api.add_space_variable(repo_id=repo_id, key=k, value=v)
            print(f"  variable {k:38s}  set")
        else:
            print(f"  (dry-run) variable {k}={v}")

    # secrets — preserve existing, generate if missing
    secret_plan = [
        ("INSPECTOR_HF_TOKEN", token, "HF token (bucket write scope)"),
        (
            "INSPECTOR_SESSION_SECRET",
            None,
            "32-byte hex; auto-generate if absent (Phase 3 cookie signing)",
        ),
        (
            "INSPECTOR_JOB_CALLBACK_SECRET",
            None,
            "32-byte hex; auto-generate if absent (Phase 5 HF Job callback)",
        ),
        (
            "INSPECTOR_GITHUB_DISPATCH_TOKEN",
            "PLACEHOLDER_REPLACE_BEFORE_PHASE_5",
            "Fine-grained PAT (actions:write); placeholder until Phase 5",
        ),
    ]
    for key, value, note in secret_plan:
        if apply and key in existing_secrets and value is None:
            print(f"  secret   {key:38s}  preserved ({note})")
            continue
        v = value if value is not None else _secrets.token_hex(32)
        if apply:
            api.add_space_secret(repo_id=repo_id, key=key, value=v)
            preview = "<auto-gen>" if value is None else "<copied>"
            print(f"  secret   {key:38s}  set ({preview}; {note})")
            if value is None and key not in existing_secrets:
                # Print auto-gen value once for the operator to record.
                print(f"           -> first-run value for {key}: {v}")
        else:
            preview = "<auto-gen>" if value is None else "<set>"
            print(f"  (dry-run) secret {key}={preview} ({note})")

    if apply:
        print("\n==> Restarting Space (factory reboot to pick up volume + env)...")
        api.restart_space(repo_id=repo_id, factory_reboot=True)
        print(f"==> Done. Space: https://huggingface.co/spaces/{repo_id}")
        print(f"            URL: https://{repo_id.replace('/', '-')}.hf.space")
    else:
        print(
            "\n==> DRY-RUN complete. Re-run with --apply to mutate.\n"
            "    All operations above are idempotent; safe to re-run."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
