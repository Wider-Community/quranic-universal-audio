"""Per-mode data directory resolver.

Wraps the storage backend with semantic helpers — callers pass a slug
and get back the bytes/dict they need. Routes/services use this instead
of touching ``RECITATION_SEGMENTS_PATH`` (legacy filesystem constant, kept
only for tests on ``FilesystemBackend``).

The ``kind`` (``wip`` vs ``published``) is consulted from the state
service for any caller that doesn't already know — most don't, because
the lifecycle decision belongs to the state machine, not to data IO.

"""

from __future__ import annotations

from typing import Iterator, Literal

from . import storage_paths
from .hf_bucket import StorageNotFound, get_backend

WipOrPublished = Literal["wip", "published"]


def kind_for(slug: str) -> WipOrPublished:
    """Return ``"wip"`` or ``"published"`` for ``slug``.

    Delegates to ``state.kind_for(slug)``; falls back to ``"wip"`` when the
    slug isn't tracked yet (e.g. mid-cutover, or test fixtures bypassing
    state seeding).
    """
    # Lazy import to avoid a circular at module load (``state.py`` imports
    # ``storage_paths`` and ``hf_bucket`` from this package).
    from services.state import state as state_service

    k = state_service.kind_for(slug)
    return k if k in ("wip", "published") else "wip"


# ---- path helpers (no I/O) ----


def list_slugs(kind: WipOrPublished) -> list[str]:
    """Return all slug subdirectories under ``wip/`` or ``published/``."""
    return get_backend().list_dir(kind)


def reciter_file_path(slug: str, kind: WipOrPublished, name: str) -> str:
    return storage_paths.reciter_file(slug, kind, name)


def segments_path(slug: str, kind: WipOrPublished | None = None) -> str:
    return storage_paths.segments_path(slug, kind or kind_for(slug))


def detailed_path(slug: str, kind: WipOrPublished | None = None) -> str:
    return storage_paths.detailed_path(slug, kind or kind_for(slug))


def edit_history_path(slug: str, kind: WipOrPublished | None = None) -> str:
    return storage_paths.edit_history_path(slug, kind or kind_for(slug))


def edit_history_peaks_path(
    slug: str, kind: WipOrPublished | None = None
) -> str:
    return storage_paths.edit_history_peaks_path(slug, kind or kind_for(slug))


def low_confidence_path(slug: str, kind: WipOrPublished | None = None) -> str:
    return storage_paths.low_confidence_path(slug, kind or kind_for(slug))


def auto_split_path(slug: str, kind: WipOrPublished | None = None) -> str:
    return storage_paths.auto_split_path(slug, kind or kind_for(slug))


def pipeline_meta_path(slug: str, kind: WipOrPublished | None = None) -> str:
    return storage_paths.pipeline_meta_path(slug, kind or kind_for(slug))


def read_pipeline_meta_doc(slug: str) -> dict | None:
    """Return the parsed ``pipeline_meta.json`` doc, or ``None`` if absent."""
    try:
        return get_backend().read_json(pipeline_meta_path(slug))  # type: ignore[return-value]
    except StorageNotFound:
        return None


def write_pipeline_meta_doc(slug: str, doc: dict) -> None:
    get_backend().write_json_atomic(pipeline_meta_path(slug), doc)


def has_reciter(slug: str, kind: WipOrPublished | None = None) -> bool:
    """True if the reciter directory exists under the given subtree."""
    return get_backend().exists(storage_paths.reciter_dir(slug, kind or kind_for(slug)))


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


# ---- timestamps (published-only — wip reciters have no TS yet) ----


def read_timestamps_chapter(slug: str, chapter: int) -> bytes | None:
    """Return raw ``timestamps/<chapter>.json`` bytes, or ``None`` if absent.

    Reads from ``<bucket>/published/<slug>/timestamps/<chapter>.json``.
    Timestamps live only under ``published/`` — wip reciters have none.
    """
    try:
        return get_backend().read_bytes(
            storage_paths.published_timestamps_path(slug, chapter)
        )
    except StorageNotFound:
        return None


