"""Cross-consumer pydantic schemas for Inspector v2 bucket-resident JSON files.

Lives at ``scripts/lib/schemas/`` so Inspector backend, GH Actions scripts,
the training pipeline, and the dataset builder all read the same canonical
definitions. See docs/reference/catalog.md and
docs/planning/inspector-deploy/v2/inspector-state-management.md for the
authoritative spec.
"""

from __future__ import annotations

from .access import Member, Role, RolesFile
from .activity_state import ActivityState
from .admin_requests import (
    AdminRequestCounts,
    AdminRequestRow,
    AdminRequestsResponse,
    RequestChange,
)
from .admin_users import (
    AdminActiveClaim,
    AdminActivityEvent,
    AdminClaimEvent,
    AdminRequestEvent,
    AdminRoleEvent,
    AdminUserDetail,
    AdminUserRow,
    AdminUserStats,
    AdminUsersResponse,
    AdminUsersSummary,
    AdminVisitorStats,
    VisitorDayStat,
)
from .audit import Actor, AuditRecord
from .catalog import (
    AudioCategory,
    AudioManifestSidecar,
    Channel,
    ChapterEntry,
    Delivery,
    ReciterCatalog,
    ReciterEntry,
    RecordingContext,
    Riwayah,
    SidecarMeta,
    Source,
    Style,
    Vocab,
)
from .edit_history import EditHistoryBatch, EditOperation, parse_edit_history_line
from .intake_requests import (
    IntakeAttestations,
    IntakeSource,
    IntakeSubmission,
    IntakeValidation,
    ProbeResponse,
    ProbeResult,
    SourceLink,
)
from .peaks_history import PeaksRecord, parse_peaks_record
from .pipeline_meta import PipelineMeta
from .pending_requests import (
    ArchivedRequest,
    ArchivedRequestsFile,
    PendingRequest,
    PendingRequestsFile,
    ProposedEdits,
)
from .segment import (
    DetailedDocument,
    DetailedEntry,
    DetailedMeta,
    DetailedSegment,
    parse_detailed_segment,
)
from .state import (
    ReciterRow,
    ReciterState,
    ReciterStateFile,
    RevisionContext,
    Visibility,
)

__all__ = [
    "ActivityState",
    "Actor",
    "AdminActiveClaim",
    "AdminActivityEvent",
    "AdminClaimEvent",
    "AdminRequestCounts",
    "AdminRequestEvent",
    "AdminRequestRow",
    "AdminRequestsResponse",
    "AdminRoleEvent",
    "AdminUserDetail",
    "AdminUserRow",
    "AdminUserStats",
    "AdminUsersResponse",
    "AdminUsersSummary",
    "AdminVisitorStats",
    "ArchivedRequest",
    "RequestChange",
    "ArchivedRequestsFile",
    "AudioCategory",
    "AudioManifestSidecar",
    "AuditRecord",
    "Channel",
    "ChapterEntry",
    "Delivery",
    "DetailedDocument",
    "DetailedEntry",
    "DetailedMeta",
    "DetailedSegment",
    "EditHistoryBatch",
    "EditOperation",
    "IntakeAttestations",
    "IntakeSource",
    "IntakeSubmission",
    "IntakeValidation",
    "Member",
    "PeaksRecord",
    "PendingRequest",
    "PendingRequestsFile",
    "PipelineMeta",
    "ProbeResponse",
    "ProbeResult",
    "ProposedEdits",
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
    "SidecarMeta",
    "Source",
    "SourceLink",
    "Style",
    "Visibility",
    "VisitorDayStat",
    "Vocab",
    "parse_detailed_segment",
    "parse_edit_history_line",
    "parse_peaks_record",
]
