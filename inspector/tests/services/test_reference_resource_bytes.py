"""``_build_resource_bytes`` must serve a resource shipped only as ``.json.gz``.

Deployed Spaces ship ``qpc_hafs.json`` pre-gzipped (>10 MB → HF auto-LFS, and
the Space build doesn't smudge LFS) so only the ``.json.gz`` sibling exists in
the container. The reader previously keyed off the uncompressed path alone and
silently skipped the missing file, so ``/api/ts/resource/qpc_hafs`` served
nothing — the Timestamps text strip + Analysis tab went blank in prod while the
waveform (resource-independent) still rendered. These tests pin the ``.gz``
fallback so that regression can't return.
"""

from __future__ import annotations

import gzip

from services.reference import timestamps as ts_manifest


def test_reads_uncompressed_when_present(tmp_path, monkeypatch):
    p = tmp_path / "res.json"
    p.write_bytes(b'{"k": "v"}')
    monkeypatch.setattr(ts_manifest, "_RESOURCE_PATHS", {"res": p})

    out = ts_manifest._build_resource_bytes()

    assert gzip.decompress(out["res"]) == b'{"k": "v"}'


def test_falls_back_to_gz_when_only_gz_present(tmp_path, monkeypatch):
    """Container ships only the ``.gz`` — the reader must gunzip it."""
    raw = b'{"qpc": "text"}'
    gz = tmp_path / "res.json.gz"
    gz.write_bytes(gzip.compress(raw, mtime=0))
    # Point at the uncompressed name that does NOT exist on disk.
    monkeypatch.setattr(ts_manifest, "_RESOURCE_PATHS", {"res": tmp_path / "res.json"})

    out = ts_manifest._build_resource_bytes()

    assert "res" in out
    assert gzip.decompress(out["res"]) == raw


def test_skips_when_neither_variant_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(ts_manifest, "_RESOURCE_PATHS", {"res": tmp_path / "missing.json"})

    assert ts_manifest._build_resource_bytes() == {}
