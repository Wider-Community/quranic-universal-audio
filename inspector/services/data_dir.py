"""Per-mode data directory resolver.

Wraps the storage backend with semantic helpers — callers pass a slug + kind
and get back the on-bucket path they need. Routes/services use this instead
of touching ``RECITATION_SEGMENTS_PATH`` (legacy path on the local
filesystem; kept only as a fallback for ``FilesystemBackend`` tests).

Phase 1: no ``auto`` kind. Every call site declares whether it wants the
``wip`` or ``published`` subtree. The state service surfaces a helper
(``inspector.services.state.kind_for(slug)``) for routes that genuinely
don't know until runtime.
"""

from __future__ import annotations

from typing import Literal

from . import storage_paths
from .hf_bucket import get_backend

WipOrPublished = Literal["wip", "published"]


def list_slugs(kind: WipOrPublished) -> list[str]:
    """Return all slug subdirectories under ``wip/`` or ``published/``."""
    return get_backend().list_dir(kind)


def reciter_file_path(slug: str, kind: WipOrPublished, name: str) -> str:
    return storage_paths.reciter_file(slug, kind, name)


def segments_path(slug: str, kind: WipOrPublished) -> str:
    return storage_paths.segments_path(slug, kind)


def detailed_path(slug: str, kind: WipOrPublished) -> str:
    return storage_paths.detailed_path(slug, kind)


def edit_history_path(slug: str, kind: WipOrPublished) -> str:
    return storage_paths.edit_history_path(slug, kind)


def edit_history_peaks_path(slug: str, kind: WipOrPublished) -> str:
    return storage_paths.edit_history_peaks_path(slug, kind)


def low_confidence_path(slug: str, kind: WipOrPublished) -> str:
    return storage_paths.low_confidence_path(slug, kind)


def has_reciter(slug: str, kind: WipOrPublished) -> bool:
    """True if the reciter directory exists under the given subtree."""
    return get_backend().exists(storage_paths.reciter_dir(slug, kind))
