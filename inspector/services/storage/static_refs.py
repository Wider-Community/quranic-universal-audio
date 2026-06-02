"""Static reference-data byte loader (qpc_hafs).

``qpc_hafs`` ships in the image as ``data/qpc_hafs.json[.gz]``, but the deployed
HF Space build can't smudge LFS and HF auto-LFS-promotes ``*.gz`` **by
extension** (a 9.98 MB ``*.json`` ships fine; a 1.45 MB ``*.gz`` becomes a
~133-byte pointer). So the image's ``.gz`` is an LFS pointer on the Space —
``gzip.decompress`` on it raises ``BadGzipFile`` and blanks the Timestamps text
strip + Analysis tab (and the Segments-side qpc reads).

This loader resolves the *real* uncompressed bytes across every runtime:
local uncompressed (dev checkout) → local valid gzip (CI / job staging) →
bucket ``reference/qpc_hafs.json.gz`` (deployed Space, where only the bucket
carries real bytes). Both callers — ``data_loader.load_qpc`` (parsed dict) and
``services/reference/timestamps`` (gzipped resource bytes) — cache their own
derived result, so this stays uncached and is hit at most once per cache cycle.
"""

from __future__ import annotations

import gzip
import logging

from config import QPC_HAFS_PATH
from services.storage import data_dir

log = logging.getLogger("inspector")

# Bucket location of the canonical gzipped qpc_hafs (Xet-backed — no LFS
# pointer problem, unlike the image-shipped ``.gz``). Synced to dev + prod
# buckets out of band; see scripts note in the deploy docs.
QPC_BUCKET_PATH = "reference/qpc_hafs.json.gz"


def _gunzip_or_none(raw: bytes) -> bytes | None:
    """Decompress gzip bytes, or ``None`` if ``raw`` isn't valid gzip (e.g. an
    LFS pointer ``version https://...`` masquerading as the file)."""
    try:
        return gzip.decompress(raw)
    except (OSError, gzip.BadGzipFile):
        return None


def load_qpc_bytes() -> bytes:
    """Uncompressed ``qpc_hafs.json`` bytes; ``b""`` if unavailable everywhere.

    Never raises — a hot, cached endpoint (the TS manifest) builds on top of
    this, so an unreachable resource degrades to an empty text layer rather
    than a 500.
    """
    # 1. Local uncompressed — the dev checkout's source of truth.
    if QPC_HAFS_PATH.exists():
        return QPC_HAFS_PATH.read_bytes()

    # 2. Local gzip — real bytes in CI / HF-Job staging; an LFS pointer on the
    #    deployed Space (skip it and fall through to the bucket).
    gz = QPC_HAFS_PATH.with_suffix(QPC_HAFS_PATH.suffix + ".gz")
    if gz.exists():
        dec = _gunzip_or_none(gz.read_bytes())
        if dec is not None:
            return dec
        log.warning(
            "qpc_hafs local %s is not gzip (LFS pointer?) — falling back to bucket",
            gz.name,
        )

    # 3. Bucket — the only place with real bytes on the deployed Space.
    try:
        raw = data_dir.get_backend().read_bytes(QPC_BUCKET_PATH)
    except Exception as e:  # noqa: BLE001 — degrade, never 500 the manifest
        log.error("qpc_hafs unavailable from bucket %s: %s", QPC_BUCKET_PATH, e)
        return b""
    dec = _gunzip_or_none(raw)
    if dec is None:
        log.error("bucket %s is not valid gzip", QPC_BUCKET_PATH)
        return b""
    return dec
