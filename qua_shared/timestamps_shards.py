"""Timestamp shard builders and deterministic gzip serialization."""

from __future__ import annotations

import gzip
import hashlib

MANIFEST_SCHEMA_VERSION = 1
TIMESTAMP_SHARD_SCHEMA_VERSION = 12


def build_timestamp_shards(
    v2_doc: dict,
    *,
    audio_category: str,
    src_meta: dict | None = None,
) -> dict[int, dict]:
    """Build strict native v12 shards through the staged SDK."""
    from qua_sdk.integrations.shards import build_native_shards

    return build_native_shards(
        v2_doc,
        audio_category=audio_category,
        src_meta=src_meta,
    )


def gzip_shard(shard_doc: dict) -> bytes:
    """Serialize and gzip a shard document deterministically.

    Uses orjson for speed/UTF-8 fidelity. `mtime=0` on the gzip header so
    re-running the build with unchanged input produces byte-identical
    output (load-bearing for the hash-diff cache).
    """
    import orjson

    payload = orjson.dumps(shard_doc)
    return gzip.compress(payload, compresslevel=6, mtime=0)


def sha256_hex(b: bytes) -> str:
    """SHA-256 hex digest of `b`. Used by the manifest's shard_hashes index."""
    return hashlib.sha256(b).hexdigest()
