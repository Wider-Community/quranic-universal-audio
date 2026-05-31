"""HF dataset publish kind — per-recitation push.

Launches an HF Job that runs ``scripts/jobs/publish_hf.py``. The job reads
the recitation's bucket artifacts (detailed.json, timestamps/*.json.gz,
audio/*.mp3 via Xing-master stream-copy slicing) and pushes a parquet split
to the public HF dataset.

On completion the webhook → ``complete()`` inserts a
``per_recitation_releases(track='hf', ...)`` row, supersedes prior ``hf``
rows for the slug, and fires ``released`` event with payload
``{track: 'hf', slug, version}``.

The HF Job NEVER writes the DB. Mutation flows through ``complete()``
either via the webhook route or via the in-process poll fallback in
``jobs.base``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from scripts.lib.schemas import Actor
from services.db import repo_releases
from services.db.sync import durable_transaction
from services.state import audit
from services.storage.hf_bucket import resolve_bucket_repo

from . import base

log = logging.getLogger("inspector")

KIND = "hf_publish"

JOB_FLAVOR = os.environ.get("INSPECTOR_HF_JOB_FLAVOR", "cpu-basic")
JOB_TIMEOUT = os.environ.get("INSPECTOR_HF_JOB_TIMEOUT", "30m")


def launch(slug: str, *, webhook_base: str | None = None) -> dict:
    """Launch a publish-hf job for ``slug``. Returns ``{job_id, url}``."""
    from huggingface_hub import Volume, get_token, run_job

    # Cross-kind single-flight on the slug — TS or HF publish in flight blocks
    # this launch (and vice versa).
    busy = base.running_job_for(slug=slug)
    if busy is not None:
        raise RuntimeError(
            f"job already in flight for {slug}: kind={busy[0]} id={busy[1]}")

    base.stage_job_code()
    bucket = resolve_bucket_repo()
    env = {
        "SLUG": slug,
        "INSPECTOR_BUCKET_MOUNT": "/data",
        "PYTHONPATH": "/aux/code",
    }
    secrets = {"HF_TOKEN": get_token()}
    webhook_secret = os.environ.get("INSPECTOR_WEBHOOK_SECRET", "").strip()
    if webhook_secret and webhook_base:
        env["INSPECTOR_WEBHOOK_URL"] = (
            webhook_base.rstrip("/") + "/api/webhooks/hf-publish-complete"
        )
        secrets["INSPECTOR_WEBHOOK_SECRET"] = webhook_secret

    entrypoint = "python /aux/code/scripts/jobs/publish_hf.py"
    if base.NEEDS_BOOTSTRAP:
        command = ["bash", "-lc",
                   "/opt/conda/bin/pip install datasets huggingface_hub orjson "
                   "&& " + entrypoint]
    else:
        command = ["bash", "-lc",
                   f"conda run -p /env --no-capture-output {entrypoint}"]

    job = run_job(
        image=base.JOB_IMAGE,
        command=command,
        flavor=JOB_FLAVOR,
        timeout=JOB_TIMEOUT,
        env=env,
        secrets=secrets,
        volumes=[
            Volume(type="bucket", source=bucket, mount_path="/data"),
            Volume(type="bucket", source=base.ALIGNER_BUCKET, mount_path="/aux",
                   read_only=True),
        ],
        labels={"task": KIND, "reciter": slug},
    )
    job_id = base.hf_job_id(job) or ""
    url = getattr(job, "url", None)
    log.info("launched hf_publish job %s for %s", job_id, slug)
    return {"job_id": job_id, "url": url}


def complete(slug: str | None, job_id: str, *,
             version: str | None = None,
             external_uri: str | None = None,
             launched_by: str | None = None,
             validation_summary: dict | None = None) -> dict:
    """Record an HF dataset publish in the DB. Idempotent on (track, slug, version).

    Inserts a new ``per_recitation_releases(track='hf')`` row, supersedes any
    prior current row for the slug, and fires ``released({track:'hf', ...})``.

    ``version`` is the HF revision SHA the publish landed at; pulled from the
    webhook payload OR from a fallback that reads the just-pushed dataset.
    """
    if slug is None:
        log.warning("hf_publish.complete called with slug=None")
        return {"ok": False, "reason": "no slug"}

    version = version or job_id  # fallback so the unique key has something
    now = datetime.now(timezone.utc)
    actor = Actor(
        hf_user_id="SYSTEM_ACTOR",
        login_at_time=launched_by or "system",
        role="owner",
    )
    with durable_transaction() as _:
        # Idempotency: if a row for (hf, slug, version) already exists, no-op.
        existing = repo_releases.current_release("hf", slug)
        if existing and existing.get("version") == version:
            log.info("hf_publish.complete(%s, %s): already recorded", slug, version)
            return {"ok": True, "skipped": "duplicate"}
        # Supersede prior current row FIRST — the partial-unique blocks two
        # current rows for (hf, slug) so we can't insert before clearing.
        repo_releases.supersede_current("hf", slug, except_id=-1, at=now)
        new_id = repo_releases.insert_per_recitation_release(
            track="hf", slug=slug, version=version,
            produced_at=now,
            produced_by="SYSTEM_ACTOR",
            produced_by_job_id=job_id,
            launched_by=launched_by,
            external_uri=external_uri,
            validation_summary=validation_summary,
        )
        audit.append(
            "released",
            actor=actor,
            slug=slug,
            payload={"track": "hf", "version": version, "job_id": job_id},
            reason="hf_publish",
        )
    log.info("hf_publish.complete(%s, %s): recorded", slug, version)
    return {"ok": True, "release_id": new_id}


def register() -> None:
    base.register_handler(KIND, lambda slug, jid: complete(slug, jid))
