"""Wire shapes for the native align pipeline (``/api/admin/reciter/<slug>/align*``).

``AlignRunStatus`` is what the Requests tab renders: the durable ``align_runs``
row plus the live per-stage detail the runner keeps in memory (chapter counts,
current chapter, beam probe progress). ``AdminRequestRow.align`` carries the
same shape for the open queue.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AlignStage = Literal["acquire", "align", "sidecars", "assemble", "done"]
AlignRunState = Literal["pending", "running", "failed", "succeeded", "canceled"]
AlignModelName = Literal["Base", "Large"]


class AlignStartRequest(BaseModel):
    """Body of ``POST /api/admin/reciter/<slug>/align``."""

    model_config = ConfigDict(extra="forbid")

    model_name: AlignModelName = "Large"


class AlignRunStatus(BaseModel):
    """One align run as the admin surfaces read it."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    slug: str
    stage: AlignStage
    status: AlignRunState
    attempt: int = 1
    requested_by: str | None = None
    model_name: str | None = None

    chapters_total: int = 0
    chapters_done: int = 0
    #: ``"<chapter>: <error>"`` for chapters the current stage gave up on.
    chapter_failures: list[str] = Field(default_factory=list)
    #: Free-form live detail from the running stage (current chapter, beam, …).
    detail: dict = Field(default_factory=dict)

    acquire_job_id: str | None = None
    acquire_job_url: str | None = None
    last_error: str | None = None

    started_at: str
    updated_at: str
    ended_at: str | None = None
