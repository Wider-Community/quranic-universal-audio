"""FE-facing schema re-exports for the TypeScript codegen pipeline.

This module exists solely to give ``pydantic-to-typescript`` a narrow
entry point that avoids the catalog / state / audit nested-model graph
(which has forward refs the codegen can't resolve in one pass).

The FE only consumes a few of our Pydantic models — the per-reciter
artefact shapes (`detailed.json`, `edit_history.jsonl`,
`edit_history_peaks.jsonl`). Everything else stays internal to the
backend.

Re-generate the FE types via::

    python scripts/codegen/regen_fe_types.py

The generated output lands at
``inspector/frontend/src/lib/types/generated/schemas.ts`` and is
committed to git so CI can ``git diff --exit-code`` it.
"""

from __future__ import annotations

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
    AdminReviewsResponse,
    AdminReviewTransition,
    AdminReviewValidation,
)
from .admin_users import (
    AdminActiveClaim,
    AdminActivityEvent,
    AdminClaimEvent,
    AdminRequestEvent,
    AdminRoleEvent,
    AdminUserDetail,
    AdminUserRow,
    AdminUsersResponse,
    AdminUsersSummary,
    AdminUserStats,
    AdminVisitorStats,
    VisitorDayStat,
)
from .edit_history import EditHistoryBatch, EditOperation
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
    MarkReadyChecklist,
    MarkReadyRequest,
    MarkReadySubmission,
)
from .peaks_history import PeaksRecord
from .segment import (
    DetailedDocument,
    DetailedEntry,
    DetailedMeta,
    DetailedSegment,
)
from .tajweed import BridgeInfo, TajweedBridgesResponse
from .ts_job_record import TsJobRecord, TsJobSettings
from .ts_validation import TsValidationDoc, TsValidationMeta, TsValidationVerse

__all__ = [
    "AdminActiveClaim",
    "AdminActivityEvent",
    "AdminCapabilityRow",
    "AdminCapabilityTierState",
    "AdminClaimEvent",
    "AdminPermissionGroup",
    "AdminPermissionsResponse",
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
    "BridgeInfo",
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
    "MarkReadyChecklist",
    "MarkReadyRequest",
    "MarkReadySubmission",
    "PeaksRecord",
    "ProbeResponse",
    "ProbeResult",
    "RequestChange",
    "SourceLink",
    "TajweedBridgesResponse",
    "TsJobRecord",
    "TsJobSettings",
    "TsValidationDoc",
    "TsValidationMeta",
    "TsValidationVerse",
    "VisitorDayStat",
]
