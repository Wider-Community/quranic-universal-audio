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
from .admin_permissions import (
    AdminCapabilityRow,
    AdminCapabilityTierState,
    AdminPermissionGroup,
    AdminPermissionsResponse,
)
from .admin_requests import (
    AdminRequestCounts,
    AdminRequestRow,
    AdminRequestsResponse,
    RequestChange,
)
from .admin_reviews import (
    AdminReviewClaimHistoryEntry,
    AdminReviewDetail,
    AdminReviewOpenClaim,
    AdminReviewRow,
    AdminReviewTransition,
    AdminReviewValidation,
    AdminReviewsResponse,
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
from .capabilities import (
    CAPABILITIES,
    CAPABILITIES_BY_ID,
    GROUP_ORDER,
    MANAGE_PERMISSIONS,
    TIERS,
    Capability,
)
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
from .mark_ready import (
    BLOCKING_COUNT_KEYS,
    ChecklistKey,
    MarkReadyChecklist,
    MarkReadyRequest,
    MarkReadySubmission,
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
from .ts_job_record import TsJobRecord, TsJobSettings

__all__ = [
    "ActivityState",
    "Actor",
    "AdminCapabilityRow",
    "AdminCapabilityTierState",
    "AdminPermissionGroup",
    "AdminPermissionsResponse",
    "AdminActiveClaim",
    "AdminActivityEvent",
    "AdminClaimEvent",
    "AdminRequestCounts",
    "AdminRequestEvent",
    "AdminRequestRow",
    "AdminRequestsResponse",
    "AdminReviewClaimHistoryEntry",
    "AdminReviewDetail",
    "AdminReviewOpenClaim",
    "AdminReviewRow",
    "AdminReviewTransition",
    "AdminReviewValidation",
    "AdminReviewsResponse",
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
    "CAPABILITIES",
    "CAPABILITIES_BY_ID",
    "Capability",
    "GROUP_ORDER",
    "MANAGE_PERMISSIONS",
    "TIERS",
    "Channel",
    "ChapterEntry",
    "Delivery",
    "DetailedDocument",
    "DetailedEntry",
    "DetailedMeta",
    "DetailedSegment",
    "EditHistoryBatch",
    "EditOperation",
    "BLOCKING_COUNT_KEYS",
    "ChecklistKey",
    "IntakeAttestations",
    "IntakeSource",
    "IntakeSubmission",
    "IntakeValidation",
    "MarkReadyChecklist",
    "MarkReadyRequest",
    "MarkReadySubmission",
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
    "TsJobRecord",
    "TsJobSettings",
    "Visibility",
    "VisitorDayStat",
    "Vocab",
    "parse_detailed_segment",
    "parse_edit_history_line",
    "parse_peaks_record",
]
