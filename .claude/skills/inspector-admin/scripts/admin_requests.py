"""Request queue ops — list / show / resolve / accept / probe.

  admin_requests.py list                                     # default: pending
  admin_requests.py list --status accepted
  admin_requests.py show REQUEST_ID
  admin_requests.py resolve REQUEST_ID --status archived --reason "stale"
  admin_requests.py accept REQUEST_ID [--reciter-id ID]      # intake-only
  admin_requests.py probe REQUEST_ID                         # intake reachability

The "request" rows cover intake (slugless), edit, and admin-action kinds.
Open docs/reference/admin-dashboard.md for the Requests compartment shape.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def _list(a, ctx) -> int:
    from services.admin import requests as admin_requests  # noqa: E402
    data = admin_requests.list_requests(
        status=a.status, caller_is_owner=True,
        caller_hf_id=ctx.actor.hf_user_id if ctx.actor else "")
    rows = data.get("requests") if isinstance(data, dict) else data
    if not rows:
        print("(no requests)"); return 0
    for r in rows or []:
        m = r if isinstance(r, dict) else r.model_dump()
        print(f"  {m.get('request_id',''):<40s} {m.get('kind',''):<10s} "
              f"{m.get('status',''):<10s} "
              f"slug={m.get('slug') or m.get('proposed_slug') or '—'}")
    return 0


def _show(a, ctx) -> int:
    # services.admin.requests doesn't surface a per-id detail directly; pull from
    # repo_requests instead — same shape the route uses.
    from services.db import repo_requests  # noqa: E402
    import json as _json
    row = repo_requests.get(a.request_id) if hasattr(repo_requests, "get") \
        else None
    if row is None:
        print(f"unknown request_id {a.request_id}", file=sys.stderr); return 4
    print(_json.dumps(row if isinstance(row, dict) else row.model_dump(),
                      indent=2, default=str, ensure_ascii=False))
    return 0


def _resolve(a, ctx) -> int:
    from services.admin import intake  # noqa: E402
    if a.dry_run:
        print(f"DRY RUN — would resolve {a.request_id} status={a.status}")
        return 0
    intake.resolve(a.request_id, status=a.status, reason=a.reason or "",
                   actor=ctx.actor)
    print(f"resolved {a.request_id} → {a.status}")
    bs.after_write_banner(a)
    return 0


def _accept(a, ctx) -> int:
    from services.admin import intake  # noqa: E402
    if a.dry_run:
        print(f"DRY RUN — would accept {a.request_id}"); return 0
    slug = intake.accept(a.request_id, actor=ctx.actor, reciter_id=a.reciter_id)
    print(f"accepted; reciter_id={slug}")
    bs.after_write_banner(a)
    return 0


def _probe(a, ctx) -> int:
    from services.admin import intake  # noqa: E402
    res = intake.probe(a.request_id)
    print(res.model_dump() if hasattr(res, "model_dump") else res)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list"); pl.add_argument("--status", default="pending")
    bs.add_common_args(pl, mutating=False)
    psh = sub.add_parser("show"); psh.add_argument("request_id")
    bs.add_common_args(psh, mutating=False)
    pr = sub.add_parser("resolve"); pr.add_argument("request_id")
    pr.add_argument("--status", choices=("accepted", "rejected", "archived"),
                    default="archived")
    pr.add_argument("--reason"); bs.add_common_args(pr)
    pa = sub.add_parser("accept"); pa.add_argument("request_id")
    pa.add_argument("--reciter-id", help="custom reciter id (intake mint flow)")
    bs.add_common_args(pa)
    pp = sub.add_parser("probe"); pp.add_argument("request_id")
    bs.add_common_args(pp, mutating=False)

    a = p.parse_args()
    write = a.cmd in ("resolve", "accept")
    return bs.run(
        a,
        lambda ctx: {"list": _list, "show": _show, "resolve": _resolve,
                     "accept": _accept, "probe": _probe}[a.cmd](a, ctx),
        need_actor=write, mutates=write, safe_write=write,
    )


if __name__ == "__main__":
    raise SystemExit(main())
