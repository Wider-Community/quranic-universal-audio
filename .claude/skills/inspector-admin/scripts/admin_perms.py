"""Capability override management (owner-only).

  admin_perms.py matrix                                          # full grid
  admin_perms.py matrix --grep reciter.unlock
  admin_perms.py set --cap reciter.unlock_for_revision --tier maintainer --allowed 1
  admin_perms.py reset --cap reciter.unlock_for_revision --tier maintainer

Open docs/reference/capabilities.md for the capability registry + tier
semantics + the resolver.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def _matrix(a, ctx) -> int:
    from services.admin import permissions  # noqa: E402
    resp = permissions.build_matrix()
    data = resp.model_dump() if hasattr(resp, "model_dump") else resp
    groups = data.get("groups", [])
    needle = (a.grep or "").lower()
    for g in groups:
        for cap in g.get("capabilities", []):
            cid = cap.get("id", "")
            if needle and needle not in cid.lower():
                continue
            tiers = " ".join(
                f"{t.get('tier','')}={'1' if t.get('effective') else '0'}"
                f"{'*' if t.get('overridden') else ''}"
                for t in cap.get("tiers", []))
            print(f"  {cid:<40s}  {tiers}")
    print("(* = override; without * = registry default)")
    return 0


def _set(a, ctx) -> int:
    from services.admin import permissions  # noqa: E402
    allowed = bool(int(a.allowed))
    if a.dry_run:
        print(f"DRY RUN — would set {a.cap} @ {a.tier} → {allowed}")
        return 0
    changed = permissions.set_grant(
        capability_id=a.cap, tier=a.tier, allowed=allowed, actor=ctx.actor)
    print(f"changed={changed}  {a.cap} @ {a.tier} = {allowed}")
    bs.after_write_banner(a)
    return 0


def _reset(a, ctx) -> int:
    from services.admin import permissions  # noqa: E402
    if a.dry_run:
        print(f"DRY RUN — would reset {a.cap} @ {a.tier}"); return 0
    changed = permissions.reset_grant(
        capability_id=a.cap, tier=a.tier, actor=ctx.actor)
    print(f"changed={changed}  override cleared")
    bs.after_write_banner(a)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pm = sub.add_parser("matrix"); pm.add_argument("--grep")
    bs.add_common_args(pm, mutating=False)
    ps = sub.add_parser("set"); ps.add_argument("--cap", required=True)
    ps.add_argument("--tier", required=True,
                    choices=("contributor", "maintainer", "owner"))
    ps.add_argument("--allowed", required=True, choices=("0", "1"))
    bs.add_common_args(ps)
    pr = sub.add_parser("reset"); pr.add_argument("--cap", required=True)
    pr.add_argument("--tier", required=True,
                    choices=("contributor", "maintainer", "owner"))
    bs.add_common_args(pr)

    a = p.parse_args()
    ctx = bs.setup(a, need_actor=a.cmd != "matrix")
    return {"matrix": _matrix, "set": _set, "reset": _reset}[a.cmd](a, ctx)


if __name__ == "__main__":
    raise SystemExit(main())
