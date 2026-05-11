"""Seed ``<bucket>/state/reciter_state.json`` from filesystem signals.

For each directory under ``data/recitation_segments/<slug>/``:

- If both ``segments.json`` and the timestamps file under
  ``data/timestamps/{by_ayah_audio,by_surah_audio}/<slug>/timestamps.json``
  are present → state ``"completed"``.
- Otherwise (segments only) → state ``"awaiting_review"``.

Reuses ``scripts.lib.reciter_eligibility.is_eligible`` as the gate so
"completed" matches the existing ✓ marker logic used by RECITERS.md /
list_reciters.py.

Overwrites ``<bucket>/state/reciter_state.json`` in-place. Any in-progress
claims will be cleared — re-claim happens through the Inspector UI after
cutover.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from ._env import load_repo_env, repo_root

load_repo_env()

from scripts.lib.reciter_eligibility import (
    find_eligible_reciters,
    has_tracked_timestamps,
)
from scripts.lib.schemas import ReciterRow, ReciterState, ReciterStateFile
from inspector.services import storage_paths
from inspector.services.hf_bucket import get_backend


def main() -> int:
    root = repo_root()
    segs_dir = root / "data" / "recitation_segments"
    if not segs_dir.is_dir():
        print(f"FAIL: {segs_dir} not found", file=sys.stderr)
        return 1

    eligible = set(find_eligible_reciters(repo_root=root))
    now = datetime.now(timezone.utc)
    rows: list[ReciterRow] = []
    for child in sorted(segs_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        slug = child.name
        if not (child / "segments.json").exists():
            print(f"skip {slug}: no segments.json")
            continue
        if slug in eligible:
            state = ReciterState.COMPLETED
        else:
            state = ReciterState.AWAITING_REVIEW
        rows.append(ReciterRow(slug=slug, state=state, state_since=now))
        tracked_ts = "ts" if has_tracked_timestamps(slug, root) else "  "
        print(f"  {slug:40s} [{tracked_ts}] -> {state.value}")

    state_file = ReciterStateFile(reciters=rows)
    backend = get_backend()
    backend.write_json_atomic(
        storage_paths.state_path(),
        state_file.model_dump(mode="json"),
    )
    print(
        f"ok  uploaded {len(rows)} rows to {storage_paths.state_path()} "
        f"(completed={sum(1 for r in rows if r.state == ReciterState.COMPLETED)}, "
        f"awaiting_review={sum(1 for r in rows if r.state == ReciterState.AWAITING_REVIEW)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
