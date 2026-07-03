"""HF dataset publish kind — per-recitation push.

Launches an HF Job that runs ``qua_jobs/publish_hf.py``. The job reads
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
from datetime import UTC, datetime
from typing import cast

from qua_shared.schemas import Actor, Role
from services.db import repo_releases
from services.db.sync import durable_transaction
from services.state import audit
from services.storage.hf_bucket import resolve_bucket_repo

from . import base, records

log = logging.getLogger("inspector")

KIND = "hf_publish"

JOB_FLAVOR = os.environ.get("INSPECTOR_HF_JOB_FLAVOR", "cpu-upgrade")
JOB_TIMEOUT = os.environ.get("INSPECTOR_HF_JOB_TIMEOUT", "30m")


def launch(slug: str, *, webhook_base: str | None = None) -> dict:
    """Launch a publish-hf job for ``slug``. Returns ``{job_id, url}``."""
    from huggingface_hub import SpaceHardware, Volume, get_token, run_job

    # Cross-kind single-flight on the slug — TS or HF publish in flight blocks
    # this launch (and vice versa).
    busy = base.running_job_for(slug=slug)
    if busy is not None:
        raise RuntimeError(f"job already in flight for {slug}: kind={busy[0]} id={busy[1]}")

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

    # publish_hf needs ``datasets`` + ``orjson`` + ``pyyaml`` on top of the
    # prebuilt /env. ``torch`` + ``torchcodec`` are required by datasets v3
    # ``Audio()`` write path (encode_example imports torch unconditionally —
    # ``decode=False`` only affects the read side). CPU-only torch is ~200 MB,
    # adds ~60-90s to job startup but keeps consumer UX intact
    # (``ds[i]["audio"]["array"]`` returns a waveform).
    deps = "datasets orjson pyyaml torch torchcodec"
    entrypoint = "python /aux/code/qua_jobs/publish_hf.py"
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
        flavor=cast(SpaceHardware, JOB_FLAVOR),
        timeout=JOB_TIMEOUT,
        env=env,
        secrets=secrets,
        volumes=[
            Volume(type="bucket", source=bucket, mount_path="/data"),
            Volume(type="bucket", source=base.ALIGNER_BUCKET, mount_path="/aux", read_only=True),
        ],
        labels={"task": KIND, "reciter": slug},
    )
    job_id = base.hf_job_id(job) or ""
    url = getattr(job, "url", None)
    records.record_launch(KIND, slug, job_id, url=url)
    log.info("launched hf_publish job %s for %s", job_id, slug)
    # Bust the in-flight cache so the next /releases/status fetch reflects
    # the new job without waiting for the 5 s TTL.
    from services.storage import cache as _cache

    _cache.invalidate_in_flight_jobs_cache()
    return {"job_id": job_id, "url": url}


def complete(
    slug: str | None,
    job_id: str,
    *,
    version: str | None = None,
    external_uri: str | None = None,
    launched_by: str | None = None,
    validation_summary: dict | None = None,
) -> dict:
    """Record an HF dataset publish in the DB. Idempotent on (track, slug, version).

    Inserts a new ``per_recitation_releases(track='hf')`` row, supersedes any
    prior current row for the slug, and fires ``released({track:'hf', ...})``.
    When the slug has no current ``ts`` row (timestamps ingested offline, never
    through an in-app TS job), it first registers one (``version='offline-ingest'``)
    so the published reciter isn't orphaned from staleness / GH-cut eligibility.

    ``version`` is the HF revision SHA the publish landed at; pulled from the
    webhook payload OR from a fallback that reads the just-pushed dataset.
    """
    if slug is None:
        log.warning("hf_publish.complete called with slug=None")
        return {"ok": False, "reason": "no slug"}

    version = version or job_id  # fallback so the unique key has something

    # Idempotency pre-check OUTSIDE the write txn. The poll worker re-checks
    # every still-listed terminal job, so for an already-recorded publish this
    # returns before opening a durable_transaction — which would bump db_seq and
    # push the whole DB to the bucket for a no-op. Any row (current OR
    # superseded) for (hf, slug, version) counts.
    existing = repo_releases.release_by_version("hf", slug, version)
    if existing is not None:
        log.info(
            "hf_publish.complete(%s, %s): already recorded (id=%s)",
            slug,
            version,
            existing.get("id"),
        )
        return {"ok": True, "skipped": "duplicate"}

    now = datetime.now(UTC)
    actor = Actor(
        hf_user_id="SYSTEM_ACTOR",
        login_at_time=launched_by or "system",
        role=Role.OWNER,
    )
    with durable_transaction() as _:
        # Re-read inside the txn as the atomic guard: webhook + poll can
        # double-fire for a freshly-terminal job, and the serialized writer
        # means the loser sees the winner's row here and bails (one-time, not
        # the recurring poll path). The partial-unique on (track, slug) WHERE
        # superseded_at IS NULL only blocks two CURRENT rows.
        if repo_releases.release_by_version("hf", slug, version) is not None:
            return {"ok": True, "skipped": "duplicate"}
        # Invariant: an HF dataset release rests on a TS production. A reciter
        # whose timestamps were ingested offline (bucket upload, never an in-app
        # TS job) has no ts release row, so publishing it here would leave it
        # orphaned — invisible to staleness / GH-cut eligibility / ts-refresh.
        # Register the production now so the published reciter is tracked.
        if repo_releases.current_release("ts", slug) is None:
            repo_releases.insert_per_recitation_release(
                track="ts",
                slug=slug,
                version="offline-ingest",
                produced_at=now,
                produced_by="SYSTEM_ACTOR",
            )
        # Supersede prior current row FIRST — the partial-unique blocks two
        # current rows for (hf, slug) so we can't insert before clearing.
        repo_releases.supersede_current("hf", slug, except_id=-1, at=now)
        new_id = repo_releases.insert_per_recitation_release(
            track="hf",
            slug=slug,
            version=version,
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
    records.record_terminal(
        KIND,
        slug,
        job_id,
        status="succeeded",
        version=version,
        external_uri=external_uri,
        validation_summary=validation_summary,
        launched_by=launched_by,
    )
    log.info("hf_publish.complete(%s, %s): recorded", slug, version)
    # Terminal transition — invalidate the in-flight cache so the FE drops
    # the row from "In progress" on the next fetch instead of waiting up to
    # ~5 s for the TTL.
    from services.storage import cache as _cache

    _cache.invalidate_in_flight_jobs_cache()
    return {"ok": True, "release_id": new_id}


def register() -> None:
    def _handler(slug: str | None, jid: str) -> None:
        complete(slug, jid)

    base.register_handler(KIND, _handler)
