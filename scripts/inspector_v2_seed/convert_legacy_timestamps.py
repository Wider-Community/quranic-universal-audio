"""Bridge: convert legacy gzipped per-chapter timestamps shards to v2 paths.

Reads ``<bucket>/timestamps/<slug>/<chapter>.json.gz`` for every completed
reciter and re-uploads as ungzipped ``<bucket>/published/<slug>/timestamps/<chapter>.json``.

This is a one-shot migration: it lets D20 Option B drop the legacy bucket
layout before Phase 6's HF Job lands per-chapter timestamps natively. After
this runs, Phase 6's job-completion writer just keeps writing to the same
path; the legacy ``timestamps/<slug>/`` subtree can be deleted.

Run after Track A (aligner Preload migration) is ready to deploy.

Idempotent: re-running re-uploads the same content (no-op on Xet dedup).
"""

from __future__ import annotations

import gzip
import os
import sys
from pathlib import Path

from ._env import load_repo_env

load_repo_env()

import time

from huggingface_hub import batch_bucket_files, hffs, list_bucket_tree

from inspector.services import state as state_service
from inspector.services import storage_paths
from inspector.services.hf_bucket import get_backend
from scripts.lib.schemas import ReciterState


def _retry(fn, *, label, attempts=3, delay=2.0):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except RuntimeError as e:
            # httpx "Cannot send a request, as the client has been closed."
            # — observed after many alternating reads/writes against hffs.
            # Refresh by logging in again on the next attempt.
            last = e
            print(f"  {label} attempt {i + 1}/{attempts} failed: {e}", file=sys.stderr)
            time.sleep(delay * (i + 1))
            from huggingface_hub import login as _hf_login

            _hf_login(
                token=os.environ.get("INSPECTOR_HF_TOKEN") or os.environ.get("HF_TOKEN"),
                add_to_git_credential=False,
            )
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  {label} attempt {i + 1}/{attempts} failed: {e}", file=sys.stderr)
            time.sleep(delay * (i + 1))
    raise last  # type: ignore[misc]


def main() -> int:
    bucket = os.environ.get(
        "INSPECTOR_BUCKET_REPO", "hetchyy/quranic-inspector-bucket-dev"
    )
    get_backend()  # forces login() once
    state_service.hydrate()

    completed = [
        r.slug
        for r in state_service.snapshot().reciters
        if r.state == ReciterState.COMPLETED
    ]
    if not completed:
        print("FAIL: no completed reciters in state file", file=sys.stderr)
        return 1
    print(f"converting timestamps for {len(completed)} completed reciter(s)")

    tmp_root = Path(os.environ.get("TEMP") or "/tmp") / "inspector-ts-convert"
    tmp_root.mkdir(parents=True, exist_ok=True)

    # ---- Pass 1: read all shards from bucket to local tmp, decompress ----
    plan: list[tuple[str, Path, str]] = []  # (slug, local_path, dest_path)
    for slug in completed:
        prefix = f"timestamps/{slug}"
        entries = _retry(
            lambda p=prefix: [
                it.path
                for it in list_bucket_tree(bucket, prefix=p, recursive=False)
                if it.type == "file" and it.path.endswith(".json.gz")
            ],
            label=f"list({prefix})",
        )
        if not entries:
            print(f"  skip {slug}: no legacy shards")
            continue
        local_dir = tmp_root / slug
        local_dir.mkdir(parents=True, exist_ok=True)
        for path in entries:
            chapter = Path(path).name.removesuffix(".json.gz")
            local_path = local_dir / f"{chapter}.json"
            if not local_path.exists():
                # hffs.cat_file is the read primitive for HF buckets (there
                # is no hf_hub_download for repo_type=bucket). The httpx
                # lifecycle issue we saw earlier was alternating reads with
                # writes; here we read all then write all, so reads stay
                # batched and the retry wrapper catches any stray closure.
                gz_body = _retry(
                    lambda p=path: hffs.cat_file(f"buckets/{bucket}/{p}"),
                    label=f"read({path})",
                )
                body = gzip.decompress(gz_body)
                local_path.write_bytes(body)
            plan.append(
                (slug, local_path, storage_paths.published_timestamps_path(slug, chapter))
            )
        print(f"  read pass  {slug:35s} {len(entries):3d} shards staged")

    # ---- Pass 2: upload everything in chunks ----
    print(f"upload pass: {len(plan)} files in chunks of 100 ...")
    chunk = 100
    uploaded = 0
    for i in range(0, len(plan), chunk):
        batch = plan[i : i + chunk]
        pairs = [(str(lp.resolve()), dst) for (_slug, lp, dst) in batch]
        _retry(
            lambda p=pairs: batch_bucket_files(bucket, add=p),
            label=f"upload[{i}:{i + chunk}]",
        )
        uploaded += len(batch)
        print(f"  uploaded {uploaded}/{len(plan)}")

    print(f"ok  converted {uploaded} timestamps shards across {len(completed)} reciters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
