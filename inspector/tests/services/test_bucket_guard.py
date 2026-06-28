"""Tests for the local prod-bucket safety guard in ``services/storage/hf_bucket``.

The SQLite substrate syncs full-file, so a single stray write from a
local/non-deployed process clobbers production state. ``resolve_bucket_repo``
defaults every non-deployed process to the dev bucket and refuses the prod
bucket unless explicitly acknowledged. Deployed Spaces (behind the proxy) are
exempt.
"""

from __future__ import annotations

from typing import cast

import pytest

from services.storage.hf_bucket import (
    DEV_BUCKET_REPO,
    PROD_BUCKET_REPO,
    ProdBucketRefused,
    ReadOnlyBackend,
    StorageBackend,
    StorageReadOnly,
    get_backend,
    reset_backend,
    resolve_bucket_repo,
)

# Every mutating method the read-only wrapper must refuse.
_BLOCKED_WRITES = (
    "write_bytes_atomic",
    "write_json_atomic",
    "append_jsonl",
    "write_bytes_direct",
    "copy",
    "move",
    "delete",
)


class _RecordingBackend:
    """Minimal stand-in: reads return a sentinel, writes record + return."""

    def __init__(self) -> None:
        self.writes: list[str] = []

    def read_bytes(self, path: str) -> bytes:
        return b"read:" + path.encode()

    def read_bytes_direct(self, path: str) -> bytes:
        return b"direct"

    def exists(self, path: str) -> bool:
        return True

    def write_bytes_atomic(self, path, data):
        self.writes.append("write_bytes_atomic")

    def write_json_atomic(self, path, obj):
        self.writes.append("write_json_atomic")

    def append_jsonl(self, path, record):
        self.writes.append("append_jsonl")

    def write_bytes_direct(self, path, data):
        self.writes.append("write_bytes_direct")

    def copy(self, src, dst):
        self.writes.append("copy")

    def move(self, src, dst):
        self.writes.append("move")

    def delete(self, path):
        self.writes.append("delete")


def _clear(monkeypatch):
    for var in (
        "INSPECTOR_BUCKET_REPO",
        "INSPECTOR_BEHIND_PROXY",
        "INSPECTOR_ALLOW_PROD_BUCKET",
    ):
        monkeypatch.delenv(var, raising=False)


def test_defaults_to_dev_when_unset(monkeypatch):
    _clear(monkeypatch)
    assert resolve_bucket_repo() == DEV_BUCKET_REPO


def test_blank_env_falls_back_to_dev(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BUCKET_REPO", "   ")
    assert resolve_bucket_repo() == DEV_BUCKET_REPO


def test_explicit_dev_passes_through(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BUCKET_REPO", DEV_BUCKET_REPO)
    assert resolve_bucket_repo() == DEV_BUCKET_REPO


def test_arbitrary_personal_bucket_passes_through(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BUCKET_REPO", "alice/quranic-inspector-alice")
    assert resolve_bucket_repo() == "alice/quranic-inspector-alice"


def test_prod_refused_locally(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BUCKET_REPO", PROD_BUCKET_REPO)
    with pytest.raises(ProdBucketRefused):
        resolve_bucket_repo()


def test_prod_allowed_with_optin(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BUCKET_REPO", PROD_BUCKET_REPO)
    monkeypatch.setenv("INSPECTOR_ALLOW_PROD_BUCKET", "1")
    assert resolve_bucket_repo() == PROD_BUCKET_REPO


def test_prod_allowed_when_deployed(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BUCKET_REPO", PROD_BUCKET_REPO)
    monkeypatch.setenv("INSPECTOR_BEHIND_PROXY", "1")
    assert resolve_bucket_repo() == PROD_BUCKET_REPO


# --- read-only wrapper (INSPECTOR_READ_ONLY=1) -------------------------------


def test_readonly_backend_forwards_reads():
    inner = _RecordingBackend()
    ro = ReadOnlyBackend(cast(StorageBackend, inner))
    assert ro.read_bytes("x") == b"read:x"
    assert ro.read_bytes_direct("x") == b"direct"
    assert ro.exists("x") is True


@pytest.mark.parametrize("method", _BLOCKED_WRITES)
def test_readonly_backend_refuses_every_write(method):
    inner = _RecordingBackend()
    ro = ReadOnlyBackend(cast(StorageBackend, inner))
    with pytest.raises(StorageReadOnly):
        getattr(ro, method)("a", "b")
    assert inner.writes == []  # the inner backend was never reached


def test_get_backend_wraps_when_read_only(monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTOR_READ_ONLY", "1")
    reset_backend()
    try:
        assert isinstance(get_backend(), ReadOnlyBackend)
    finally:
        reset_backend()


def test_get_backend_unwrapped_without_read_only(monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.delenv("INSPECTOR_READ_ONLY", raising=False)
    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    reset_backend()
    try:
        assert not isinstance(get_backend(), ReadOnlyBackend)
    finally:
        reset_backend()
