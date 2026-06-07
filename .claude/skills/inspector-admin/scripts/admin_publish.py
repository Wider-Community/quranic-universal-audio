"""Publish a finished TS job's reciter — calls complete_timestamps_job.

The exact path the webhook OR poll-fallback would take. Use when the
deployed Space missed the webhook and we don't want to wait for someone to
open the drawer in the UI.

  admin_publish.py SLUG --job-id JOB_ID --prod --yes-prod
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("slug")
    p.add_argument("--job-id", required=True)
    bs.add_common_args(p)
    a = p.parse_args()

    def _run(ctx) -> int:
        from services.admin import timestamps_jobs  # noqa: E402
        from services.state import state as state_service  # noqa: E402

        row = state_service.get_row(a.slug)
        if row is None:
            print(f"unknown slug {a.slug}", file=sys.stderr)
            return 4
        print(f"BEFORE: state={row.state.value}  marked_ready={row.marked_ready}")

        if a.dry_run:
            print(f"DRY RUN — would call complete_timestamps_job({a.slug!r}, "
                  f"{a.job_id!r})")
            return 0

        result = timestamps_jobs.complete_timestamps_job(a.slug, a.job_id)
        print(f"result: {result}")

        row = state_service.get_row(a.slug)
        print(f"AFTER:  state={row.state.value}  marked_ready={row.marked_ready}")
        bs.after_write_banner(a)
        return 0

    # complete_timestamps_job always does an in-process bucket-DB write.
    return bs.run(a, _run, need_actor=True, mutates=True, safe_write=True)


if __name__ == "__main__":
    raise SystemExit(main())
