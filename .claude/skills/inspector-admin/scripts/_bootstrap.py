"""Shared bootstrap for inspector-admin scripts.

Everything every admin script needs in one place:

  setup(args, *, need_db=True, need_actor=True) → BootstrapCtx
    - resolves repo root, sets sys.path so `services.*` + `scripts.lib.*` import
    - loads HF_TOKEN from .env if missing in env
    - picks bucket repo from --prod (refuses prod for --yes-prod-only ops without the flag)
    - sets a script-private INSPECTOR_DB_PATH so we don't collide with a
      running local dev Inspector (same trick the existing launch_ts_job.py used)
    - if need_db: pulls the SQLite from the bucket + initialises the writer
    - if need_actor: constructs a real Actor from INSPECTOR_DEV_OWNER_* env

  add_common_args(parser, *, mutating=True)
    - adds --prod / --yes-prod / --dry-run

  after_write_banner(args)
    - prints the standing "deployed Space needs a restart" reminder

Pattern in each script:
    from _bootstrap import setup, add_common_args, after_write_banner
    p = argparse.ArgumentParser(...)
    add_common_args(p)
    a = p.parse_args()
    ctx = setup(a)
    # ... do the work via services/admin/* and state.transition ...
    if not a.dry_run:
        after_write_banner(a)
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Bucket id table mirrors inspector/services/storage/hf_bucket.py.
BUCKETS = {
    "dev": "hetchyy/quranic-inspector-bucket-dev",
    "prod": "hetchyy/quranic-inspector-bucket",
}


def repo_root() -> Path:
    # .claude/skills/inspector-admin/scripts/<file>.py → up 4 = repo root
    return Path(__file__).resolve().parents[4]


def _ensure_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def _load_env() -> None:
    """HF_TOKEN + INSPECTOR_DEV_OWNER_* from repo-root .env if missing."""
    env_file = repo_root() / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and not os.environ.get(k):
            os.environ[k] = v


def add_common_args(parser: argparse.ArgumentParser, *, mutating: bool = True) -> None:
    parser.add_argument("--prod", action="store_true",
                        help="target the prod bucket (default: dev)")
    if mutating:
        parser.add_argument("--yes-prod", action="store_true",
                            help="required for a prod mutating op")
        parser.add_argument("--dry-run", action="store_true",
                            help="run the handler but skip durable_transaction")


@dataclass
class BootstrapCtx:
    repo_root: Path
    bucket_id: str           # hetchyy/quranic-inspector-bucket{,-dev}
    actor: Optional[object]  # scripts.lib.schemas.audit.Actor when need_actor=True
    db_path: Path
    db_synced: bool


def setup(args: argparse.Namespace, *, need_db: bool = True,
          need_actor: bool = True,
          mutates: bool | None = None) -> BootstrapCtx:
    _ensure_utf8_stdout()

    rr = repo_root()
    for p in (str(rr), str(rr / "inspector")):
        if p not in sys.path:
            sys.path.insert(0, p)

    _load_env()

    bucket_kind = "prod" if getattr(args, "prod", False) else "dev"
    bucket_id = BUCKETS[bucket_kind]
    os.environ["INSPECTOR_BUCKET_REPO"] = bucket_id
    os.environ["INSPECTOR_ALLOW_PROD_BUCKET"] = "1" if bucket_kind == "prod" else "0"

    # Mutating-against-prod gate. ``mutates`` is the explicit signal — when
    # left None, fall back to "did the parser register a --yes-prod flag?"
    # which works for compile-time-known mutations. Subcommands whose write
    # intent depends on a runtime flag (e.g. admin_db exec --write) pass an
    # explicit ``mutates=`` and bypass the heuristic.
    is_mutation = (mutates if mutates is not None
                   else hasattr(args, "yes_prod"))
    if (bucket_kind == "prod" and is_mutation
            and not getattr(args, "yes_prod", False)
            and not getattr(args, "dry_run", False)):
        print("refusing to write to prod bucket without --yes-prod",
              file=sys.stderr)
        sys.exit(2)

    # Script-private SQLite path so we don't fight a running local Inspector
    # (Windows os.replace can't overwrite an open file).
    db_path = Path(tempfile.gettempdir()) / f"inspector_admin_{bucket_kind}.db"
    os.environ["INSPECTOR_DB_PATH"] = str(db_path)

    actor = None
    if need_actor:
        from scripts.lib.schemas import Actor  # noqa: E402
        from scripts.lib.schemas.access import Role  # noqa: E402
        hf_id = os.environ.get("INSPECTOR_DEV_OWNER_HF_ID", "").strip()
        login = os.environ.get("INSPECTOR_DEV_OWNER_LOGIN", "").strip()
        if not hf_id or not login:
            print("missing INSPECTOR_DEV_OWNER_HF_ID / _LOGIN in env or .env",
                  file=sys.stderr)
            sys.exit(3)
        actor = Actor(hf_user_id=hf_id, login_at_time=login, role=Role.OWNER)

    db_synced = False
    if need_db:
        from services import db as _db  # noqa: E402
        from services.db import sync as _db_sync  # noqa: E402
        db_synced = _db_sync.pull()
        _db.init_db()

    return BootstrapCtx(repo_root=rr, bucket_id=bucket_id, actor=actor,
                        db_path=db_path, db_synced=db_synced)


def after_write_banner(args: argparse.Namespace) -> None:
    if not getattr(args, "prod", False):
        return
    print()
    print("=" * 72)
    print("WROTE TO PROD BUCKET. The deployed Space (hetchyy/quranic-universal-audio)")
    print("holds an in-memory SQLite snapshot per-process — restart it for the new")
    print("rows to become visible in the UI.")
    print("=" * 72)


def fmt_size(n: int | float | None) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_iso(s: object) -> str:
    """ISO-string passthrough (handles None / datetimes)."""
    if s is None:
        return "—"
    if hasattr(s, "isoformat"):
        return s.isoformat(timespec="seconds")  # type: ignore[attr-defined]
    return str(s)
