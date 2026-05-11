"""Cross-consumer pydantic schemas for Inspector v2 bucket-resident JSON files.

Lives at ``scripts/lib/schemas/`` so Inspector backend, GH Actions scripts,
the training pipeline, and the dataset builder all read the same canonical
definitions. See docs/reference/reciter-catalog.md and
docs/planning/inspector-deploy/v2/inspector-state-management.md for the
authoritative spec.
"""

from __future__ import annotations

from .access import Member, Role, RolesFile
from .audit import Actor, AuditRecord
from .catalog import (
    AudioCategory,
    Channel,
    Delivery,
    ReciterCatalog,
    ReciterEntry,
    RecordingContext,
    Riwayah,
    Source,
    Style,
    Vocab,
)
from .edit_history import EditHistoryBatch, parse_edit_history_line
from .state import (
    ReciterRow,
    ReciterState,
    ReciterStateFile,
    RevisionContext,
    Visibility,
)

__all__ = [
    "Actor",
    "AudioCategory",
    "AuditRecord",
    "Channel",
    "Delivery",
    "EditHistoryBatch",
    "Member",
    "ReciterCatalog",
    "ReciterEntry",
    "ReciterRow",
    "ReciterState",
    "ReciterStateFile",
    "RecordingContext",
    "RevisionContext",
    "Riwayah",
    "Role",
    "RolesFile",
    "Source",
    "Style",
    "Visibility",
    "Vocab",
    "parse_edit_history_line",
]
