"""Generic state.transition wrapper.

  admin_state.py SLUG --event reciter.unpublished --reason "bad alignment"
  admin_state.py SLUG --event admin.unlocked_for_revision --prod --yes-prod
  admin_state.py SLUG --event claim.reassigned --payload '{"new_assignee_hf_id":"X","new_assignee_login":"Y"}'

For the valid event names per state + the payload shape per event, open
docs/reference/state-machine.md. This script does NOT validate either —
it forwards straight to services/state/state.transition, which raises on
an unknown event or bad payload.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("slug")
    p.add_argument("--event", required=True,
                   help="state-machine event name (see state-machine.md)")
    p.add_argument("--reason", help="audit reason; may be required for some events")
    p.add_argument("--payload", help="JSON object; shape depends on event")
    bs.add_common_args(p)
    a = p.parse_args()

    ctx = bs.setup(a)
    from services.state import state as state_service  # noqa: E402

    row = state_service.get_row(a.slug)
    if row is None:
        print(f"unknown slug {a.slug}", file=sys.stderr)
        return 4
    print(f"BEFORE: state={row.state.value}  marked_ready={row.marked_ready}")

    payload = json.loads(a.payload) if a.payload else None
    if a.dry_run:
        print(f"DRY RUN — would call transition(slug={a.slug!r}, event={a.event!r}, "
              f"reason={a.reason!r}, payload={payload!r})")
        return 0

    new_row = state_service.transition(
        a.slug, a.event, actor=ctx.actor, payload=payload, reason=a.reason)
    print(f"AFTER:  state={new_row.state.value}  marked_ready={new_row.marked_ready}")
    bs.after_write_banner(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
