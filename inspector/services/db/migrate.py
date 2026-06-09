"""Boot-time migration runner — ``PRAGMA user_version`` based.

Migrations are ``NNNN_*.sql`` files in ``migrations/``. On boot we read
``user_version``, apply every script with a higher number in order inside a
single transaction per script, and bump ``user_version`` to match. Fail-fast:
any error aborts the boot (the caller surfaces ``/healthz`` 503) rather than
silently degrading.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_NAME_RE = re.compile(r"^(\d{4})_.*\.sql$")


def _discover() -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    seen: dict[int, Path] = {}
    for p in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        m = _NAME_RE.match(p.name)
        if not m:
            logger.warning("ignoring non-conforming migration file: %s", p.name)
            continue
        number = int(m.group(1))
        # Duplicate numbers silently break the version-gated runner: once any DB
        # records ``user_version=N``, EVERY ``NNNN_*`` at that number is skipped
        # (``n > version`` is false), so a reused number never applies on a live
        # DB. Fail loudly here instead of shipping a migration that never runs.
        if number in seen:
            raise RuntimeError(
                f"duplicate migration number {number:04d}: {seen[number].name} and "
                f"{p.name} — renumber one (live DBs gate on user_version, so a reused "
                f"number is silently skipped)"
            )
        seen[number] = p
        out.append((number, p))
    out.sort(key=lambda t: t[0])
    return out


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def run_migrations(conn: sqlite3.Connection) -> int:
    """Apply all pending migrations. Returns the resulting schema version.

    Each migration runs in its own transaction; ``user_version`` is bumped in
    the same transaction so a crash mid-migration never leaves a half-applied
    version recorded.
    """
    version = current_version(conn)
    pending = [(n, p) for (n, p) in _discover() if n > version]
    if not pending:
        return version

    for number, path in pending:
        sql = path.read_text(encoding="utf-8")
        logger.info("applying migration %04d (%s)", number, path.name)
        # Wrap the script in explicit transaction control so the DDL + the
        # user_version bump apply atomically (executescript honours BEGIN/COMMIT
        # embedded in the script). A failure mid-script leaves the txn open;
        # roll it back and fail-fast.
        script = f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;"
        try:
            conn.executescript(script)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("migration %04d failed — aborting boot", number)
            raise
        version = number

    return version
