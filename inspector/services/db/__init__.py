"""SQLite substrate for the inspector backend.

Single container-local ``inspector.db`` is the source of truth for the
former 7 bucket JSON stores + audit log; uploaded full-file to the bucket
after each committed write. See ``connection`` (txn primitives), ``migrate``
(schema runner), ``sync`` (bucket pull/push), and ``repo_*`` (per-domain
read/write).
"""

from __future__ import annotations

import os

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


def substrate_enabled() -> bool:
    """True when the SQLite substrate is the source of truth.

    Transition flag (plan's ``INSPECTOR_STORE_BACKEND`` escape hatch): defaults
    to ``json`` (legacy stores) until the cutover flips it to ``sqlite``.
    """
    return os.environ.get("INSPECTOR_STORE_BACKEND", "json").lower() == "sqlite"


def healthcheck() -> dict:
    """Cheap DB status for ``/healthz`` (never raises)."""
    try:
        return {"open": True, "schema_version": current_version(get_writer())}
    except Exception as e:  # noqa: BLE001
        return {"open": False, "error": str(e)[:200]}


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
