"""SQLite connection + transaction primitives for the inspector substrate.

Single-writer / WAL-readers model (single-worker gunicorn, 16 threads):

- ONE serialized writer connection guarded by a re-entrant ``_WRITE_LOCK``.
  All mutations go through ``transaction()`` which opens ``BEGIN IMMEDIATE``
  on the writer connection and commits atomically.
- Thread-local READER connections in autocommit + ``query_only`` mode. WAL
  lets readers run concurrently with the writer, and because readers hold no
  long-lived transaction each ``SELECT`` sees the latest committed snapshot
  (this is the read-after-write guarantee — no stale reads after a commit).

``transaction()`` is re-entrant / savepoint-aware: nested calls (e.g. a
state handler that calls ``catalog`` + ``request`` repos which each open a
transaction) enroll in the active connection via a ``ContextVar`` and use a
SAVEPOINT, never a fresh ``BEGIN``. This is what makes multi-store handlers
atomic.

Every committed write txn bumps ``db_meta.db_seq`` — the monotonic counter
the bucket-sync CAS guard relies on.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# ----------------------------------------------------------------------
# module state
# ----------------------------------------------------------------------

_lock = threading.Lock()                 # guards writer/path (re)initialisation
_WRITE_LOCK = threading.RLock()          # serializes writers; re-entrant for nesting
_writer: sqlite3.Connection | None = None
_readers = threading.local()
_db_path: str | None = None
_generation = 0                          # bumped on reset so stale readers reopen

# The connection bound to the currently-active write transaction (if any).
_active: ContextVar[sqlite3.Connection | None] = ContextVar("db_active_conn", default=None)
# Nesting depth + a per-depth savepoint name, for re-entrant transaction().
_depth: ContextVar[int] = ContextVar("db_txn_depth", default=0)


# ----------------------------------------------------------------------
# path resolution
# ----------------------------------------------------------------------


def db_path() -> str:
    """Resolve the on-disk DB path (``INSPECTOR_DB_PATH`` or a temp default)."""
    global _db_path
    if _db_path is None:
        _db_path = os.environ.get(
            "INSPECTOR_DB_PATH", str(Path(tempfile.gettempdir()) / "inspector.db")
        )
    return _db_path


def set_db_path_for_test(path: str | os.PathLike[str]) -> None:
    """Point the module at a fresh DB file (tests only). Closes any open conns."""
    global _db_path
    reset()
    _db_path = str(path)


def _apply_pragmas(conn: sqlite3.Connection, *, writer: bool) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    if not writer:
        conn.execute("PRAGMA query_only = ON")


def _open(*, writer: bool) -> sqlite3.Connection:
    path = db_path()
    parent = Path(path).parent
    if str(parent) and path != ":memory:":
        parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None → autocommit; we manage BEGIN/COMMIT explicitly.
    conn = sqlite3.connect(
        path, isolation_level=None, check_same_thread=False, timeout=5.0
    )
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn, writer=writer)
    if writer and path != ":memory:":
        _chmod_600(path)
    return conn


def _chmod_600(path: str) -> None:
    # DB holds private requests/audit. POSIX only; no-op / best-effort on Windows.
    for p in (path, f"{path}-wal", f"{path}-shm"):
        try:
            if os.path.exists(p):
                os.chmod(p, 0o600)
        except OSError:
            pass


# ----------------------------------------------------------------------
# connection accessors
# ----------------------------------------------------------------------


def get_writer() -> sqlite3.Connection:
    global _writer
    if _writer is None:
        with _lock:
            if _writer is None:
                _writer = _open(writer=True)
    return _writer


def _get_reader() -> sqlite3.Connection:
    gen = getattr(_readers, "generation", None)
    conn = getattr(_readers, "conn", None)
    if conn is None or gen != _generation:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        conn = _open(writer=False)
        _readers.conn = conn
        _readers.generation = _generation
    return conn


def get_conn() -> sqlite3.Connection:
    """Return the active write-txn connection if one is open on this context,
    else a thread-local autocommit reader (always-fresh committed snapshot)."""
    active = _active.get()
    if active is not None:
        return active
    return _get_reader()


# ----------------------------------------------------------------------
# transactions
# ----------------------------------------------------------------------


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Re-entrant write transaction.

    Top-level: acquire ``_WRITE_LOCK``, ``BEGIN IMMEDIATE`` on the writer,
    yield it, then bump ``db_seq`` + ``COMMIT`` (or ``ROLLBACK`` on error).
    Nested: reuse the active connection via a ``SAVEPOINT`` so a nested
    failure rolls back only its own work while still being part of the
    outer atomic unit.
    """
    active = _active.get()
    if active is not None:
        # nested — savepoint for partial rollback isolation
        depth = _depth.get() + 1
        sp = f"sp_{depth}"
        active.execute(f"SAVEPOINT {sp}")
        token = _depth.set(depth)
        try:
            yield active
        except Exception:
            active.execute(f"ROLLBACK TO {sp}")
            active.execute(f"RELEASE {sp}")
            raise
        else:
            active.execute(f"RELEASE {sp}")
        finally:
            _depth.reset(token)
        return

    # top-level. _WRITE_LOCK and the context vars are set up so that ANY
    # failure (incl. BEGIN/COMMIT/db_seq bump) still releases the lock and
    # never leaves the shared writer connection mid-transaction.
    _WRITE_LOCK.acquire()
    try:
        conn = get_writer()
        tok_active = _active.set(conn)
        tok_depth = _depth.set(0)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                _bump_db_seq(conn)
                conn.execute("COMMIT")
            except Exception:
                # roll back the (possibly still-open) txn; swallow rollback
                # errors so the original exception propagates intact.
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        finally:
            _active.reset(tok_active)
            _depth.reset(tok_depth)
    finally:
        _WRITE_LOCK.release()


def _bump_db_seq(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE db_meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
        "WHERE key = 'db_seq'"
    )


def current_db_seq(conn: sqlite3.Connection | None = None) -> int:
    c = conn or get_conn()
    row = c.execute("SELECT value FROM db_meta WHERE key = 'db_seq'").fetchone()
    return int(row[0]) if row else 0


# ----------------------------------------------------------------------
# lifecycle
# ----------------------------------------------------------------------


def reset() -> None:
    """Close the writer + invalidate readers. Used by tests + path switches."""
    global _writer, _generation
    with _lock:
        if _writer is not None:
            try:
                _writer.close()
            except Exception:
                pass
            _writer = None
        _generation += 1  # forces every thread's reader to reopen lazily
