"""Request archives: thin read facade over the unified ``requests`` table.

Post-cutover the three archive files (``completed``/``returned``/``discarded``)
are just terminal ``status`` values on ``requests`` rows — written by
``repo_requests.resolve`` (called from ``pending_requests``), never by a
separate append here. This module keeps ``ArchiveKind`` + the per-slug/whole
read helpers so legacy/forensic read callers don't churn.
"""

from __future__ import annotations

import enum

from scripts.lib.schemas import ArchivedRequest, ArchivedRequestsFile

from services.db import repo_requests


class ArchiveKind(str, enum.Enum):
    COMPLETED = "completed"
    RETURNED = "returned"
    DISCARDED = "discarded"


def hydrate() -> None:
    """No-op under the SQLite substrate (DB is the source of truth)."""
    return None


def get_for_slug(slug: str, kind: ArchiveKind) -> list[ArchivedRequest]:
    """All archived entries for ``slug`` in ``kind`` (oldest→newest)."""
    return repo_requests.get_for_slug(kind.value, slug)


def snapshot(kind: ArchiveKind) -> ArchivedRequestsFile:
    """Reassemble the legacy ``by_slug`` archive view for ``kind``."""
    store = ArchivedRequestsFile()
    for entry in repo_requests.all_archived(kind.value):
        store.by_slug.setdefault(entry.slug, []).append(entry)
    return store


__all__ = [
    "ArchiveKind",
    "get_for_slug",
    "hydrate",
    "snapshot",
]
