"""Stage 1 — persist chapter audio + peaks to the bucket via a CPU HF Job.

Launches ``qua_jobs/acquire_audio.py`` with the same volumes/labels shape as the
other job kinds (bucket RW at ``/data``, aligner-bucket code RO at ``/aux``), then
polls it to a terminal state from the worker thread. The job's report at
``staging/<slug>/<run>/acquire.json`` is the stage's output; any chapter failure
fails the stage with the chapter list so the manifest can be fixed and retried.
"""

from __future__ import annotations

import logging
import os
import time
from typing import cast

from services.admin.jobs import base, records
from services.storage.hf_bucket import resolve_bucket_repo

from . import progress, staging

log = logging.getLogger("inspector")

KIND = "acquire_audio"
JOB_FLAVOR = os.environ.get("INSPECTOR_ACQUIRE_JOB_FLAVOR", "cpu-upgrade")
JOB_TIMEOUT = os.environ.get("INSPECTOR_ACQUIRE_JOB_TIMEOUT", "6h")
POLL_INTERVAL_S = 30
_ENTRYPOINT = "python /aux/code/qua_jobs/acquire_audio.py"


class AcquireError(RuntimeError):
    pass


def launch(slug: str, run_id: str, *, needs_ytdlp: bool, channels: int | None) -> str:
    """Launch the acquire job; returns its HF job id."""
    from huggingface_hub import SpaceHardware, Volume, get_token, run_job

    busy = base.running_job_for(slug=slug)
    if busy is not None:
        raise AcquireError(f"job already in flight for {slug}: kind={busy[0]} id={busy[1]}")

    base.stage_job_code()
    env = {
        "SLUG": slug,
        "RUN_ID": run_id,
        "INSPECTOR_BUCKET_MOUNT": "/data",
        "PYTHONPATH": "/aux/code",
    }
    if channels in (1, 2):
        env["CHANNELS"] = str(channels)
    command = base.job_command(_ENTRYPOINT, "numpy" + (" yt-dlp" if needs_ytdlp else ""))

    job = run_job(
        image=base.JOB_IMAGE,
        command=command,
        flavor=cast(SpaceHardware, JOB_FLAVOR),
        timeout=JOB_TIMEOUT,
        env=env,
        secrets={"HF_TOKEN": get_token()},
        volumes=[
            Volume(type="bucket", source=resolve_bucket_repo(), mount_path="/data"),
            Volume(type="bucket", source=base.ALIGNER_BUCKET, mount_path="/aux", read_only=True),
        ],
        labels={"task": KIND, "reciter": slug},
    )
    job_id = base.hf_job_id(job) or ""
    records.record_launch(KIND, slug, job_id, url=getattr(job, "url", None))
    from services.storage import cache as _cache

    _cache.invalidate_in_flight_jobs_cache()
    log.info("align %s: launched acquire job %s for %s", run_id, job_id, slug)
    return job_id


def wait(slug: str, run_id: str, job_id: str) -> dict:
    """Block until the job is terminal; return the acquire report. Raises on failure."""
    from huggingface_hub import inspect_job

    while True:
        progress.check_cancel(run_id)
        try:
            status = base.hf_status_str(inspect_job(job_id=job_id))
        except Exception as exc:  # noqa: BLE001 — transient HF API errors
            log.warning("align %s: inspect_job(%s) failed: %s", run_id, job_id, exc)
            status = "unknown"
        progress.set_detail(run_id, job_id=job_id, job_status=status)
        if status in base.TERMINAL:
            break
        time.sleep(POLL_INTERVAL_S)

    report = staging.read_json(staging.acquire_path(slug, run_id)) or {}
    failures = report.get("failures") or {}
    ok = status in base.TERMINAL_SUCCESS and not failures
    records.record_terminal(KIND, slug, job_id, status="succeeded" if ok else "failed")
    if not ok:
        detail = "; ".join(f"{ch}: {err}" for ch, err in sorted(failures.items(), key=_ch_key))
        raise AcquireError(
            f"acquire job {job_id} ended {status}"
            + (f" — {len(failures)} chapter(s) failed: {detail}" if failures else "")
        )
    return report


def cancel(job_id: str) -> None:
    from huggingface_hub import cancel_job

    try:
        cancel_job(job_id=job_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("align: cancel_job(%s) failed: %s", job_id, exc)


def _ch_key(item: tuple[str, str]) -> int:
    return int(item[0]) if item[0].isdigit() else 0
