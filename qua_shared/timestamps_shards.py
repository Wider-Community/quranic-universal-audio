"""Timestamp shard builders and deterministic Brotli serialization."""

from __future__ import annotations

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


def brotli_shard(shard_doc: dict) -> bytes:
    """Serialize and Brotli-compress a shard deterministically at quality 6."""
    import brotli
    import orjson

    payload = orjson.dumps(shard_doc)
    return brotli.compress(payload, quality=6, mode=brotli.MODE_TEXT)


def sha256_hex(b: bytes) -> str:
    """SHA-256 hex digest of `b`. Used by the manifest's shard_hashes index."""
    return hashlib.sha256(b).hexdigest()
