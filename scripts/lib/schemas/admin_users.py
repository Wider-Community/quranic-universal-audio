"""Admin-dashboard Users-panel + visitor-analytics wire schemas.

Read models served by ``/api/admin/users``, ``/api/admin/users/<id>``, and
``/api/admin/visitor-stats``. All timestamps are ISO-8601 UTC *strings* exactly
as stored in the substrate (TEXT columns) — the FE formats them (relative time
/ date) so we never re-parse here. ``ConfigDict(extra="allow")`` for forward
compatibility, per the schema convention.

These are FE-facing: re-exported from ``fe_types.py`` and code-generated into
``inspector/frontend/src/lib/types/generated/schemas.ts`` via
``inspector/scripts/regen_fe_types.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AdminActiveClaim(BaseModel):
    model_config = ConfigDict(extra="allow")

    slug: str
    state: str | None = None
    marked_ready: bool = False


class AdminUserRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    hf_user_id: str
    login: str | None = None
    role: str = "contributor"
    joined: str | None = None          # users.first_seen (ISO)
    last_activity: str | None = None   # MAX(transitions.ts) (ISO)
    requests: int = 0
    reviews: int = 0
    active_claim: AdminActiveClaim | None = None


class AdminUsersSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    registered: int = 0
    active_this_week: int = 0


class AdminUsersResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    users: list[AdminUserRow] = Field(default_factory=list)
    summary: AdminUsersSummary = Field(default_factory=AdminUsersSummary)


# ---- detail drawer ----


class AdminUserStats(BaseModel):
    model_config = ConfigDict(extra="allow")

    reviews: int = 0
    lifetime_claims: int = 0
    avg_turnaround_seconds: float | None = None
    requests_by_status: dict[str, int] = Field(default_factory=dict)


class AdminRoleEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    granted_at: str | None = None
    granted_by: str | None = None
    revoked_at: str | None = None
    revoked_by: str | None = None
    reason: str | None = None


class AdminClaimEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    slug: str
    claimed_at: str | None = None
    released_at: str | None = None
    marked_ready_at: str | None = None
    close_reason: str | None = None
    outcome: str = ""   # derived label: "claimed, open now" / "published" / ...


class AdminRequestEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    kind: str
    slug: str | None = None
    submitted_at: str | None = None
    status: str
    resolved_at: str | None = None
    resolution_reason: str | None = None


class AdminActivityEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    ts: str | None = None
    slug: str | None = None
    event: str
    to_state: str | None = None
    reason: str | None = None


class AdminUserDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    hf_user_id: str
    login: str | None = None
    role: str = "contributor"
    joined: str | None = None
    last_login_at: str | None = None
    last_entry_at: str | None = None
    last_activity: str | None = None
    stats: AdminUserStats = Field(default_factory=AdminUserStats)
    role_history: list[AdminRoleEvent] = Field(default_factory=list)
    claims_history: list[AdminClaimEvent] = Field(default_factory=list)
    requests_history: list[AdminRequestEvent] = Field(default_factory=list)
    recent_activity: list[AdminActivityEvent] = Field(default_factory=list)


# ---- visitor analytics ----


class VisitorDayStat(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: str
    signed_in_hits: int = 0
    anon_hits: int = 0
    unique_signed_in: int = 0
    unique_anon: int = 0


class AdminVisitorStats(BaseModel):
    model_config = ConfigDict(extra="allow")

    today: VisitorDayStat
    recent: list[VisitorDayStat] = Field(default_factory=list)
