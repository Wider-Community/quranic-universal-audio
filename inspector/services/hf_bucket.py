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

import io
import json
import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path, PurePosixPath
from typing import IO, Iterator, Protocol, runtime_checkable

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


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _ensure_posix(path: str) -> str:
    if not path or path.startswith("/") or "\\" in path:
        raise ValueError(f"path must be relative POSIX: {path!r}")
    return path


def _dump_json(obj: dict | list) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False).encode(
        "utf-8"
    )


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
        return json.loads(self.read_bytes(path).decode("utf-8"))

    def iter_jsonl(self, path: str) -> Iterator[dict]:
        p = self._resolve(path)
        if not p.exists():
            return
        with p.open("rb") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                yield json.loads(line.decode("utf-8"))

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
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._write_lock, p.open("ab") as fh:
            fh.write(line.encode("utf-8"))

    # ---- introspection / moves ----

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def list_dir(self, path: str) -> list[str]:
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


# ----------------------------------------------------------------------
# BucketBackend
# ----------------------------------------------------------------------


class BucketBackend:
    """HF storage bucket backend. Mount + direct-upload hybrid.

    Operations on the same conceptual file always go through the **mount**
    when a mount is configured (deployed Spaces) so the local NFS cache
    handles repeat reads. Writes additionally call
    ``huggingface_hub.upload_file()`` for durability beyond the mount's
    flush window — this is the per-write upload pattern documented in
    data-storage §3.

    Without a mount (local mode), reads route through ``hf_hub_download``
    backed by a local cache directory. Writes call ``upload_file()``
    directly.
    """

    def __init__(
        self,
        repo_id: str,
        *,
        repo_type: str = "dataset",
        token: str | None = None,
        mount: str | Path | None = None,
        cache_dir: str | Path | None = None,
        force_flush_on_write: bool = True,
    ) -> None:
        self._repo_id = repo_id
        self._repo_type = repo_type
        self._token = token or os.environ.get("INSPECTOR_HF_TOKEN") or os.environ.get(
            "HF_TOKEN"
        )
        self._mount: Path | None = Path(mount).resolve() if mount else None
        self._cache_dir = Path(
            cache_dir or os.path.expanduser("~/.cache/inspector/bucket")
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._force_flush_on_write = force_flush_on_write
        self._write_lock = threading.Lock()

        # Lazy huggingface_hub import — keeps tests fast and lets the
        # module load without HF deps when only FilesystemBackend is used.
        self._hf = None  # type: ignore[assignment]

        # If mount is configured, validate it exists at construction time.
        if self._mount is not None and not self._mount.exists():
            logger.warning(
                "BucketBackend mount %s does not exist yet; falling back to "
                "direct upload/download.",
                self._mount,
            )
            self._mount = None

    # ---- lazy hf client ----

    def _hf_api(self):
        if self._hf is None:
            from huggingface_hub import HfApi  # type: ignore[import-not-found]

            self._hf = HfApi(token=self._token)
        return self._hf

    # ---- path resolution ----

    def _mount_path(self, path: str) -> Path | None:
        _ensure_posix(path)
        if self._mount is None:
            return None
        return self._mount / PurePosixPath(path)

    # ---- reads ----

    def read_bytes(self, path: str) -> bytes:
        _ensure_posix(path)
        if self._mount is not None:
            mp = self._mount / PurePosixPath(path)
            if mp.exists():
                return mp.read_bytes()
            # fall through to HF download — file may not be in the mount
            # cache yet on first access
        from huggingface_hub import hf_hub_download  # type: ignore[import-not-found]
        from huggingface_hub.errors import EntryNotFoundError  # type: ignore[import-not-found]

        try:
            local = hf_hub_download(
                repo_id=self._repo_id,
                filename=path,
                repo_type=self._repo_type,
                token=self._token,
                cache_dir=str(self._cache_dir),
            )
        except EntryNotFoundError as e:
            raise StorageNotFound(path) from e
        return Path(local).read_bytes()

    def read_json(self, path: str) -> dict | list:
        return json.loads(self.read_bytes(path).decode("utf-8"))

    def iter_jsonl(self, path: str) -> Iterator[dict]:
        try:
            raw = self.read_bytes(path)
        except StorageNotFound:
            return
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            yield json.loads(stripped.decode("utf-8"))

    # ---- writes ----

    def _upload(self, path: str, data: bytes, commit_message: str | None = None) -> None:
        from huggingface_hub import upload_file  # type: ignore[import-not-found]

        buf = io.BytesIO(data)
        upload_file(
            path_or_fileobj=buf,
            path_in_repo=path,
            repo_id=self._repo_id,
            repo_type=self._repo_type,
            token=self._token,
            commit_message=commit_message or f"update {path}",
        )

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
                if self._force_flush_on_write:
                    self._upload(path, data)
                return

            # No mount: direct upload only.
            self._upload(path, data)

    def write_json_atomic(self, path: str, obj: dict | list) -> None:
        self.write_bytes_atomic(path, _dump_json(obj))

    def append_jsonl(self, path: str, record: dict) -> None:
        """Append-one-line. Since HF buckets don't expose a streaming append,
        we read the current file, append the line in memory, and re-upload.

        For high-frequency append paths (``edit_history.jsonl`` under active
        editing), this is acceptable at our write rate (≤1 save / 10 s per
        active reviewer × ≤25 concurrent reviewers per replica). If it becomes
        a hotspot, the mount-write + lazy flush path bypasses the read-modify-
        write cycle.
        """
        _ensure_posix(path)
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            if self._mount is not None:
                mp = self._mount / PurePosixPath(path)
                mp.parent.mkdir(parents=True, exist_ok=True)
                with mp.open("ab") as fh:
                    fh.write(line)
                if self._force_flush_on_write:
                    # Re-read the mount file and upload; the mount may have
                    # buffered earlier writes that need durability.
                    self._upload(path, mp.read_bytes())
                return

            # No mount: read-modify-write via HF.
            try:
                current = self.read_bytes(path)
            except StorageNotFound:
                current = b""
            self._upload(path, current + line)

    # ---- introspection / moves ----

    def exists(self, path: str) -> bool:
        _ensure_posix(path)
        if self._mount is not None:
            mp = self._mount / PurePosixPath(path)
            if mp.exists():
                return True
        # Probe via HfApi.
        try:
            api = self._hf_api()
            files = api.list_repo_files(
                repo_id=self._repo_id, repo_type=self._repo_type
            )
        except Exception as e:
            logger.warning("BucketBackend.exists: list_repo_files failed: %s", e)
            return False
        return path in files

    def list_dir(self, path: str) -> list[str]:
        _ensure_posix(path)
        if self._mount is not None:
            mp = self._mount / PurePosixPath(path)
            if mp.is_dir():
                return sorted(child.name for child in mp.iterdir())

        # Without a mount: enumerate via list_repo_files and synthesize a
        # one-level listing.
        try:
            api = self._hf_api()
            files = api.list_repo_files(
                repo_id=self._repo_id, repo_type=self._repo_type
            )
        except Exception as e:
            logger.warning("BucketBackend.list_dir: list_repo_files failed: %s", e)
            return []
        prefix = path.rstrip("/") + "/"
        names: set[str] = set()
        for f in files:
            if not f.startswith(prefix):
                continue
            tail = f[len(prefix) :]
            if not tail:
                continue
            names.add(tail.split("/", 1)[0])
        return sorted(names)

    def copy(self, src: str, dst: str) -> None:
        # Without server-side copy via HfApi, the supported path is
        # read-then-upload. For directory copies, callers iterate.
        data = self.read_bytes(src)
        self.write_bytes_atomic(dst, data)

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
            from huggingface_hub import HfApi  # type: ignore[import-not-found]

            api = self._hf_api()
            api.delete_file(
                path_in_repo=path,
                repo_id=self._repo_id,
                repo_type=self._repo_type,
                token=self._token,
                commit_message=f"delete {path}",
            )
        except Exception as e:
            # delete_file errors on non-existent paths — log and continue
            logger.debug("BucketBackend.delete %s: %s", path, e)


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
    - ``INSPECTOR_FORCE_FLUSH_ON_SAVE`` — ``1`` (default) | ``0``
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
            repo_id = os.environ.get(
                "INSPECTOR_BUCKET_REPO", "hetchyy/quranic-inspector-bucket-dev"
            )
            mount = os.environ.get("INSPECTOR_BUCKET_MOUNT") or None
            force_flush = os.environ.get("INSPECTOR_FORCE_FLUSH_ON_SAVE", "1") == "1"
            backend = BucketBackend(
                repo_id=repo_id,
                mount=mount,
                force_flush_on_write=force_flush,
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
