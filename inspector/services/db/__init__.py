"""SQLite substrate for the inspector backend.

Single container-local ``inspector.db`` is the source of truth for the
former 7 bucket JSON stores + audit log; uploaded full-file to the bucket
after each committed write. See ``connection`` (txn primitives), ``migrate``
(schema runner), ``sync`` (bucket pull/push), and ``repo_*`` (per-domain
read/write).
"""

from __future__ import annotations

from .connection import (
    _chmod_600,
    current_db_seq,
    db_path,
    get_conn,
    get_writer,
    reset,
    set_db_path_for_test,
    transaction,
)
from .migrate import current_version, run_migrations


def init_db() -> int:
    """Open the writer + apply pending migrations. Returns schema version."""
    conn = get_writer()
    version = run_migrations(conn)
    # WAL/SHM sidecars only exist after the first write; tighten perms now.
    _chmod_600(db_path())
    return version


__all__ = [
    "current_db_seq",
    "current_version",
    "db_path",
    "get_conn",
    "get_writer",
    "init_db",
    "reset",
    "run_migrations",
    "set_db_path_for_test",
    "transaction",
]
