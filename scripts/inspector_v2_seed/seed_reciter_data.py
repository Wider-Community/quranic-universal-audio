"""Upload per-reciter data files to ``<bucket>/{wip,published}/<slug>/``.

For each reciter row in ``<bucket>/state/reciter_state.json``:

- ``state == completed`` → upload under ``published/<slug>/``
- otherwise → upload under ``wip/<slug>/``

Per-reciter files uploaded (if present on disk):
- ``segments.json``, ``detailed.json``, ``edit_history.jsonl``,
  ``edit_history_peaks.jsonl``, ``low_confidence_v2.json``

**Timestamps are intentionally NOT uploaded.** Per
inspector-data-storage.md §1, timestamps live on the public HF dataset
(``hetchyy/quranic-universal-ayahs``) — Inspector reads them browser →
HF CDN direct. The ``published/<slug>/timestamps/`` subtree on the
bucket fills in later via the HF Job triggered by ``reciter.published``
(Phase 6 work).

Skipped on disk:
- ``validation.log`` and ``*.bak`` — legacy dev artifacts. Post-cutover
  Inspector never produces either (validators are libraries, save flow
  drops ``backup_file()``).

Uses ``batch_bucket_files`` directly (bypasses the storage backend's
single-file write helpers) for throughput on the ~14 × 5 file fan-out.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ._env import load_repo_env, repo_root

load_repo_env()

from huggingface_hub import batch_bucket_files

from scripts.lib.schemas import ReciterState
from inspector.services import state as state_service
from inspector.services import storage_paths
from inspector.services.hf_bucket import get_backend
from scripts.inspector_v2_seed.seed_state import CUTOVER_CANONICAL_MAP

PER_RECITER_FILES = (
    "segments.json",
    "detailed.json",
    "edit_history.jsonl",
    "edit_history_peaks.jsonl",
    "low_confidence_v2.json",
)


def _collect_files(root: Path) -> list[tuple[str, str]]:
    """Build the [(local_abs_path, bucket_path), ...] upload manifest.

    The bucket key is the canonical delivery slug (post-dedup). For each
    state row we read from the freshly-hydrated state file (which itself
    was seeded with canonical slugs by ``seed_state.py``), then resolve the
    on-disk source dir via the inverse of ``CUTOVER_CANONICAL_MAP``.
    """
    state_service.hydrate()
    rows = state_service.snapshot().reciters

    # Reverse the canonical map so we can find the on-disk v1 dir for each
    # canonical slug in the state file.
    canonical_to_v1 = {v: k for k, v in CUTOVER_CANONICAL_MAP.items()}

    repo_data = root / "data"
    pairs: list[tuple[str, str]] = []
    for row in rows:
        canonical_slug = row.slug
        v1_dir_name = canonical_to_v1.get(canonical_slug, canonical_slug)
        kind = (
            "published" if row.state == ReciterState.COMPLETED else "wip"
        )
        src_dir = repo_data / "recitation_segments" / v1_dir_name
        if not src_dir.is_dir():
            print(f"skip {canonical_slug}: {src_dir} missing")
            continue
        for name in PER_RECITER_FILES:
            sp = src_dir / name
            if sp.exists():
                pairs.append(
                    (str(sp.resolve()),
                     storage_paths.reciter_file(canonical_slug, kind, name))
                )
    return pairs


def main() -> int:
    root = repo_root()
    pairs = _collect_files(root)
    if not pairs:
        print("FAIL: nothing to upload", file=sys.stderr)
        return 1

    bucket_id = get_backend()  # ensures backend instantiated → login() done
    # We need the bucket_id string, not the backend object. Read from env.
    import os

    bucket = os.environ.get(
        "INSPECTOR_BUCKET_REPO", "hetchyy/quranic-inspector-bucket-dev"
    )

    print(f"uploading {len(pairs)} files to bucket {bucket} ...")
    # Chunk into batches of 200 to keep request size reasonable.
    chunk = 200
    for i in range(0, len(pairs), chunk):
        slice_ = pairs[i : i + chunk]
        batch_bucket_files(bucket, add=slice_)
        print(f"  uploaded {min(i + chunk, len(pairs))}/{len(pairs)}")

    print("ok  cutover data seed complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
