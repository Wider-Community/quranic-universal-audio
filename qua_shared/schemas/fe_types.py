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

from .bucket.cell_vocab import CellRole, CellStatus
from .bucket.edit_history import EditHistoryBatch, EditOperation, EditOpPatch
from .bucket.jobs import JobMember, JobRecord, JobsListResponse
from .bucket.peaks_history import PeaksRecord
from .bucket.segment import (
    DetailedDocument,
    DetailedEntry,
    DetailedMeta,
    DetailedSegment,
    FlagFollowUp,
    SegmentFlag,
)
from .bucket.tajweed_vocab import TajweedRule
from .bucket.ts_job_record import TsJobRecord, TsJobSettings
from .bucket.ts_shard import TsShardCell, TsShardDoc, TsShardMeta, TsShardSegment, TsShardWord
from .bucket.ts_validation import TsValidationDoc, TsValidationMeta, TsValidationVerse
from .config.automation import (
    AutoGenTsConfig,
    AutomationConfig,
    AutomationResponse,
    AutomationStateRow,
    GhCutConfig,
    HfPublishConfig,
    StaleMetadataConfig,
    StaleTsRegenConfig,
    TsGenerationDefaults,
)
from .wire._envelopes import ErrorEnvelope, OkAck
from .wire.admin_permissions import (
    AdminCapabilityRow,
    AdminCapabilityTierState,
    AdminPermissionGroup,
    AdminPermissionsResponse,
)
from .wire.admin_requests import (
    AdminRequestCounts,
    AdminRequestRow,
    AdminRequestsResponse,
    RequestChange,
)
from .wire.admin_reviews import (
    AdminReviewClaimHistoryEntry,
    AdminReviewDetail,
    AdminReviewOpenClaim,
    AdminReviewRow,
    AdminReviewsResponse,
    AdminReviewTransition,
)
from .wire.admin_users import (
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
from .wire.announcements import Announcement
from .wire.audio import AudioSurahEntry, AudioSurahsResponse
from .wire.email_preferences import EmailPreferences, EmailPreferencesSaved
from .wire.intake_requests import (
    IntakeAttestations,
    IntakeSource,
    IntakeSubmission,
    IntakeValidation,
    ProbeResponse,
    ProbeResult,
    SourceLink,
)
from .wire.mark_ready import (
    MarkReadyChecklist,
    MarkReadyRequest,
    MarkReadySubmission,
)
from .wire.public import (
    AdminDiscardedDelivery,
    AdminViewReciter,
    BucketCounts,
    PublicDelivery,
    PublicReciter,
    PublicReciterPage,
)
from .wire.release import (
    AdminCutReleaseRequest,
    AdminGhReleaseMember,
    AdminInFlightJob,
    AdminLastBatch,
    AdminLatestGhRelease,
    AdminLaunchResponse,
    AdminPublishBatchRequest,
    AdminPublishError,
    AdminReleaseLinks,
    AdminReleasePreviewCounts,
    AdminReleasePreviewResponse,
    AdminReleasePreviewRow,
    AdminReleaseRow,
    AdminReleasesStatusResponse,
    AdminReleasesSummary,
    AdminReleaseStatusRow,
    StaleReason,
    SuggestedAction,
)
from .wire.seg import (
    SegAllResponse,
    SegConfigResponse,
    SegDataResponse,
    SegmentFlagView,
    SegmentsChapterSummary,
    SegPeaksResponse,
    SegReciter,
    SegRecitersResponse,
    SegSaveRequest,
    SegSaveResponse,
    SegSegmentPeaksRequest,
    SegSegmentPeaksResponse,
    SegUndoBatchRequest,
    SegUndoOpsRequest,
    SegUndoResponse,
    SegValAnyItem,
    SegValidateResponse,
)
from .wire.timestamps import TsConfigResponse, TsManifestResponse
from .wire.ts_flags import (
    TsFlagAuthor,
    TsFlagComment,
    TsFlagCreateRequest,
    TsFlagVerseCount,
    TsReciterFlags,
    TsVerseFlags,
)

__all__ = [
    "Announcement",
    "AdminDiscardedDelivery",
    "AdminViewReciter",
    "AudioSurahEntry",
    "AudioSurahsResponse",
    "BucketCounts",
    "PublicDelivery",
    "PublicReciter",
    "PublicReciterPage",
    "SegAllResponse",
    "SegConfigResponse",
    "SegDataResponse",
    "SegPeaksResponse",
    "SegReciter",
    "SegRecitersResponse",
    "SegSaveRequest",
    "SegSaveResponse",
    "SegSegmentPeaksRequest",
    "SegSegmentPeaksResponse",
    "SegUndoBatchRequest",
    "SegUndoOpsRequest",
    "SegUndoResponse",
    "SegValAnyItem",
    "SegValidateResponse",
    "SegmentFlagView",
    "SegmentsChapterSummary",
    "TsConfigResponse",
    "TsManifestResponse",
    "TsFlagAuthor",
    "TsFlagComment",
    "TsFlagCreateRequest",
    "TsFlagVerseCount",
    "TsReciterFlags",
    "TsVerseFlags",
    "AutoGenTsConfig",
    "AutomationConfig",
    "AutomationResponse",
    "AutomationStateRow",
    "GhCutConfig",
    "HfPublishConfig",
    "StaleMetadataConfig",
    "StaleTsRegenConfig",
    "TsGenerationDefaults",
    "AdminActiveClaim",
    "AdminActivityEvent",
    "AdminCapabilityRow",
    "AdminCapabilityTierState",
    "AdminClaimEvent",
    "AdminCutReleaseRequest",
    "AdminGhReleaseMember",
    "AdminInFlightJob",
    "AdminLastBatch",
    "AdminLatestGhRelease",
    "AdminLaunchResponse",
    "AdminPublishBatchRequest",
    "AdminPublishError",
    "AdminReleaseLinks",
    "AdminReleasePreviewCounts",
    "AdminReleasePreviewResponse",
    "AdminReleasePreviewRow",
    "AdminReleaseRow",
    "AdminReleaseStatusRow",
    "AdminReleasesStatusResponse",
    "AdminReleasesSummary",
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
    "AdminReviewsResponse",
    "AdminRoleEvent",
    "AdminUserDetail",
    "AdminUserRow",
    "AdminUserStats",
    "AdminUsersResponse",
    "AdminUsersSummary",
    "AdminVisitorStats",
    "DetailedDocument",
    "DetailedEntry",
    "DetailedMeta",
    "DetailedSegment",
    "EmailPreferences",
    "EmailPreferencesSaved",
    "EditHistoryBatch",
    "EditOperation",
    "EditOpPatch",
    "ErrorEnvelope",
    "FlagFollowUp",
    "IntakeAttestations",
    "IntakeSource",
    "IntakeSubmission",
    "IntakeValidation",
    "JobMember",
    "JobRecord",
    "JobsListResponse",
    "MarkReadyChecklist",
    "MarkReadyRequest",
    "MarkReadySubmission",
    "OkAck",
    "PeaksRecord",
    "ProbeResponse",
    "ProbeResult",
    "RequestChange",
    "SegmentFlag",
    "SourceLink",
    "StaleReason",
    "SuggestedAction",
    "TsJobRecord",
    "TsJobSettings",
    "TsShardCell",
    "TsShardDoc",
    "TsShardMeta",
    "TsShardSegment",
    "TsShardWord",
    "CellRole",
    "CellStatus",
    "TajweedRule",
    "TsValidationDoc",
    "TsValidationMeta",
    "TsValidationVerse",
    "VisitorDayStat",
]
