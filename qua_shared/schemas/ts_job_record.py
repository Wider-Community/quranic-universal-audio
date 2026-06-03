"""Timestamps-generation job record — persisted per HF Job run.

Written to ``jobs/ts/<job_id>.json`` on the bucket (top-level ``jobs/<type>/``
namespace, future-proof for other job kinds). Two writers, one schema:

- ``inspector/services/admin/timestamps_jobs.py`` writes the initial
  ``running`` record at launch and backstops the terminal status on poll if
  the job was hard-killed before self-writing.
- ``qua_jobs/generate_timestamps.py`` (the job itself) overwrites the
  record with the final status + full logs on completion/failure.

The Reviews-tab side panel reads these so a job's settings + logs stay
viewable any time after completion (HF log retention is limited). See
``docs/planning/inspector-deploy/v2/phases/13-timestamps-job.md`` and the
approved side-panel plan.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ._extras import strip_and_warn


class TsJobSettings(BaseModel):
    """Job parameters chosen by the admin in the launch form.

    ``beams`` is the resolved list passed to ``align_batch_multi_beam`` —
    ``[alignment_beam, *probe_beams]`` (deduped). Canonical beam = ``max(beams)``.
    """

    model_config = ConfigDict(extra="forbid")

    beams: list[int] = Field(default_factory=lambda: [50])
    persist_audio: bool = False
    gen_peaks: bool = False
    # Advanced (server-default when omitted by the form).
    workers: int | None = None
    flavor: str | None = None
    timeout: str | None = None
    batch_size: int | None = None
    download_workers: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _surface_extras(cls, data: Any) -> Any:
        return strip_and_warn(
            data, declared=set(cls.model_fields), dead=set(),
            model_name="TsJobSettings",
        )


class TsJobRecord(BaseModel):
    """One job run's durable record (settings + status + logs).

    ``status`` mirrors HF's lowercased stage (``running`` / ``succeeded`` /
    ``failed`` / ``error`` / ``timed-out`` …). ``logs`` is a bounded tail;
    ``log_truncated`` flags that earlier lines were dropped.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    job_id: str
    slug: str
    type: str = "ts"  # job kind — matches the jobs/<type>/ bucket namespace
    settings: TsJobSettings = Field(default_factory=TsJobSettings)
    status: str = "running"
    started_at: str | None = None  # ISO-8601 UTC
    ended_at: str | None = None    # ISO-8601 UTC
    url: str | None = None         # HF job URL
    logs: list[str] = Field(default_factory=list)
    log_truncated: bool = False
    error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _surface_extras(cls, data: Any) -> Any:
        return strip_and_warn(
            data, declared=set(cls.model_fields), dead=set(),
            model_name="TsJobRecord",
        )
