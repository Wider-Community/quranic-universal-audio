"""HF dataset catalog refresh kind — global ``mushafs`` rebuild.

Launches a lightweight HF Job (``qua_jobs/refresh_hf_catalog.py``) that rebuilds
ONLY the dataset catalog config + card from the live Inspector SQLite catalog —
no audio slicing, no per-verse parquet rebuild. It is the cheap remediation for
``catalog_edit`` HF staleness (a metadata edit that desynced the published
catalog from canonical).

On completion the webhook → ``complete()`` clears the ``catalog_edit`` HF
staleness stamps (the global parquet now matches canonical) and audits the
refresh. ``ts_regen`` staleness is left intact — that still needs a republish.

The HF Job NEVER writes the DB; mutation flows through ``complete()`` via the
webhook route or the 120 s poll fallback in ``jobs.base``.
"""

from __future__ import annotations

import logging
import os

from qua_shared.schemas import Actor
from services.db import repo_releases
from services.db.sync import durable_transaction
from services.state import audit
from services.storage.hf_bucket import resolve_bucket_repo

from . import base

log = logging.getLogger("inspector")

KIND = "refresh_catalog"

JOB_FLAVOR = os.environ.get("INSPECTOR_REFRESH_JOB_FLAVOR", "cpu-upgrade")
JOB_TIMEOUT = os.environ.get("INSPECTOR_REFRESH_JOB_TIMEOUT", "20m")


def launch(*, webhook_base: str | None = None) -> dict:
    """Launch a catalog-refresh job. Returns ``{job_id, url}``.

    Global single-flight — refuses if another refresh is in flight.
    """
    from huggingface_hub import Volume, get_token, run_job

    busy = base.running_job_for(kind=KIND)
    if busy is not None:
        raise RuntimeError(f"refresh_catalog already in flight: kind={busy[0]} id={busy[1]}")

    base.stage_job_code()
    bucket = resolve_bucket_repo()
    env = {
        "INSPECTOR_BUCKET_MOUNT": "/data",
        "PYTHONPATH": "/aux/code",
    }
    secrets = {"HF_TOKEN": get_token()}
    webhook_secret = os.environ.get("INSPECTOR_WEBHOOK_SECRET", "").strip()
    if webhook_secret and webhook_base:
        env["INSPECTOR_WEBHOOK_URL"] = (
            webhook_base.rstrip("/") + "/api/webhooks/hf-catalog-refresh-complete"
        )
        secrets["INSPECTOR_WEBHOOK_SECRET"] = webhook_secret

    # The refresh path only builds the catalog parquet + card — ``datasets`` +
    # ``pyyaml`` + ``orjson``. No torch/torchcodec (no Audio() write path), so
    # startup is meaningfully lighter than a full publish.
    deps = "datasets orjson pyyaml"
    entrypoint = "python /aux/code/qua_jobs/refresh_hf_catalog.py"
    if base.NEEDS_BOOTSTRAP:
        command = [
            "bash",
            "-lc",
            "mamba install -y -c conda-forge python=3.11 "
            f"&& /opt/conda/bin/pip install -q huggingface_hub {deps} "
            f"&& {entrypoint}",
        ]
    else:
        command = [
            "bash",
            "-lc",
            f"/env/bin/pip install -q {deps} && conda run -p /env --no-capture-output {entrypoint}",
        ]

    job = run_job(
        image=base.JOB_IMAGE,
        command=command,
        flavor=JOB_FLAVOR,
        timeout=JOB_TIMEOUT,
        env=env,
        secrets=secrets,
        volumes=[
            Volume(type="bucket", source=bucket, mount_path="/data"),
            Volume(type="bucket", source=base.ALIGNER_BUCKET, mount_path="/aux", read_only=True),
        ],
        labels={"task": KIND, "reciter": "_global"},
    )
    job_id = base.hf_job_id(job) or ""
    url = getattr(job, "url", None)
    log.info("launched refresh_catalog job %s", job_id)
    from services.storage import cache as _cache

    _cache.invalidate_in_flight_jobs_cache()
    return {"job_id": job_id, "url": url}


def complete(slug: str | None, job_id: str) -> dict:
    """Clear ``catalog_edit`` HF staleness after a successful refresh.

    Global + idempotent: the refresh rebuilt the whole ``mushafs`` parquet from
    canonical, so every catalog-only-stale HF row is now reconciled. Clearing
    an already-clear set is a no-op, so webhook + poll double-fire is safe.
    ``ts_regen`` staleness is deliberately untouched (still needs a republish).
    """
    actor = Actor(hf_user_id="SYSTEM_ACTOR", login_at_time="system", role="owner")
    with durable_transaction() as _:
        cleared = repo_releases.clear_catalog_stale_hf()
        if cleared:
            audit.append(
                "catalog.refreshed",
                actor=actor,
                slug=None,
                payload={"cleared_stale_hf": cleared, "job_id": job_id},
                reason="refresh_catalog",
            )
    log.info("refresh_catalog.complete(%s): cleared %d catalog-stale hf rows", job_id, cleared)
    from services.storage import cache as _cache

    _cache.invalidate_in_flight_jobs_cache()
    return {"ok": True, "cleared_stale_hf": cleared}


def register() -> None:
    base.register_handler(KIND, lambda slug, jid: complete(slug, jid))
