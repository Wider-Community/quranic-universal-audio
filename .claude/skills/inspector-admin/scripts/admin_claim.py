"""Claim ops — show, force-release, reassign.

  admin_claim.py show SLUG
  admin_claim.py release SLUG --reason "abandoned by reviewer"
  admin_claim.py reassign SLUG --to LOGIN --reason "swap reviewer"

`release` and `reassign` route through state.transition (events
`claim.force_released` / `claim.reassigned`). Reassign looks up the new
assignee's hf_user_id via the HF user API.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def _show(a, ctx) -> int:
    from services.state import state as state_service  # noqa: E402
    row = state_service.get_row(a.slug)
    if row is None:
        print(f"unknown slug {a.slug}", file=sys.stderr); return 4
    print(f"slug: {row.slug}")
    print(f"state: {row.state.value}  marked_ready: {row.marked_ready}")
    assignee = getattr(row, "assignee_hf_id", None)
    print(f"assignee_hf_id: {assignee or '—'}")
    print(f"assignee_login: {getattr(row, 'assignee_login', None) or '—'}")
    return 0


def _release(a, ctx) -> int:
    from services.state import state as state_service  # noqa: E402
    if a.dry_run:
        print(f"DRY RUN — would transition({a.slug!r}, 'claim.force_released')")
        return 0
    row = state_service.transition(
        a.slug, "claim.force_released", actor=ctx.actor, reason=a.reason)
    print(f"state={row.state.value}  marked_ready={row.marked_ready}")
    bs.after_write_banner(a)
    return 0


def _reassign(a, ctx) -> int:
    from huggingface_hub import HfApi  # noqa: E402
    from services.state import state as state_service  # noqa: E402

    info = HfApi().whoami() if not a.to else None
    target = HfApi().get_user_overview(a.to) if a.to else None
    if a.to and target is None:
        print(f"cannot resolve HF login {a.to}", file=sys.stderr); return 4
    new_id = getattr(target, "id", None) or getattr(target, "user_id", None)
    if not new_id:
        # Older HF SDK shape — fall back to a search.
        try:
            new_id = HfApi().get_user(a.to).id
        except Exception:
            pass
    if not new_id:
        print(f"could not resolve hf_user_id for {a.to}", file=sys.stderr); return 4
    payload = {"new_assignee_hf_id": new_id, "new_assignee_login": a.to}
    if a.dry_run:
        print(f"DRY RUN — payload={payload}"); return 0
    row = state_service.transition(
        a.slug, "claim.reassigned", actor=ctx.actor,
        payload=payload, reason=a.reason)
    print(f"reassigned to {a.to} ({new_id})  state={row.state.value}")
    bs.after_write_banner(a)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    psh = sub.add_parser("show"); psh.add_argument("slug")
    bs.add_common_args(psh, mutating=False)
    prl = sub.add_parser("release"); prl.add_argument("slug")
    prl.add_argument("--reason"); bs.add_common_args(prl)
    pra = sub.add_parser("reassign"); pra.add_argument("slug")
    pra.add_argument("--to", required=True); pra.add_argument("--reason")
    bs.add_common_args(pra)
    a = p.parse_args()
    ctx = bs.setup(a, need_actor=a.cmd != "show")
    return {"show": _show, "release": _release, "reassign": _reassign}[a.cmd](a, ctx)


if __name__ == "__main__":
    raise SystemExit(main())
