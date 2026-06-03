"""Raw SQL against the pulled inspector.db. Read-only by default.

  admin_db.py exec "select slug, state from delivery_states limit 20"
  admin_db.py exec "select hf_user_id, role from access" --prod
  admin_db.py exec "update <…>" --write --yes-prod --prod    # mutating + sync back
  admin_db.py tables                                          # list known tables

Mutating SQL bypasses state.transition / repo_* abstractions — no audit row
is appended. Only use when nothing else fits AND you accept the audit gap.
For lifecycle changes prefer admin_state.py.

Open docs/reference/database.md for the schema map.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def _exec(a, ctx) -> int:
    from services import db as _db  # noqa: E402
    from services.db import sync as _db_sync  # noqa: E402

    if a.write:
        if a.dry_run:
            print("DRY RUN — would execute and sync back"); print(a.sql); return 0
        with _db_sync.durable_transaction() as conn:
            cur = conn.execute(a.sql)
            print(f"rowcount: {cur.rowcount}")
        bs.after_write_banner(a)
        return 0

    conn = _db.get_conn()
    cur = conn.execute(a.sql)
    cols = [d[0] for d in (cur.description or [])]
    rows = cur.fetchmany(a.rows)
    if not cols:
        print("(no result columns — was this a write? add --write)")
        return 0
    print(" | ".join(cols))
    print("-" * (sum(len(c) for c in cols) + 3 * (len(cols) - 1)))
    for row in rows:
        print(" | ".join("" if v is None else str(v) for v in row))
    extra = cur.fetchone()
    if extra:
        print(f"... ({a.rows}+ rows; raise --rows or LIMIT in SQL)")
    return 0


def _tables(a, ctx) -> int:
    from services import db as _db  # noqa: E402
    conn = _db.get_conn()
    rows = conn.execute("select name from sqlite_master where type='table' order by name").fetchall()
    for r in rows:
        print(r[0])
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("exec"); pe.add_argument("sql")
    pe.add_argument("--write", action="store_true",
                    help="open writer + commit + sync back to bucket")
    pe.add_argument("--rows", type=int, default=200,
                    help="max rows to print for SELECT (default: 200)")
    bs.add_common_args(pe)
    pt = sub.add_parser("tables"); bs.add_common_args(pt, mutating=False)

    a = p.parse_args()
    # Read-only exec needs DB but not actor; --write needs both. Pass mutates
    # explicitly so the --yes-prod gate fires for --write but skips for SELECT.
    is_write = a.cmd == "exec" and getattr(a, "write", False)
    ctx = bs.setup(a, need_actor=is_write, mutates=is_write)
    return {"exec": _exec, "tables": _tables}[a.cmd](a, ctx)


if __name__ == "__main__":
    raise SystemExit(main())
