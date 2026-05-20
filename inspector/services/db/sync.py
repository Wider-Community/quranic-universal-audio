"""Bucket sync for the SQLite substrate.

Boot pulls ``db/inspector.db`` from the bucket; every committed write produces
a standalone snapshot (SQLite online ``backup()`` — no WAL/-shm sidecar) and
uploads it synchronously with a compare-and-swap guard before the mutating
request is acked. Uses the bucket primitives directly, bypassing the mount's
debounced flush (a container restart in that window would lose an acked write).

CAS: a tiny ``db/inspector.seq`` sidecar holds ``{seq, nonce, ts}``. The seq is
read FROM the snapshot itself, so it always matches the uploaded content. Upload
refuses if the remote ``seq`` is ahead of ours AND was written by a different
container nonce (deploy-overlap guard).

CAVEAT: bucket I/O has no atomic compare-and-swap, so this guard catches a
*stale* racer, not two writers committing in the exact same instant. It is safe
under the project's single-active-writer invariant (one Space, single worker);
a rolling-deploy overlap is the window it covers. Documented, not eliminated.

Counters (``status()``) back ``/healthz``.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from services.storage.hf_bucket import StorageNotFound, get_backend

from . import _serde, connection

logger = logging.getLogger(__name__)

DB_BUCKET_PATH = "db/inspector.db"
SEQ_BUCKET_PATH = "db/inspector.seq"
_SNAPSHOT_RETENTION_DAYS = 30
_SNAPSHOT_RE = re.compile(r"^inspector-(\d{4}-\d{2}-\d{2})\.db$")

# Per-process identity so the CAS guard can tell "our own prior upload" from
# "another container raced us during a rolling deploy".
_NONCE = uuid.uuid4().hex[:12]

_state_lock = threading.Lock()
_last_upload_ts: float | None = None
_last_error: str | None = None

# Durability seam (the "no 200 without a durable bucket copy" invariant).
# ``_SYNC_ENABLED`` is True in production; tests disable it via
# ``set_sync_enabled(False)`` so the bulk of the suite doesn't pay snapshot
# cost (dedicated durability tests flip it back on). ``_defer_depth`` lets a
# boot-scan / sweeper batch wrap N transitions in ``deferred_sync()`` so the
# loop uploads ONCE instead of once-per-commit (the boot/bucket-storm fix).
_SYNC_ENABLED = True
_defer_depth: ContextVar[int] = ContextVar("db_sync_defer_depth", default=0)


class UploadConflict(RuntimeError):
    """The bucket DB was advanced by a different container; upload refused."""


def _safe_err(e: Exception) -> str:
    """Exception text without leaking secrets (HF errors can embed token=... URLs)."""
    return f"{type(e).__name__}: {str(e)[:200]}"


# ---- mount-bypassing I/O (direct on BucketBackend; plain on FilesystemBackend) ----


def _read_direct(path: str) -> bytes:
    backend = get_backend()
    fn = getattr(backend, "read_bytes_direct", None) or backend.read_bytes
    return fn(path)


def _write_direct(path: str, data: bytes) -> None:
    backend = get_backend()
    fn = getattr(backend, "write_bytes_direct", None) or backend.write_bytes_atomic
    fn(path, data)


# ---- snapshot ----


def snapshot() -> tuple[bytes, int]:
    """Return (standalone-db-bytes, db_seq) for the current DB.

    Uses SQLite's online backup API → a self-contained file (no WAL sidecar).
    The seq is read from the snapshot itself so the uploaded bytes and the
    labelled seq can never disagree. MUST run outside an active write txn.
    """
    if connection._active.get() is not None:  # type: ignore[attr-defined]
        raise RuntimeError("snapshot() called inside an active write transaction")
    src = connection.get_writer()
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dest = sqlite3.connect(tmp)
        try:
            src.backup(dest)
            row = dest.execute("SELECT value FROM db_meta WHERE key='db_seq'").fetchone()
            seq = int(row[0]) if row else 0
        finally:
            dest.close()
        return Path(tmp).read_bytes(), seq
    finally:
        for p in (tmp, f"{tmp}-wal", f"{tmp}-shm"):
            try:
                os.remove(p)
            except OSError:
                pass


def snapshot_bytes() -> bytes:
    return snapshot()[0]


# ---- seq sidecar / CAS ----


def _read_remote_seq() -> dict | None:
    try:
        raw = _read_direct(SEQ_BUCKET_PATH)
    except StorageNotFound:
        return None
    except Exception as e:
        logger.warning("db sync: could not read remote seq sidecar: %s", _safe_err(e))
        return None
    try:
        return _serde.json_loads(raw)
    except Exception as e:
        logger.warning("db sync: malformed remote seq sidecar: %s", _safe_err(e))
        return None


def _seq_payload(seq: int) -> bytes:
    return _serde.json_dumps(
        {"seq": seq, "nonce": _NONCE, "ts": _serde.to_iso(_serde.now())}
    ).encode("utf-8")


# ---- upload (synchronous, CAS-guarded) ----


def upload() -> int:
    """Snapshot + upload the DB with a CAS guard. Returns the uploaded seq.

    Raises ``UploadConflict`` if the bucket was advanced by another container
    (the caller surfaces 5xx; the local commit stays ahead and a later upload
    reconciles). On any failure ``last_error`` is set and the exception
    propagates — never report a write durable that isn't in the bucket.
    """
    global _last_upload_ts, _last_error
    data, snap_seq = snapshot()  # seq read from the snapshot → matches the bytes
    remote = _read_remote_seq()
    if (
        remote is not None
        and int(remote.get("seq", -1)) >= snap_seq
        and remote.get("nonce") != _NONCE
    ):
        msg = (
            f"CAS conflict: bucket seq={remote.get('seq')} (nonce "
            f"{remote.get('nonce')}) >= local {snap_seq}; refusing to clobber"
        )
        with _state_lock:
            _last_error = msg
        logger.error("db sync: %s", msg)
        raise UploadConflict(msg)
    try:
        _write_direct(DB_BUCKET_PATH, data)
        _write_direct(SEQ_BUCKET_PATH, _seq_payload(snap_seq))
    except Exception as e:
        with _state_lock:
            _last_error = _safe_err(e)
        logger.exception("db sync: upload failed")
        raise
    with _state_lock:
        _last_upload_ts = time.time()
        _last_error = None
    return snap_seq


# ---- boot pull ----


def pull(dest_path: str | None = None) -> bool:
    """Download the bucket DB to the local path (default: the configured DB
    path). Returns True if pulled, False if the bucket has no DB yet. Always
    trust the bucket; clears stale local WAL/-shm; perms tightened to 0600."""
    dest = dest_path or connection.db_path()
    try:
        data = _read_direct(DB_BUCKET_PATH)
    except StorageNotFound:
        logger.info("db sync: no DB in bucket yet — fresh init")
        return False
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    for side in (f"{dest}-wal", f"{dest}-shm"):
        try:
            os.remove(side)
        except OSError:
            pass
    tmp = f"{dest}.pull.tmp"
    Path(tmp).write_bytes(data)
    try:
        os.chmod(tmp, 0o600)  # DB holds private requests/audit
    except OSError:
        pass
    os.replace(tmp, dest)
    logger.info("db sync: pulled %d bytes from bucket", len(data))
    return True


# ---- daily snapshot + retention ----


def daily_snapshot(*, today: datetime | None = None) -> str:
    day = (today or datetime.now(timezone.utc)).date().isoformat()
    path = f"db/inspector-{day}.db"
    _write_direct(path, snapshot_bytes())
    _prune_snapshots(today=today)
    return path


def _prune_snapshots(*, today: datetime | None = None) -> list[str]:
    cutoff = (today or datetime.now(timezone.utc)).date()
    backend = get_backend()
    try:
        names = backend.list_dir("db")
    except Exception as e:
        logger.warning("db sync: snapshot prune skipped (list_dir failed): %s", _safe_err(e))
        return []
    removed: list[str] = []
    for name in names:
        m = _SNAPSHOT_RE.match(name)
        if not m:
            continue
        try:
            d = datetime.fromisoformat(m.group(1)).date()
        except ValueError:
            continue
        if (cutoff - d).days > _SNAPSHOT_RETENTION_DAYS:
            try:
                backend.delete(f"db/{name}")
                removed.append(name)
            except Exception as e:
                logger.warning("db sync: failed to prune %s: %s", name, _safe_err(e))
    return removed


# ---- health ----


def bucket_lag_seconds() -> float | None:
    if _last_upload_ts is None:
        return None
    return round(time.time() - _last_upload_ts, 3)


def status() -> dict:
    with _state_lock:
        return {
            "nonce": _NONCE,
            "last_bucket_upload_ts": _last_upload_ts,
            "bucket_lag_seconds": bucket_lag_seconds(),
            "last_error": _last_error,
            "queue": 0,  # synchronous uploads in this build
        }


def _reset_for_test() -> None:
    global _last_upload_ts, _last_error
    with _state_lock:
        _last_upload_ts = None
        _last_error = None


# ---- durability seam (used by every mutating service boundary) ----


def set_sync_enabled(enabled: bool) -> None:
    """Arm/disarm the per-commit bucket upload. Production keeps it armed;
    tests disarm it unless they specifically assert durability."""
    global _SYNC_ENABLED
    _SYNC_ENABLED = enabled


def is_sync_enabled() -> bool:
    return _SYNC_ENABLED


def mark_durable() -> None:
    """Make the just-committed transaction durable on the bucket.

    No-op when sync is disarmed (tests) or when inside a ``deferred_sync()``
    batch (the batch uploads once on exit). Raises (→ caller maps to 5xx) on
    ``UploadConflict`` / upload failure so a write absent from the bucket is
    never acked 200.
    """
    if not _SYNC_ENABLED or _defer_depth.get() > 0:
        return
    upload()


@contextmanager
def deferred_sync() -> Iterator[None]:
    """Coalesce uploads across a batch of commits into ONE upload on exit.

    Boot-scan (``hydrate_initial_seen``) and the wip sweeper apply N transitions
    in a loop; without this each would CAS-upload, storming the bucket at boot.
    The outermost block uploads once (only if the body didn't raise and at least
    one durable boundary ran). Re-entrant via a depth counter.
    """
    token = _defer_depth.set(_defer_depth.get() + 1)
    raised = False
    try:
        yield
    except BaseException:
        raised = True
        raise
    finally:
        depth = _defer_depth.get()
        _defer_depth.reset(token)
        if depth == 1 and not raised and _SYNC_ENABLED:
            upload()


@contextmanager
def durable_transaction() -> Iterator[sqlite3.Connection]:
    """A top-level write transaction whose commit is uploaded to the bucket
    before control returns to the caller. Use at EVERY mutating service
    boundary (``state.transition``, ``access`` grant/revoke/update, activity
    mutations). The upload fires after the txn commits and the active-conn
    ContextVar clears (``snapshot()`` requires no active txn). On upload failure
    the exception propagates — the route layer turns it into 5xx."""
    with connection.transaction() as conn:
        yield conn
    mark_durable()
