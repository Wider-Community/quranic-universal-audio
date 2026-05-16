"""One-off: archive pending entries whose state row has already moved past
AWAITING_ALIGNMENT.

Before this change the codebase had a boot-time ``reconcile_with_state``
that *deleted* orphans — that threw away the requester's structured
proposed_edits + comments + auto_claim. The new design archives at each
terminal transition (alignment_completed / soft-reject / hard-reject) so
no new orphans should appear, but legacy data on the bucket already
contains some.

This script catches up that legacy data by writing every orphan into
``requests/completed.json`` with a synthetic system actor and
``reason="migrated from orphan"`` (so the audit trail records why the
archive entry didn't come through the normal handler path).

Dry-run by default. Pass --apply to actually mutate the bucket.
Idempotent — a second run with the same starting state archives zero
entries (the first run cleared them).

Usage:
    python3 inspector/scripts/migrate_pending_orphans.py            # dry-run
    python3 inspector/scripts/migrate_pending_orphans.py --apply    # commit

Requires ``HF_TOKEN`` in the environment (or .env) for bucket writes.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# parents[1] = inspector/  (for `services`, `config`); parents[2] = repo root
# (for `scripts.lib.schemas`). Same dual-path setup pytest uses.
_INSPECTOR_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_INSPECTOR_DIR))
sys.path.insert(0, str(_REPO_ROOT))

from scripts.lib.schemas import Actor, ArchivedRequest, ReciterState, Role  # noqa: E402

from services import pending_requests as pending_requests_service  # noqa: E402
from services import request_archive as request_archive_service  # noqa: E402
from services import state as state_service  # noqa: E402


SYSTEM_ACTOR = Actor(
    hf_user_id="system",
    login_at_time="system",
    role=Role.OWNER,
)


def _hydrate_all() -> None:
    state_service.hydrate()
    pending_requests_service.hydrate()
    request_archive_service.hydrate()


def find_orphans() -> list[tuple[str, ReciterState | None]]:
    """Walk the pending store and return ``(slug, current_state)`` for every
    entry whose state row is not AWAITING_ALIGNMENT (or missing)."""
    snap = pending_requests_service.snapshot()
    orphans: list[tuple[str, ReciterState | None]] = []
    for slug in snap.by_slug:
        row = state_service.get_row(slug)
        current = row.state if row is not None else None
        if current == ReciterState.AWAITING_ALIGNMENT:
            continue
        orphans.append((slug, current))
    return orphans


def archive_orphan(slug: str) -> None:
    """Build an ArchivedRequest from the pending entry and append to
    completed.json; then clear from pending. Mirrors what
    pending_requests._archive does, but with a fixed migration reason
    and the synthetic system actor (so the archive entry is auditably
    distinct from organic alignment_completed transitions, which set
    reason=None)."""
    pending = pending_requests_service.get(slug)
    if pending is None:
        return
    entry = ArchivedRequest(
        slug=pending.slug,
        submitted_at=pending.submitted_at,
        requester=pending.requester,
        proposed_edits=pending.proposed_edits,
        comments=pending.comments,
        auto_claim=pending.auto_claim,
        archived_at=datetime.now(timezone.utc),
        transitioned_by=SYSTEM_ACTOR,
        reason="migrated from orphan",
    )
    request_archive_service.append(
        request_archive_service.ArchiveKind.COMPLETED, entry,
    )
    pending_requests_service.clear(slug)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit changes to the bucket. Without this, runs as a dry-run.",
    )
    args = parser.parse_args(argv)

    _hydrate_all()
    orphans = find_orphans()

    print(f"Found {len(orphans)} orphan pending entry/entries:")
    for slug, current in orphans:
        state_label = current.value if current is not None else "<no row>"
        print(f"  - {slug}  (state={state_label})")

    if not orphans:
        print("Nothing to migrate.")
        return 0

    if not args.apply:
        print("\nDry-run — re-run with --apply to commit.")
        return 0

    print(f"\nArchiving {len(orphans)} entries to requests/completed.json …")
    for slug, _ in orphans:
        archive_orphan(slug)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
