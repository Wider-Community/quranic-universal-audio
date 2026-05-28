"""Typed repository errors.

The service layer maps these to its own error contract (e.g. catalog's
``InvalidCatalogChange``) so callers keep their existing exception types while
the repos raise something more specific than a raw ``sqlite3.IntegrityError``.
"""

from __future__ import annotations


class RepoError(Exception):
    """Base for repository-layer errors."""


class Duplicate(RepoError):
    """A unique key (PK / partial-unique) would be violated."""


class NotFound(RepoError):
    """A required row does not exist."""
