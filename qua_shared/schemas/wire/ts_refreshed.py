"""Internal "timestamps refreshed" callback wire schema.

A manual backfill, schema-bump re-stamp, or local TS regen uploads shards to
the bucket OUTSIDE the normal HF-job completion path, so the Inspector never
records a new ``ts`` release nor recomputes staleness — the refresh is silent.

``TsRefreshedRequest`` is the body of ``POST /api/admin/internal/ts-refreshed``
(the route in ``inspector/routes/admin/internal.py``), POSTed by the shared
``qua_shared.inspector_notify.notify_ts_refreshed`` helper after a successful
upload. The endpoint is secret-gated (the same ``X-Inspector-Job-Secret``
mechanism the job-completion webhook uses), not a user session — it is
machine-to-machine.

Internal-only: NOT re-exported from ``fe_types.py`` (no FE consumer), so it is
deliberately absent from the codegen'd ``schemas.ts``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TsRefreshedRequest(BaseModel):
    """Body for ``POST /api/admin/internal/ts-refreshed``.

    ``slug`` is the reciter whose shards were just re-uploaded. ``chapters`` is
    the optional list of surahs touched (omitted/empty = whole reciter).
    ``reason`` is a short free-text provenance tag (e.g. ``"v12_cutover"``,
    ``"local_regen"``) recorded on the audit event. ``produced_at`` is an
    optional ISO-8601 UTC override for the new TS-release ``produced_at``
    watermark; absent = the server stamps ``now`` (the common case — the
    refresh just happened).
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1)
    chapters: list[int] | None = None
    reason: str | None = Field(default=None, max_length=200)
    produced_at: str | None = None
