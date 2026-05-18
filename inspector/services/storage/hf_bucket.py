"""Storage backend abstraction for the v2 deployment.

Two concrete backends:

- ``BucketBackend`` — reads/writes the private HF storage bucket. Used by
  both local and deployed modes. When ``mount`` is set (deployed Space),
  reads + writes go through the filesystem mount, with optional
  ``huggingface_hub.upload_file()`` after each write for durability beyond
  the mount's 2–30 s flush window. When ``mount`` is None (local dev),
  reads come from ``huggingface_hub.hf_hub_download`` with an on-disk
  cache; writes go via ``upload_file()`` directly.

- ``FilesystemBackend`` — POSIX-only impl for tests and ``INSPECTOR_BACKEND=
  filesystem`` opt-in offline mode. Atomic write via tmp+rename.

Spec: docs/planning/inspector-deploy/v2/inspector-data-storage.md §3.

Both backends operate on POSIX-style paths (forward slashes) for layout
neutrality. ``FilesystemBackend`` translates to native paths internally.

Single-process assumption: the module exposes a singleton via
``get_backend()`` so all services share the same instance and any per-key
locking lives consistently in one place. Multi-worker scale-out is deferred
(see inspector-data-storage.md §11).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path, PurePosixPath
from typing import Iterator, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------


class StorageError(Exception):
    """Base for backend errors."""


class StorageNotFound(StorageError):
    """The requested path does not exist."""


# ----------------------------------------------------------------------
# Protocol
# ----------------------------------------------------------------------


@runtime_checkable
class StorageBackend(Protocol):
    """The contract every backend implements."""

    def read_bytes(self, path: str) -> bytes: ...
    def read_json(self, path: str) -> dict | list: ...
    def iter_jsonl(self, path: str) -> Iterator[dict]: ...
    def write_bytes_atomic(self, path: str, data: bytes) -> None: ...
    def write_json_atomic(self, path: str, obj: dict | list) -> None: ...
    def append_jsonl(self, path: str, record: dict) -> None: ...
    def exists(self, path: str) -> bool: ...
    def list_dir(self, path: str) -> list[str]: ...
    def copy(self, src: str, dst: str) -> None: ...
    def move(self, src: str, dst: str) -> None: ...
    def delete(self, path: str) -> None: ...
    def local_path(self, path: str) -> Path | None: ...


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _ensure_posix(path: str, *, allow_empty: bool = False) -> str:
    if path.startswith("/") or "\\" in path:
        raise ValueError(f"path must be relative POSIX: {path!r}")
    if not path and not allow_empty:
        raise ValueError("path must not be empty")
    return path


def _dump_json(obj: dict | list) -> bytes:
    import orjson

    return orjson.dumps(obj, option=orjson.OPT_INDENT_2)


# ----------------------------------------------------------------------
# FilesystemBackend
# ----------------------------------------------------------------------


class FilesystemBackend:
    """Pure POSIX filesystem backend. Tests + offline opt-in.

    Atomic writes via tempfile in the same directory + ``os.replace`` so
    readers never see a torn file. Append uses standard ``"ab"`` mode (no
    atomicity guarantee — append-only files like ``edit_history.jsonl`` and
    ``audit/*.jsonl`` tolerate concurrent appends within a single process
    because higher-level locking serializes writers).
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()  # serializes atomic-write contention

    # ---- path resolution ----

    def _resolve(self, path: str) -> Path:
        _ensure_posix(path)
        return self._root / PurePosixPath(path)

    # ---- reads ----

    def read_bytes(self, path: str) -> bytes:
        p = self._resolve(path)
        if not p.exists():
            raise StorageNotFound(path)
        return p.read_bytes()

    def read_json(self, path: str) -> dict | list:
        import orjson

        return orjson.loads(self.read_bytes(path))

    def iter_jsonl(self, path: str) -> Iterator[dict]:
        p = self._resolve(path)
        if not p.exists():
            return
        import orjson

        with p.open("rb") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                yield orjson.loads(line)

    # ---- writes ----

    def write_bytes_atomic(self, path: str, data: bytes) -> None:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock:
            fd, tmp = tempfile.mkstemp(prefix=p.name + ".tmp.", dir=str(p.parent))
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, str(p))
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    def write_json_atomic(self, path: str, obj: dict | list) -> None:
        self.write_bytes_atomic(path, _dump_json(obj))

    def append_jsonl(self, path: str, record: dict) -> None:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        import orjson

        line = orjson.dumps(record) + b"\n"
        with self._write_lock, p.open("ab") as fh:
            fh.write(line)

    # ---- introspection / moves ----

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def list_dir(self, path: str) -> list[str]:
        if path == "":
            p = self._root
        else:
            p = self._resolve(path)
        if not p.is_dir():
            return []
        return sorted(child.name for child in p.iterdir())

    def copy(self, src: str, dst: str) -> None:
        s = self._resolve(src)
        d = self._resolve(dst)
        if not s.exists():
            raise StorageNotFound(src)
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)

    def move(self, src: str, dst: str) -> None:
        s = self._resolve(src)
        d = self._resolve(dst)
        if not s.exists():
            raise StorageNotFound(src)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))

    def delete(self, path: str) -> None:
        p = self._resolve(path)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()

    def local_path(self, path: str) -> Path | None:
        p = self._resolve(path)
        return p if p.exists() else None


# ----------------------------------------------------------------------
# BucketBackend
# ----------------------------------------------------------------------


class BucketBackend:
    """HF storage bucket backend.

    Uses the bucket-specific API (``batch_bucket_files``, ``list_bucket_tree``,
    ``hffs.cat_file``, ``get_bucket_file_metadata``) — distinct from the repo
    API (``upload_file`` / ``hf_hub_download``). Bucket IDs are
    ``owner/name`` strings; the ``hf://buckets/`` URI form is for fsspec only.

    Mount + direct-upload hybrid:

    - With a mount (deployed Spaces via ``hf-mount``): reads go through the
      mount, falling back to the bucket API on cache miss. Writes go
      through the mount only — the hf-mount daemon's debounced flush
      handles durability.
    - Without a mount (local mode): reads go through ``hffs.cat_file()``;
      writes go through ``batch_bucket_files(add=...)``.

    Spec: docs/planning/inspector-deploy/v2/inspector-data-storage.md §3.
    """

    def __init__(
        self,
        bucket_id: str,
        *,
        token: str | None = None,
        mount: str | Path | None = None,
    ) -> None:
        self._bucket_id = bucket_id
        self._token = (
            token
            or os.environ.get("INSPECTOR_HF_TOKEN")
            or os.environ.get("HF_TOKEN")
        )
        self._mount: Path | None = Path(mount).resolve() if mount else None
        self._write_lock = threading.Lock()

        # Bucket writes go through Xet storage, which requires the token to
        # be registered via login() (per-call token= doesn't establish Xet
        # auth). Idempotent; safe to call repeatedly across replicas.
        if self._token:
            try:
                from huggingface_hub import (  # type: ignore[import-not-found]
                    login as _hf_login,
                )

                _hf_login(token=self._token, add_to_git_credential=False)
            except Exception as e:  # noqa: BLE001
                logger.warning("huggingface_hub.login() failed: %s", e)

        if self._mount is not None and not self._mount.exists():
            logger.warning(
                "BucketBackend mount %s does not exist; falling back to bucket "
                "API for all reads + writes.",
                self._mount,
            )
            self._mount = None

    # ---- helpers ----

    def _bucket_uri(self, path: str) -> str:
        """Return the ``buckets/<id>/<path>`` form used by ``hffs``."""
        return f"buckets/{self._bucket_id}/{path}"

    def _is_not_found(self, exc: Exception) -> bool:
        """Heuristic: HF API doesn't expose a single bucket-NotFound error;
        404s surface as ``HfHubHTTPError`` with a 404 status, ``KeyError`` on
        missing tree entries, or fsspec's ``FileNotFoundError``.
        """
        if isinstance(exc, FileNotFoundError):
            return True
        # HfHubHTTPError carries a response with status_code
        response = getattr(exc, "response", None)
        if response is not None and getattr(response, "status_code", None) == 404:
            return True
        return False

    # ---- reads ----

    def read_bytes(self, path: str) -> bytes:
        _ensure_posix(path)
        if self._mount is not None:
            mp = self._mount / PurePosixPath(path)
            if mp.exists():
                return mp.read_bytes()

        from huggingface_hub import hffs  # type: ignore[import-not-found]

        try:
            return hffs.cat_file(self._bucket_uri(path))
        except Exception as e:
            if self._is_not_found(e):
                raise StorageNotFound(path) from e
            raise

    def local_path(self, path: str) -> Path | None:
        """Return the mount-backed local path for ``path`` if available.

        Returns ``None`` in local-dev mode (no mount) or when the file isn't
        on the mount yet. The audio-proxy uses this to hand a real path to
        ``send_file`` so Werkzeug can serve Range/304 via OS sendfile —
        avoiding the whole-chapter slurp + BytesIO round-trip.
        """
        _ensure_posix(path)
        if self._mount is None:
            return None
        mp = self._mount / PurePosixPath(path)
        return mp if mp.exists() else None

    def read_json(self, path: str) -> dict | list:
        import orjson

        return orjson.loads(self.read_bytes(path))

    def iter_jsonl(self, path: str) -> Iterator[dict]:
        try:
            raw = self.read_bytes(path)
        except StorageNotFound:
            return
        import orjson

        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            yield orjson.loads(stripped)

    # ---- writes ----

    def _bucket_upload(self, path: str, data: bytes) -> None:
        from huggingface_hub import (  # type: ignore[import-not-found]
            batch_bucket_files,
            hffs,
        )

        batch_bucket_files(self._bucket_id, add=[(data, path)], token=self._token)
        # fsspec caches directory listings + read content; without this,
        # read-after-write inside the same process returns the pre-upload state.
        try:
            hffs.invalidate_cache(self._bucket_uri(path))
        except Exception:
            try:
                hffs.invalidate_cache()
            except Exception:
                pass

    def write_bytes_atomic(self, path: str, data: bytes) -> None:
        _ensure_posix(path)
        with self._write_lock:
            if self._mount is not None:
                mp = self._mount / PurePosixPath(path)
                mp.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(prefix=mp.name + ".tmp.", dir=str(mp.parent))
                try:
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(data)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.replace(tmp, str(mp))
                except Exception:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise
                return

            self._bucket_upload(path, data)

    def write_json_atomic(self, path: str, obj: dict | list) -> None:
        self.write_bytes_atomic(path, _dump_json(obj))

    def append_jsonl(self, path: str, record: dict) -> None:
        """Append-one-line. With a mount, append happens in-place locally
        and the daemon flushes asynchronously. Without a mount we
        read-modify-write through the bucket API (no streaming append).

        Acceptable at our write rate (≤1 save / 10 s per active reviewer ×
        ≤25 concurrent reviewers per replica).
        """
        _ensure_posix(path)
        import orjson

        line = orjson.dumps(record) + b"\n"
        with self._write_lock:
            if self._mount is not None:
                mp = self._mount / PurePosixPath(path)
                mp.parent.mkdir(parents=True, exist_ok=True)
                with mp.open("ab") as fh:
                    fh.write(line)
                return

            try:
                current = self.read_bytes(path)
            except StorageNotFound:
                current = b""
            self._bucket_upload(path, current + line)

    # ---- introspection / moves ----

    def exists(self, path: str) -> bool:
        _ensure_posix(path)
        if self._mount is not None:
            mp = self._mount / PurePosixPath(path)
            if mp.exists():
                return True
        from huggingface_hub import (  # type: ignore[import-not-found]
            get_bucket_file_metadata,
        )

        try:
            get_bucket_file_metadata(self._bucket_id, path, token=self._token)
            return True
        except Exception as e:
            if self._is_not_found(e):
                return False
            logger.warning("BucketBackend.exists(%s) errored: %s", path, e)
            return False

    def list_dir(self, path: str) -> list[str]:
        _ensure_posix(path, allow_empty=True)
        if self._mount is not None:
            mp = self._mount if path == "" else self._mount / PurePosixPath(path)
            if mp.is_dir():
                return sorted(child.name for child in mp.iterdir())

        from huggingface_hub import list_bucket_tree  # type: ignore[import-not-found]

        try:
            kwargs = {"recursive": False, "token": self._token}
            if path:
                kwargs["prefix"] = path.rstrip("/")
            items = list_bucket_tree(self._bucket_id, **kwargs)
        except Exception as e:
            if self._is_not_found(e):
                return []
            logger.warning("BucketBackend.list_dir(%s) errored: %s", path, e)
            return []

        prefix = (path.rstrip("/") + "/") if path else ""
        names: set[str] = set()
        for it in items:
            p = it.path
            if prefix and not p.startswith(prefix):
                continue
            tail = p[len(prefix):] if prefix else p
            if not tail:
                continue
            names.add(tail.split("/", 1)[0])
        return sorted(names)

    def copy(self, src: str, dst: str) -> None:
        """Server-side copy by Xet hash when possible; falls back to
        read-then-upload for files without a Xet hash (small JSON, etc.)."""
        _ensure_posix(src)
        _ensure_posix(dst)
        from huggingface_hub import (  # type: ignore[import-not-found]
            batch_bucket_files,
            get_bucket_file_metadata,
        )

        try:
            meta = get_bucket_file_metadata(self._bucket_id, src, token=self._token)
        except Exception as e:
            if self._is_not_found(e):
                raise StorageNotFound(src) from e
            raise

        xet_hash = getattr(meta, "xet_hash", None)
        if xet_hash:
            batch_bucket_files(
                self._bucket_id,
                copy=[("bucket", self._bucket_id, xet_hash, dst)],
                token=self._token,
            )
            return
        data = self.read_bytes(src)
        self._bucket_upload(dst, data)

    def move(self, src: str, dst: str) -> None:
        self.copy(src, dst)
        self.delete(src)

    def delete(self, path: str) -> None:
        _ensure_posix(path)
        if self._mount is not None:
            mp = self._mount / PurePosixPath(path)
            if mp.is_dir():
                shutil.rmtree(mp, ignore_errors=True)
            elif mp.exists():
                mp.unlink()
        try:
            from huggingface_hub import (  # type: ignore[import-not-found]
                batch_bucket_files,
                hffs,
            )

            batch_bucket_files(self._bucket_id, delete=[path], token=self._token)
            try:
                hffs.invalidate_cache(self._bucket_uri(path))
            except Exception:
                pass
        except Exception as e:
            if not self._is_not_found(e):
                logger.warning("BucketBackend.delete(%s) errored: %s", path, e)


# ----------------------------------------------------------------------
# Singleton factory
# ----------------------------------------------------------------------


_backend_singleton: StorageBackend | None = None
_backend_lock = threading.Lock()


def get_backend() -> StorageBackend:
    """Return the process-wide storage backend.

    Configured via env vars:

    - ``INSPECTOR_BACKEND`` — ``bucket`` (default) | ``filesystem``
    - ``INSPECTOR_FILESYSTEM_ROOT`` — root path for ``FilesystemBackend``
    - ``INSPECTOR_BUCKET_REPO`` — HF repo id (default
      ``hetchyy/quranic-inspector-bucket-dev`` for local + dev Space;
      override to the prod repo in the prod Space)
    - ``INSPECTOR_BUCKET_MOUNT`` — mount path inside deployed Space; unset
      in local mode (BucketBackend uses ``hf_hub_download`` instead)
    - ``INSPECTOR_HF_TOKEN`` / ``HF_TOKEN`` — write/read token
    """
    global _backend_singleton
    if _backend_singleton is not None:
        return _backend_singleton

    with _backend_lock:
        if _backend_singleton is not None:
            return _backend_singleton

        kind = os.environ.get("INSPECTOR_BACKEND", "bucket").strip().lower()
        if kind == "filesystem":
            root = os.environ.get("INSPECTOR_FILESYSTEM_ROOT")
            if not root:
                raise RuntimeError(
                    "INSPECTOR_BACKEND=filesystem requires INSPECTOR_FILESYSTEM_ROOT"
                )
            backend: StorageBackend = FilesystemBackend(root)
        elif kind == "bucket":
            bucket_id = os.environ.get(
                "INSPECTOR_BUCKET_REPO", "hetchyy/quranic-inspector-bucket-dev"
            )
            # Opt into the local FUSE mount on first use. No-op if app.py
            # already mounted at boot, under pytest, behind the Space
            # proxy, or if hf-mount isn't installed. Scripts that go
            # straight to get_backend() get the speedup without explicit
            # plumbing.
            from services.storage.auto_mount import auto_mount
            auto_mount()
            mount = os.environ.get("INSPECTOR_BUCKET_MOUNT") or None
            backend = BucketBackend(
                bucket_id=bucket_id,
                mount=mount,
            )
        else:
            raise RuntimeError(f"unknown INSPECTOR_BACKEND={kind!r}")

        _backend_singleton = backend
        return backend


def set_backend(backend: StorageBackend) -> None:
    """Replace the singleton — used by tests via the conftest fixture."""
    global _backend_singleton
    with _backend_lock:
        _backend_singleton = backend


def reset_backend() -> None:
    """Drop the singleton so the next ``get_backend()`` re-reads env."""
    global _backend_singleton
    with _backend_lock:
        _backend_singleton = None
