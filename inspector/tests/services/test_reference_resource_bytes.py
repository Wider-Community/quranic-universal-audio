"""qpc_hafs byte resolution must survive the deployed Space's LFS pointer.

HF auto-LFS-promotes ``*.gz`` by extension and the Space build can't smudge
LFS, so the image's ``data/qpc_hafs.json.gz`` is a ``version https://...``
pointer there — ``gzip.decompress`` on it raises and previously 500'd the TS
manifest (blanking the text strip + Analysis tab). ``static_refs.load_qpc_bytes``
must fall back to the bucket, and ``_build_resource_bytes`` must degrade (skip)
rather than raise. These tests pin both so the regression can't return.
"""

from __future__ import annotations

import gzip

from services.storage import static_refs
from services.reference import timestamps as ts_manifest


class _FakeBackend:
    def __init__(self, files: dict[str, bytes]):
        self._files = files

    def read_bytes(self, path: str) -> bytes:
        try:
            return self._files[path]
        except KeyError as e:
            raise FileNotFoundError(path) from e


def test_prefers_local_uncompressed(tmp_path, monkeypatch):
    p = tmp_path / "qpc_hafs.json"
    p.write_bytes(b'{"1:1:1": "x"}')
    monkeypatch.setattr(static_refs, "QPC_HAFS_PATH", p)

    assert static_refs.load_qpc_bytes() == b'{"1:1:1": "x"}'


def test_local_gz_when_no_uncompressed(tmp_path, monkeypatch):
    """CI / job staging ships a real ``.gz`` and no uncompressed source."""
    raw = b'{"1:1:1": "gz"}'
    (tmp_path / "qpc_hafs.json.gz").write_bytes(gzip.compress(raw, mtime=0))
    monkeypatch.setattr(static_refs, "QPC_HAFS_PATH", tmp_path / "qpc_hafs.json")

    assert static_refs.load_qpc_bytes() == raw


def test_lfs_pointer_gz_falls_back_to_bucket(tmp_path, monkeypatch):
    """The deployed-Space case: local ``.gz`` is an LFS pointer (not gzip), so
    the real bytes must come from the bucket."""
    raw = b'{"1:1:1": "bucket"}'
    # Local .gz is a git-lfs pointer, not gzip — gzip.decompress would raise.
    (tmp_path / "qpc_hafs.json.gz").write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:deadbeef\nsize 1452433\n"
    )
    monkeypatch.setattr(static_refs, "QPC_HAFS_PATH", tmp_path / "qpc_hafs.json")
    fake = _FakeBackend({static_refs.QPC_BUCKET_PATH: gzip.compress(raw, mtime=0)})
    monkeypatch.setattr(static_refs.data_dir, "get_backend", lambda: fake)

    assert static_refs.load_qpc_bytes() == raw


def test_returns_empty_when_unavailable_everywhere(tmp_path, monkeypatch):
    monkeypatch.setattr(static_refs, "QPC_HAFS_PATH", tmp_path / "qpc_hafs.json")
    monkeypatch.setattr(static_refs.data_dir, "get_backend", lambda: _FakeBackend({}))

    assert static_refs.load_qpc_bytes() == b""


def test_build_resource_bytes_degrades_without_qpc(monkeypatch):
    """A missing qpc resource is skipped, not raised — the manifest must build."""
    monkeypatch.setattr(ts_manifest.static_refs, "load_qpc_bytes", lambda: b"")

    out = ts_manifest._build_resource_bytes()

    assert "qpc_hafs" not in out  # skipped, no crash


def test_build_resource_bytes_gzips_qpc(monkeypatch):
    monkeypatch.setattr(ts_manifest.static_refs, "load_qpc_bytes", lambda: b'{"1:1:1": "y"}')

    out = ts_manifest._build_resource_bytes()

    assert gzip.decompress(out["qpc_hafs"]) == b'{"1:1:1": "y"}'
