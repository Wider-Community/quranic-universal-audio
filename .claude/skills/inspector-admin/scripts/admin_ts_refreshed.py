"""Record out-of-band TS shard refreshes (``reciter.ts_refreshed``) for reciters.

Same write as ``POST /api/admin/internal/ts-refreshed`` — wraps
``services/db/repo_releases.mark_ts_refreshed`` — for a backfill / local regen
that uploaded shards straight to the bucket, bypassing the HF-job webhook. Per
slug it advances the current ``ts`` release ``produced_at`` (clears computed
staleness), stamps HF + most-recent-GH dataset membership stale (``TS_REGEN``),
and audits ``reciter.ts_refreshed``. A slug with no current ``ts`` release acks
``refreshed=False`` (nothing to advance). All slugs run in one durable txn.

  admin_ts_refreshed.py SLUG [SLUG ...] --reason whole_verse_psil_backfill --prod --yes-prod
  admin_ts_refreshed.py nasser_al_qatami_mp3quran --dry-run --prod
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("slugs", nargs="+", help="reciter slugs to mark refreshed")
    p.add_argument("--reason", default="manual", help="provenance tag stored in the audit row")
    p.add_argument("--chapters", help="comma-sep surah ints (audit-only); applied to every slug")
    bs.add_common_args(p)
    a = p.parse_args()

    def _run(ctx) -> int:
        from services.db import repo_releases
        from services.db.sync import durable_transaction

        chapters = [int(x) for x in a.chapters.split(",")] if a.chapters else None
        at = datetime.now(UTC)

        if a.dry_run:
            print(f"DRY RUN — would mark_ts_refreshed for {len(a.slugs)} slug(s) "
                  f"reason={a.reason!r} chapters={chapters}")
            for s in a.slugs:
                print(f"  {s}")
            return 0

        results: dict[str, bool] = {}
        with durable_transaction():
            for s in a.slugs:
                results[s] = repo_releases.mark_ts_refreshed(
                    s, at=at, chapters=chapters, reason=a.reason)

        for s in a.slugs:
            print(f"  {s:42} refreshed={results[s]}")
        n = sum(1 for v in results.values() if v)
        print(f"== marked {n}/{len(a.slugs)} (False = no current ts release) ==")
        bs.after_write_banner(a)
        return 0

    # mark_ts_refreshed is an in-process bucket-DB write → prod_safe_setup window.
    return bs.run(a, _run, need_actor=False, mutates=True, safe_write=True)


if __name__ == "__main__":
    raise SystemExit(main())
