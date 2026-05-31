"""TS-gen kind handler (MFA in-container alignment).

Thin shim over the existing ``services.admin.timestamps_jobs`` implementation —
keeps the existing public surface (callers in ``routes/admin/reviews.py`` and
``routes/webhooks/ts_jobs.py`` import the legacy module directly). This module
exposes a kind-uniform façade (``launch``, ``complete``) so the poll
dispatcher in ``jobs.base`` can register it alongside ``hf_publish`` +
``cut_release``.

A full move of the implementation into this file is a follow-up — the
existing module is large + load-bearing, and Phase 2 prioritizes adding the
new kinds without destabilizing TS-gen.
"""

from __future__ import annotations

from services.admin import timestamps_jobs as _legacy

KIND = "ts"

# Re-export public API for the uniform jobs package surface.
launch = _legacy.launch
running_job_for = _legacy.running_job_for
job_status = _legacy.job_status
cancel_job = _legacy.cancel_job
list_job_records = _legacy.list_job_records
read_job_record = _legacy.read_job_record


def complete(slug: str | None, job_id: str) -> None:
    """Kind-uniform completion handler — adapts to ``complete_timestamps_job``.

    Idempotent: the legacy handler short-circuits on already-released rows
    and absent shards.
    """
    if slug is None:
        return
    _legacy.complete_timestamps_job(slug, job_id)


def register() -> None:
    from . import base
    base.register_handler(KIND, complete)
