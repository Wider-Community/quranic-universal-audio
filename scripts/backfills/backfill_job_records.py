"""Backfill uniform JobRecords for pre-store release/cut/batch history.

The unified job-record store (``services/admin/jobs/records.py``) is written
going forward by every kind. Records that ran BEFORE the store existed only
live in the DB (``gh_releases`` cut_release, ``per_recitation_releases(track='hf')``
hf_publish) or as job-written batch artifacts. This one-shot synthesizes a
``JobRecord`` for each so the admin **Jobs** tab reads complete history from the
one store.

Idempotent — skips any job_id that already has a record. TS already writes
records (job + server), so it's untouched here. Batch records are job-written
already; this only normalizes them if a server-side record is absent.

Run (dev bucket by default — set INSPECTOR_BUCKET_REPO for another)::

    python scripts/backfills/backfill_job_records.py            # write
    python scripts/backfills/backfill_job_records.py --dry-run  # report only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "inspector"))


def _boot() -> None:
    from services.db import init_db
    from services.db import sync as _sync

    _sync.pull()
    init_db()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--dry-run", action="store_true", help="report what would be written")
    a = p.parse_args()

    _boot()

    from qua_shared.schemas import JobMember, JobRecord
    from services.admin.jobs import base, records
    from services.db import repo_releases
    from services.state import state as state_service

    written = 0
    skipped = 0

    def _exists(kind: str, slug: str | None, job_id: str) -> bool:
        return records.read(kind, slug, job_id) is not None

    # --- cut_release (gh_releases) ---
    for r in repo_releases.all_gh_releases():
        job_id = (r.get("produced_by_job_id") or "").strip()
        if not job_id:
            continue
        if _exists("cut_release", None, job_id):
            skipped += 1
            continue
        members = [
            JobMember(
                slug=m.get("slug"),
                status="succeeded",
                version=m.get("ts_version"),
                change_kind=m.get("change_kind"),
            )
            for m in repo_releases.gh_release_recitations(r["id"])
            if m.get("slug")
        ]
        rec = JobRecord(
            job_id=job_id,
            kind="cut_release",
            slug=None,
            status="succeeded",
            started_at=r.get("produced_at"),
            ended_at=r.get("produced_at"),
            url=base.hf_job_url(job_id),
            launched_by=r.get("launched_by"),
            version=r.get("version"),
            external_uri=r.get("external_uri"),
            members=members,
            member_count=len(members),
        )
        print(f"cut_release {r.get('version')} ({job_id}) — {len(members)} members")
        if not a.dry_run:
            records.put(rec)
        written += 1

    # --- hf_publish (per_recitation_releases track='hf', per slug) ---
    for row in state_service.all_rows():
        slug = row.slug
        for rel in repo_releases.all_releases_for_track_slug("hf", slug):
            job_id = (rel.get("produced_by_job_id") or "").strip()
            if not job_id:
                continue
            if _exists("hf_publish", slug, job_id):
                skipped += 1
                continue
            rec = JobRecord(
                job_id=job_id,
                kind="hf_publish",
                slug=slug,
                status="succeeded",
                started_at=rel.get("produced_at"),
                ended_at=rel.get("produced_at"),
                url=base.hf_job_url(job_id),
                launched_by=rel.get("launched_by"),
                version=rel.get("version"),
                external_uri=rel.get("external_uri"),
            )
            print(f"hf_publish {slug} {rel.get('version')} ({job_id})")
            if not a.dry_run:
                records.put(rec)
            written += 1

    print(
        f"\n{'DRY RUN — ' if a.dry_run else ''}wrote {written}, skipped {skipped} (already present)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
