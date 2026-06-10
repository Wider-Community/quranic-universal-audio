"""Audit log record schema: ``<bucket>/audit/<YYYY>-<MM>.jsonl``.

One folder for all events (state, claim, catalog, admin, access). Partitioned
per-month from day one. Append-only. Inspector backend is sole writer.

Spec: docs/planning/inspector-deploy/v2/inspector-state-management.md §2.

``event`` is a free-form string matching the §4 vocabulary; per-event payload
shapes are colocated with the dispatch function in ``inspector/services/state.py``.
This schema validates the envelope only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .access import Role


class Actor(BaseModel):
    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    hf_user_id: str = Field(..., min_length=1, description="OIDC sub; canonical")
    login_at_time: str = Field(..., min_length=1, description="HF login at write time")
    role: Role


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: datetime
    event: str = Field(..., min_length=1, description="See state-mgmt §4 vocabulary")
    slug: str | None = None
    from_state: str | None = None
    to_state: str | None = None
    actor: Actor
    payload: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    reason: str | None = None
    result: Literal["ok", "error"] = "ok"
