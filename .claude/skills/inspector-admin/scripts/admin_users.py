"""User management — list / show / set-role.

  admin_users.py list                                   # everyone with a role
  admin_users.py show --hf-id 684abe5b6327ae8863d106d2
  admin_users.py set-role --hf-id ID --login LOGIN --role {owner,maintainer,contributor}

set-role wraps services.admin.users.set_role; demoting the last owner
raises LastOwnerError. See docs/reference/auth-permissions.md for the
role tier semantics.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def _list(a, ctx) -> int:
    from services.admin import users  # noqa: E402
    data = users.list_users()
    rows = data.get("users") if isinstance(data, dict) else data
    print(f"{'hf_user_id':<26s} {'login':<22s} {'role':<12s} {'active':>6s}")
    for r in rows or []:
        m = r if isinstance(r, dict) else r.model_dump()
        print(f"{m.get('hf_user_id',''):<26s} {m.get('login',''):<22s} "
              f"{m.get('role',''):<12s} {str(m.get('active','')):>6s}")
    return 0


def _show(a, ctx) -> int:
    from services.admin import users  # noqa: E402
    detail = users.get_user_detail(a.hf_id)
    if detail is None:
        print(f"unknown hf_user_id {a.hf_id}", file=sys.stderr); return 4
    import json as _json
    print(_json.dumps(detail, indent=2, default=str, ensure_ascii=False))
    return 0


def _set_role(a, ctx) -> int:
    from scripts.lib.schemas.access import Role  # noqa: E402
    from services.admin import users  # noqa: E402
    target = Role(a.role)
    if a.dry_run:
        print(f"DRY RUN — would set {a.hf_id} → {target.value}"); return 0
    res = users.set_role(hf_user_id=a.hf_id, target_role=target,
                         actor=ctx.actor, login=a.login)
    print(f"result: {res}")
    bs.after_write_banner(a)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list"); bs.add_common_args(pl, mutating=False)
    psh = sub.add_parser("show"); psh.add_argument("--hf-id", required=True)
    bs.add_common_args(psh, mutating=False)
    psr = sub.add_parser("set-role"); psr.add_argument("--hf-id", required=True)
    psr.add_argument("--login", help="HF login (recommended; cached on grant)")
    psr.add_argument("--role", required=True,
                     choices=("owner", "maintainer", "contributor"))
    bs.add_common_args(psr)
    a = p.parse_args()
    ctx = bs.setup(a, need_actor=a.cmd == "set-role")
    return {"list": _list, "show": _show, "set-role": _set_role}[a.cmd](a, ctx)


if __name__ == "__main__":
    raise SystemExit(main())
