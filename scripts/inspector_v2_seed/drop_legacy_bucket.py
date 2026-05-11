"""Drop the legacy bucket layout: manifest.json.gz + segments/<slug>/ + timestamps/<slug>/.

Runs after D20 Track A (aligner Preload migration) + Track B (Inspector TS-tab
catalog migration) + the timestamps bridge converter (see
``convert_legacy_timestamps.py``) have all landed. At that point nothing in
the system reads the legacy bucket layout — the aligner Preload reads from
``<bucket>/catalog/`` + ``<bucket>/published/<slug>/{segments,timestamps/<n>}.json``,
and the Inspector deployed TS tab reads from ``/api/static/catalog.json``.

Destructive — there is no undo on a bucket. Refuses to run unless ``--confirm``
is passed. Re-running is idempotent (404s on already-deleted files are ignored).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from ._env import load_repo_env

load_repo_env()

from huggingface_hub import batch_bucket_files, list_bucket_tree

from inspector.services.hf_bucket import get_backend


def _retry(fn, *, label, attempts=3, delay=2.0):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  {label} attempt {i + 1}/{attempts} failed: {e}", file=sys.stderr)
            time.sleep(delay * (i + 1))
            from huggingface_hub import login as _hf_login

            _hf_login(
                token=os.environ.get("INSPECTOR_HF_TOKEN") or os.environ.get("HF_TOKEN"),
                add_to_git_credential=False,
            )
    raise last  # type: ignore[misc]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="drop_legacy_bucket")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to actually perform the deletion (no-op without it)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List paths that would be deleted; no deletion",
    )
    args = parser.parse_args(argv)

    bucket = os.environ.get(
        "INSPECTOR_BUCKET_REPO", "hetchyy/quranic-inspector-bucket-dev"
    )
    get_backend()  # forces login() once

    print(f"scanning {bucket} for legacy paths ...")
    all_files = list(list_bucket_tree(bucket, recursive=True))
    legacy: list[str] = []
    for f in all_files:
        if f.type != "file":
            continue
        path = f.path
        if path == "manifest.json.gz":
            legacy.append(path)
        elif path.startswith("segments/") or path.startswith("timestamps/"):
            legacy.append(path)

    if not legacy:
        print("no legacy files to delete. bucket already clean.")
        return 0

    by_top = {
        "manifest.json.gz": sum(1 for p in legacy if p == "manifest.json.gz"),
        "segments/": sum(1 for p in legacy if p.startswith("segments/")),
        "timestamps/": sum(1 for p in legacy if p.startswith("timestamps/")),
    }
    print(f"legacy files to delete: {len(legacy)}")
    for k, n in by_top.items():
        print(f"  {k:18s}  {n}")

    if args.dry_run or not args.confirm:
        if args.dry_run:
            print("\nDRY RUN — first 20 paths:")
            for p in legacy[:20]:
                print(f"  {p}")
        else:
            print("\nrefusing to delete without --confirm. Re-run with --confirm to proceed.")
        return 0

    chunk = 200
    deleted = 0
    for i in range(0, len(legacy), chunk):
        batch = legacy[i : i + chunk]
        _retry(
            lambda b=batch: batch_bucket_files(bucket, delete=b),
            label=f"delete[{i}:{i + chunk}]",
        )
        deleted += len(batch)
        print(f"  deleted {deleted}/{len(legacy)}")

    print(f"ok  dropped {deleted} legacy files from {bucket}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
