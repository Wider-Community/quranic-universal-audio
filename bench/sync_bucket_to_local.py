"""Mirror the dev-bucket files needed by `validate_reciter_segments` into a
local directory so we can re-run the bench against a `FilesystemBackend`
(simulates an NFS-mounted bucket on a deployed HF Space).

Files synced:
- state/reciter_state.json                (required by data_dir.kind_for)
- wip/<slug>/detailed.json                (required by validate)
- wip/<slug>/segments.json                (required by _check_structural_errors)
- wip/<slug>/edit_history.jsonl           (required by build_resolved_by_edit_index)
- wip/<slug>/low_confidence_v2.json       (optional — skipped silently if absent)

Output root defaults to `.local/worktrees/validate-opt/bench/fs_mirror/`. Set
INSPECTOR_BACKEND=filesystem + INSPECTOR_FILESYSTEM_ROOT=<that path> before
running the bench to use the local copies.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INSPECTOR = _REPO_ROOT / "inspector"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_INSPECTOR) not in sys.path:
    sys.path.insert(0, str(_INSPECTOR))

from services import data_dir  # noqa: E402
from services.hf_bucket import StorageNotFound, get_backend  # noqa: E402

DEST = _REPO_ROOT / "bench" / "fs_mirror"


def _sync_bytes(backend, src_path: str, dest_path: Path) -> int:
    """Read bytes from the bucket backend and write to local. Returns byte count."""
    raw = backend.read_bytes(src_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(raw)
    return len(raw)


def main() -> int:
    backend = get_backend()
    DEST.mkdir(parents=True, exist_ok=True)

    print(f"Mirroring bucket → {DEST}")
    print()

    # 1. State (needed for kind_for(slug)).
    state_path = "state/reciter_state.json"
    n = _sync_bytes(backend, state_path, DEST / state_path)
    print(f"  state/reciter_state.json  ({n / 1024:.1f} KB)")

    # 2. Per-slug content for every WIP reciter.
    wip_slugs = sorted(data_dir.list_slugs("wip"))
    for slug in wip_slugs:
        print(f"  wip/{slug}/")
        for fname in ("detailed.json", "segments.json", "edit_history.jsonl"):
            src = f"wip/{slug}/{fname}"
            try:
                n = _sync_bytes(backend, src, DEST / src)
                print(f"      {fname:<28} {n / 1024:>10.1f} KB")
            except StorageNotFound:
                print(f"      {fname:<28} (absent)")
        src = f"wip/{slug}/low_confidence_v2.json"
        try:
            n = _sync_bytes(backend, src, DEST / src)
            print(f"      low_confidence_v2.json       {n / 1024:>10.1f} KB")
        except StorageNotFound:
            # Sidecar is often absent — caching code already handles that.
            pass

    print()
    print(f"Done. Set env to use the mirror:")
    print(f"  export INSPECTOR_BACKEND=filesystem")
    print(f"  export INSPECTOR_FILESYSTEM_ROOT={DEST}")
    return 0


if __name__ == "__main__":
    t0 = time.perf_counter()
    rc = main()
    print(f"Total wall: {time.perf_counter() - t0:.1f} s")
    raise SystemExit(rc)
