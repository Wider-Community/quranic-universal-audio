"""Bucket sync for the SQLite substrate.

Boot pulls ``db/inspector.db`` from the bucket; every committed write produces
a standalone snapshot (SQLite online ``backup()`` — no WAL/-shm sidecar) and
uploads it synchronously with a compare-and-swap guard before the mutating
request is acked. Uses the bucket primitives directly, bypassing the mount's
debounced flush (a container restart in that window would lose an acked write).

CAS: a tiny ``db/inspector.seq`` sidecar holds ``{seq, nonce, ts}``. Upload
refuses if the remote ``seq`` is ahead of ours AND was written by a different
container nonce (deploy-overlap guard) — last-writer does NOT silently win.

Counters (``status()``) back ``/healthz``: ``last_bucket_upload_ts``,
``bucket_lag_seconds``, ``last_error``, ``queue`` (always 0 — uploads are
synchronous in this build).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from services.storage.hf_bucket import StorageNotFound, get_backend

from . import _serde, connection

logger = logging.getLogger(__name__)

DB_BUCKET_PATH = "db/inspector.db"
SEQ_BUCKET_PATH = "db/inspector.seq"
_SNAPSHOT_RETENTION_DAYS = 30

# A per-process identity so the CAS guard can tell "our own prior upload" from
# "another container raced us during a rolling deploy".
_NONCE = uuid.uuid4().hex[:12]

_last_upload_ts: float | None = None
_last_error: str | None = None


class UploadConflict(RuntimeError):
    """The bucket DB was advanced by a different container; upload refused."""


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


def snapshot_bytes() -> bytes:
    """A consistent, standalone single-file copy of the current DB.

    Uses SQLite's online backup API, so it is safe to call with the writer
    connection open and produces a self-contained file (no WAL sidecar to
    upload). MUST be called outside an active write transaction.
    """
    src = connection.get_writer()
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dest = sqlite3.connect(tmp)
        try:
            src.backup(dest)
        finally:
            dest.close()
        return Path(tmp).read_bytes()
    finally:
        for p in (tmp, f"{tmp}-wal", f"{tmp}-shm"):
            try:
                os.remove(p)
            except OSError:
                pass


# ---- seq sidecar / CAS ----


def _local_seq() -> int:
    return connection.current_db_seq(connection.get_writer())


def _read_remote_seq() -> dict | None:
    try:
        raw = _read_direct(SEQ_BUCKET_PATH)
    except StorageNotFound:
        return None
    except Exception as e:  # treat unreadable sidecar as absent, log loudly
        logger.warning("db sync: could not read remote seq sidecar: %s", e)
        return None
    try:
        return _serde.json_loads(raw)
    except Exception:
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
    local = _local_seq()
    remote = _read_remote_seq()
    if (
        remote is not None
        and int(remote.get("seq", -1)) >= local
        and remote.get("nonce") != _NONCE
    ):
        _last_error = (
            f"CAS conflict: bucket seq={remote.get('seq')} (nonce "
            f"{remote.get('nonce')}) >= local {local}; refusing to clobber"
        )
        logger.error("db sync: %s", _last_error)
        raise UploadConflict(_last_error)
    try:
        data = snapshot_bytes()
        _write_direct(DB_BUCKET_PATH, data)
        _write_direct(SEQ_BUCKET_PATH, _seq_payload(local))
    except Exception as e:
        _last_error = f"upload failed: {e}"
        logger.exception("db sync: upload failed")
        raise
    _last_upload_ts = time.time()
    _last_error = None
    return local


# ---- boot pull ----


def pull(dest_path: str | None = None) -> bool:
    """Download the bucket DB to the local path (default: the configured DB
    path). Returns True if pulled, False if the bucket has no DB yet (fresh
    init). Always trust the bucket; clears any stale local WAL/-shm."""
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
    os.replace(tmp, dest)
    logger.info("db sync: pulled %d bytes from bucket", len(data))
    return True


# ---- daily snapshot + retention ----


def daily_snapshot(*, today: datetime | None = None) -> str:
    """Upload a dated snapshot and prune snapshots older than the retention
    window. Returns the snapshot bucket path."""
    day = (today or datetime.now(timezone.utc)).date().isoformat()
    path = f"db/inspector-{day}.db"
    _write_direct(path, snapshot_bytes())
    _prune_snapshots(today=today)
    return path


def _prune_snapshots(*, today: datetime | None = None) -> list[str]:
    import re

    cutoff = (today or datetime.now(timezone.utc)).date()
    backend = get_backend()
    try:
        names = backend.list_dir("db")
    except Exception:
        return []
    pat = re.compile(r"^inspector-(\d{4}-\d{2}-\d{2})\.db$")
    removed: list[str] = []
    for name in names:
        m = pat.match(name)
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
                logger.warning("db sync: failed to prune %s: %s", name, e)
    return removed


# ---- health ----


def bucket_lag_seconds() -> float | None:
    if _last_upload_ts is None:
        return None
    return round(time.time() - _last_upload_ts, 3)


def status() -> dict:
    return {
        "nonce": _NONCE,
        "last_bucket_upload_ts": _last_upload_ts,
        "bucket_lag_seconds": bucket_lag_seconds(),
        "last_error": _last_error,
        "queue": 0,  # synchronous uploads in this build
    }


def _reset_for_test() -> None:
    global _last_upload_ts, _last_error
    _last_upload_ts = None
    _last_error = None
