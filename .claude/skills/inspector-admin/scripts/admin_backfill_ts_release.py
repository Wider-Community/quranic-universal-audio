"""Backfill a ``per_recitation_releases(track='ts')`` row for reciters that were
published offline (katana extraction → bucket upload + catalog import) and so
never went through the in-app TS-job completion path that normally writes it.

Root cause this repairs: the ts release row is created ONLY by
``services/admin/timestamps_jobs.py`` (job-completion / regen-on-released). A
reciter whose shards landed via offline upload has bucket timestamps + a catalog
``deliveries`` row but no ts release row, so it is invisible to staleness /
GH-cut eligibility / ts-refresh.

Per slug (idempotent, in one durable txn, prod via the single-writer window):
  1. refuse if the slug is not in ``deliveries`` (uncatalogued → not published).
  2. if it already has a current ts row, skip the insert.
  3. else insert one with ``produced_at`` = publish-time
     (``per_recitation_releases(hf).produced_at`` ?? ``deliveries.added_at``),
     ``version='offline-backfill'``, ``produced_by='SYSTEM_ACTOR'``.
  4. with --refresh, also ``mark_ts_refreshed`` (advance produced_at to now,
     stamp HF/GH stale, audit ``reciter.ts_refreshed``) — for when the shards
     were just re-stamped.

  admin_backfill_ts_release.py SLUG [SLUG ...] --refresh --reason whole_verse_psil_backfill --prod --yes-prod
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def _publish_time(conn, slug: str) -> str | None:
    """Best publish-time for a backfilled ts row: the current hf release's
    produced_at, else the catalog ``deliveries.added_at``."""
    row = conn.execute(
        "SELECT produced_at FROM per_recitation_releases "
        "WHERE track='hf' AND slug=? AND superseded_at IS NULL", (slug,)).fetchone()
    if row and row["produced_at"]:
        return row["produced_at"]
    row = conn.execute("SELECT added_at FROM deliveries WHERE slug=?", (slug,)).fetchone()
    return row["added_at"] if row and row["added_at"] else None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("slugs", nargs="+")
    p.add_argument("--refresh", action="store_true",
                   help="also mark_ts_refreshed after inserting (advance to now + stamp stale)")
    p.add_argument("--reason", default="offline-backfill")
    bs.add_common_args(p)
    a = p.parse_args()

    def _run(ctx) -> int:
        from services.db import _serde, repo_releases
        from services.db.connection import get_conn
        from services.db.sync import durable_transaction

        conn = get_conn()
        plan = []
        for s in a.slugs:
            in_cat = conn.execute("SELECT 1 FROM deliveries WHERE slug=?", (s,)).fetchone()
            if not in_cat:
                print(f"  {s:42} SKIP — not in catalog (deliveries)")
                continue
            existing = repo_releases.current_release("ts", s)
            pub = _publish_time(conn, s)
            plan.append((s, pub, bool(existing)))

        if a.dry_run:
            print(f"DRY RUN — {len(plan)} catalogued slug(s), refresh={a.refresh}:")
            for s, pub, has in plan:
                act = "refresh-only" if has else f"insert@{(pub or '?')[:10]} +backfill"
                print(f"  {s:42} pub={pub or '-'!s:25} {act}")
            return 0

        now = datetime.now(UTC)
        inserted = refreshed = 0
        with durable_transaction():
            for s, pub, has in plan:
                if not has:
                    if not pub:
                        print(f"  {s:42} SKIP — no publish-time (no hf row / added_at)")
                        continue
                    at = _serde.from_iso(pub)
                    repo_releases.supersede_current("ts", s, except_id=-1, at=now)
                    repo_releases.insert_per_recitation_release(
                        track="ts", slug=s, version="offline-backfill",
                        produced_at=at, produced_by="SYSTEM_ACTOR")
                    inserted += 1
                if a.refresh:
                    if repo_releases.mark_ts_refreshed(s, at=now, reason=a.reason):
                        refreshed += 1
                print(f"  {s:42} {'had-ts' if has else 'inserted@'+pub[:10]}"
                      f"{' +refreshed' if a.refresh else ''}")

        print(f"== inserted {inserted} ts row(s), refreshed {refreshed} ==")
        bs.after_write_banner(a)
        return 0

    return bs.run(a, _run, need_actor=False, mutates=True, safe_write=True)


if __name__ == "__main__":
    raise SystemExit(main())
