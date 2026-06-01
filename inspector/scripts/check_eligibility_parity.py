"""Phase-1 acceptance check — eligibility parity.

Asserts the v2 DB-backed eligibility set matches the legacy git-tracked set.
Run via Inspector admin endpoint or directly when an Inspector DB is mounted.

Usage:
    python -m inspector.scripts.check_eligibility_parity

Exit codes:
  0 — parity OK
  1 — mismatch (diff printed to stdout)
  2 — DB backend unavailable (cannot run the check)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the inspector package + repo root are importable when invoked as a script.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.lib.reciter_eligibility import eligible_set_via  # noqa: E402


def main() -> int:
    git_set = eligible_set_via("git")
    try:
        db_set = eligible_set_via("db")
    except Exception as exc:
        print(f"ERROR: DB backend unavailable ({exc!r})", file=sys.stderr)
        return 2

    in_git_only = sorted(git_set - db_set)
    in_db_only = sorted(db_set - git_set)

    if not in_git_only and not in_db_only:
        print(f"OK: {len(db_set)} eligible recitations match across backends.")
        return 0

    print("MISMATCH between git-tracked and DB-backed eligibility:")
    if in_git_only:
        print(f"  In git only ({len(in_git_only)}): {in_git_only}")
    if in_db_only:
        print(f"  In DB only ({len(in_db_only)}): {in_db_only}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
