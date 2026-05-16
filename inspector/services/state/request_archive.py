"""Terminal-state archives for user requests — denormalized per-slug index.

Triple-store sibling of ``pending_requests``: when a request leaves the
``requests/pending.json`` file (because the alignment pipeline produced
files, or because an admin sent it back / discarded it), the entry is
appended into one of three archive files at the same level:

- ``requests/completed.json``  — accepted via ``reciter.alignment_completed``
- ``requests/returned.json``   — soft-rejected (``request_rejected_soft``)
- ``requests/discarded.json``  — hard-rejected (``request_rejected_hard``)

Each archive file is ``ArchivedRequestsFile`` — ``by_slug: dict[slug, list[ArchivedRequest]]``.
List-of-entries rather than scalar because a slug can ride the
request→return→re-request loop multiple times. New entries append to the
end (chronological).

The audit log (``audit/<YYYY>-<MM>.jsonl``) is still the authoritative
record. These archives are a fast per-slug index so admin / requester /
forensic surfaces can answer "show this slug's request history" without
scanning month-wide JSONL partitions.

Same hydrate / snapshot / atomic-write pattern as the other six bucket
stores. Single-worker invariant applies — the in-memory dict is the
authoritative read path between writes.
"""

from __future__ import annotations

import enum
import logging
import threading

from scripts.lib.schemas import ArchivedRequest, ArchivedRequestsFile

from services.storage import storage_paths
from services.storage.hf_bucket import StorageNotFound, get_backend

logger = logging.getLogger(__name__)


class ArchiveKind(str, enum.Enum):
    COMPLETED = "completed"
    RETURNED = "returned"
    DISCARDED = "discarded"


_PATH_FOR_KIND = {
    ArchiveKind.COMPLETED: storage_paths.completed_requests_path,
    ArchiveKind.RETURNED: storage_paths.returned_requests_path,
    ArchiveKind.DISCARDED: storage_paths.discarded_requests_path,
}


_stores: dict[ArchiveKind, ArchivedRequestsFile] = {
    kind: ArchivedRequestsFile() for kind in ArchiveKind
}
_lock = threading.Lock()


def hydrate() -> None:
    """Load (or initialize) all three archive files. Idempotent."""
    global _stores
    backend = get_backend()
    loaded: dict[ArchiveKind, ArchivedRequestsFile] = {}
    for kind, path_fn in _PATH_FOR_KIND.items():
        path = path_fn()
        try:
            raw = backend.read_json(path)
            loaded[kind] = ArchivedRequestsFile.model_validate(raw)
        except StorageNotFound:
            logger.info(
                "request_archive: %s missing on bucket; initializing empty store",
                path,
            )
            loaded[kind] = ArchivedRequestsFile()
    with _lock:
        _stores = loaded


def snapshot(kind: ArchiveKind) -> ArchivedRequestsFile:
    """Return a deep copy of the archive store for ``kind``."""
    with _lock:
        return _stores[kind].model_copy(deep=True)


def get_for_slug(slug: str, kind: ArchiveKind) -> list[ArchivedRequest]:
    """Return all archived entries for ``slug`` in ``kind`` (chronological).

    Empty list if no entries. Deep-copied so callers can mutate without
    touching the in-memory store.
    """
    with _lock:
        entries = _stores[kind].by_slug.get(slug, [])
        return [e.model_copy(deep=True) for e in entries]


def append(kind: ArchiveKind, entry: ArchivedRequest) -> None:
    """Append ``entry`` to the archive for ``kind`` and persist atomically.

    Entries within a slug are stored in append order. Single-worker
    invariant means readers between this call and persist see the
    in-memory update through ``snapshot`` / ``get_for_slug``.
    """
    global _stores
    backend = get_backend()
    with _lock:
        new_store = _stores[kind].model_copy(deep=True)
        slug = entry.slug
        new_store.by_slug.setdefault(slug, []).append(entry)
        backend.write_json_atomic(
            _PATH_FOR_KIND[kind](), new_store.model_dump(mode="json"),
        )
        new_stores = dict(_stores)
        new_stores[kind] = new_store
        _stores = new_stores


__all__ = [
    "ArchiveKind",
    "append",
    "get_for_slug",
    "hydrate",
    "snapshot",
]
