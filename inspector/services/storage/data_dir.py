"""Per-reciter data directory resolver.

Wraps the storage backend with semantic helpers — callers pass a slug
and get back the bytes/dict they need. Routes/services use this instead
of touching ``RECITATION_SEGMENTS_PATH`` (legacy filesystem constant, kept
only for tests on ``FilesystemBackend``).

All per-reciter content lives under a single ``reciters/<slug>/`` prefix;
lifecycle state is a DB attribute, not a folder choice, so these helpers
need no notion of ``wip`` vs ``published``.

"""

from __future__ import annotations

import gzip
from typing import Iterator

from . import storage_paths
from .hf_bucket import StorageNotFound, get_backend


# ---- path helpers (no I/O) ----


def list_slugs() -> list[str]:
    """Return all reciter slug subdirectories under ``reciters/``."""
    return get_backend().list_dir(storage_paths.RECITERS_PREFIX)


def reciter_file_path(slug: str, name: str) -> str:
    return storage_paths.reciter_file(slug, name)


def segments_path(slug: str) -> str:
    return storage_paths.segments_path(slug)


def detailed_path(slug: str) -> str:
    return storage_paths.detailed_path(slug)


def edit_history_path(slug: str) -> str:
    return storage_paths.edit_history_path(slug)


def edit_history_peaks_path(slug: str) -> str:
    return storage_paths.edit_history_peaks_path(slug)


def low_confidence_path(slug: str) -> str:
    return storage_paths.low_confidence_path(slug)


def auto_split_path(slug: str) -> str:
    return storage_paths.auto_split_path(slug)


def pipeline_meta_path(slug: str) -> str:
    return storage_paths.pipeline_meta_path(slug)


def read_pipeline_meta_doc(slug: str) -> dict | None:
    """Return the parsed ``pipeline_meta.json`` doc, or ``None`` if absent."""
    try:
        return get_backend().read_json(pipeline_meta_path(slug))  # type: ignore[return-value]
    except StorageNotFound:
        return None


def write_pipeline_meta_doc(slug: str, doc: dict) -> None:
    get_backend().write_json_atomic(pipeline_meta_path(slug), doc)


def has_reciter(slug: str) -> bool:
    """True if the reciter directory exists under ``reciters/``."""
    return get_backend().exists(storage_paths.reciter_dir(slug))


# ---- high-level read/write helpers (these hide the backend entirely) ----


def read_segments_doc(slug: str) -> dict | None:
    """Return the parsed ``segments.json`` doc, or ``None`` if absent."""
    try:
        return get_backend().read_json(segments_path(slug))  # type: ignore[return-value]
    except StorageNotFound:
        return None


def read_detailed_bytes(slug: str) -> bytes | None:
    """Return raw ``detailed.json`` bytes, or ``None`` if absent."""
    try:
        return get_backend().read_bytes(detailed_path(slug))
    except StorageNotFound:
        return None


def read_low_confidence_doc(slug: str) -> dict | None:
    try:
        return get_backend().read_json(low_confidence_path(slug))  # type: ignore[return-value]
    except StorageNotFound:
        return None


def read_auto_split_doc(slug: str) -> dict | None:
    """Return the parsed ``auto_split_v1.json`` doc, or ``None`` if absent."""
    try:
        return get_backend().read_json(auto_split_path(slug))  # type: ignore[return-value]
    except StorageNotFound:
        return None


def write_detailed_doc(slug: str, doc: dict) -> None:
    get_backend().write_json_atomic(detailed_path(slug), doc)


def write_segments_doc(slug: str, doc: dict) -> None:
    get_backend().write_json_atomic(segments_path(slug), doc)


def append_edit_history(slug: str, batch: dict) -> None:
    get_backend().append_jsonl(edit_history_path(slug), batch)


def append_peaks_history(slug: str, record: dict) -> None:
    get_backend().append_jsonl(edit_history_peaks_path(slug), record)


def iter_edit_history(slug: str) -> Iterator[dict]:
    yield from get_backend().iter_jsonl(edit_history_path(slug))


def iter_peaks_history(slug: str) -> Iterator[dict]:
    yield from get_backend().iter_jsonl(edit_history_peaks_path(slug))


# ---- timestamps (released reciters only — others have no TS yet) ----


def read_timestamps_chapter(slug: str, chapter: int) -> bytes | None:
    """Return decompressed timestamps-shard JSON bytes for a chapter, or ``None``.

    Reads the gzipped v2 shard ``timestamps/<chapter>.json.gz`` (the job's
    canonical output) and inflates it; the caller receives raw JSON bytes.
    The pre-v2 uncompressed ``.json`` shards of the 6 already-published
    reciters are migrated by re-running the job — there is no read-time
    fallback for them.
    """
    backend = get_backend()
    try:
        gz = backend.read_bytes(storage_paths.timestamps_path_gz(slug, chapter))
        return gzip.decompress(gz)
    except StorageNotFound:
        return None


