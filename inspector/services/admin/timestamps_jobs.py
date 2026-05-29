"""Launch + inspect the in-container timestamps-generation HF Job.

Flask-free. The Reviews tab triggers ``launch()`` for an under-review
reciter; the job runs MFA alignment in-container (strategy A — stock conda
base + the MFA stack pulled from the private ``aligner-bucket``) and writes
v2 per-chapter shards into the inspector bucket. Status is read live from HF
(``inspect_job`` / ``fetch_job_logs``) — no inbound callback, no jobs table;
the launched id is appended to the reciter's ``timestamps_job_ids``.

Launching does NOT transition the reciter — it stays UNDER_REVIEW; this is
job bookkeeping, not a lifecycle change. See
docs/planning/inspector-deploy/v2/phases/13-timestamps-job.md.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from services.state import state as state_service
from services.storage.hf_bucket import resolve_bucket_repo

log = logging.getLogger("inspector")

# Private bucket holding the MFA runtime (mfa-runtime/) + the staged job code
# (code/). Mounted read-only at /aux in the job.
ALIGNER_BUCKET = os.environ.get("INSPECTOR_ALIGNER_BUCKET", "hetchyy/aligner-bucket")
JOB_IMAGE = "condaforge/mambaforge:latest"
JOB_FLAVOR = os.environ.get("INSPECTOR_TS_JOB_FLAVOR", "cpu-upgrade")
JOB_TIMEOUT = os.environ.get("INSPECTOR_TS_JOB_TIMEOUT", "2h")
_REPO_ROOT = Path(__file__).resolve().parents[3]

# python 3.11 pin: 3.14 breaks MFA (Path.copy() conflict). quranic-phonemizer
# is public on PyPI. The MFA acoustic model is pulled from the bucket at
# runtime (not installed), keeping the gitignored stack out of any image.
_INSTALL = (
    "mamba install -y -c conda-forge python=3.11 montreal-forced-aligner "
    "&& /opt/conda/bin/pip install soundfile tgt numpy PyYAML requests psutil "
    "'quranic-phonemizer>=2.0' 'huggingface_hub>=1.8.0' "
    "&& mkdir -p /scratch"
)
_ENTRYPOINT = "python /aux/code/scripts/jobs/generate_timestamps.py"


def _job_id(job) -> str | None:
    return getattr(job, "id", None) or getattr(job, "job_id", None)


def _stage_job_code() -> None:
    """Upload scripts/lib + scripts/jobs to ``aligner-bucket/code/`` so the job
    can import the pipeline. Idempotent (Xet skips unchanged content); cheap
    enough to run on every launch so the job always runs current code."""
    from huggingface_hub import batch_bucket_files

    adds: list[tuple[str, str]] = []
    for sub in ("scripts/lib", "scripts/jobs"):
        base = _REPO_ROOT / sub
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(_REPO_ROOT).as_posix()
            adds.append((str(path), f"code/{rel}"))
    if adds:
        batch_bucket_files(ALIGNER_BUCKET, add=adds)
        log.info("staged %d job-code files to %s/code/", len(adds), ALIGNER_BUCKET)


def running_job_for(slug: str) -> str | None:
    """Return the id of an in-flight timestamps job for ``slug`` (single-flight
    guard), else None. Two concurrent jobs would race the same
    ``timestamps/`` shards."""
    from huggingface_hub import list_jobs

    try:
        for job in list_jobs():
            labels = getattr(job, "labels", {}) or {}
            if labels.get("task") != "timestamps" or labels.get("reciter") != slug:
                continue
            status = _status_str(job)
            if status in ("running", "pending", "updating"):
                return _job_id(job)
    except Exception as exc:  # never block a launch on a list failure
        log.warning("running_job_for(%s) failed: %s", slug, exc)
    return None


def _status_str(info) -> str:
    status = getattr(info, "status", None)
    stage = getattr(status, "stage", None)
    return str(stage if stage is not None else status or "").lower()


def launch(slug: str, *, beams: list[int] | None = None) -> dict:
    """Launch the timestamps job for ``slug`` and link its id to the reciter.

    Returns ``{"job_id", "url"}``. Caller must enforce single-flight via
    ``running_job_for`` first.
    """
    from huggingface_hub import Volume, get_token, run_job

    row = state_service.get_row(slug)
    if row is None:
        raise ValueError(f"unknown slug {slug}")

    _stage_job_code()
    bucket = resolve_bucket_repo()

    env = {
        "SLUG": slug,
        "INSPECTOR_BUCKET_MOUNT": "/data",
        "MFA_APP_PATH": "/aux/mfa-runtime/app.py",
        "PYTHONPATH": "/aux/code",
        "MFA_WORKER_BASE": "/scratch",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    workers = os.environ.get("INSPECTOR_TS_JOB_WORKERS", "").strip()
    if workers:
        env["WORKERS"] = workers
    if beams:
        env["BEAMS"] = ",".join(str(b) for b in beams)

    job = run_job(
        image=JOB_IMAGE,
        command=["bash", "-lc", f"{_INSTALL} && {_ENTRYPOINT}"],
        flavor=JOB_FLAVOR,
        timeout=JOB_TIMEOUT,
        env=env,
        secrets={"HF_TOKEN": get_token()},
        volumes=[
            Volume(type="bucket", source=bucket, mount_path="/data"),
            Volume(type="bucket", source=ALIGNER_BUCKET, mount_path="/aux", read_only=True),
        ],
        labels={"task": "timestamps", "reciter": slug},
    )
    job_id = _job_id(job)
    if job_id:
        state_service.record_timestamps_job(slug, job_id)
    log.info("launched timestamps job %s for %s (flavor=%s)", job_id, slug, JOB_FLAVOR)
    return {"job_id": job_id, "url": getattr(job, "url", None)}


def job_status(job_id: str, *, log_tail: int = 200) -> dict:
    """Live status + bounded log tail for a job (HF is authoritative)."""
    from huggingface_hub import fetch_job_logs, inspect_job

    info = inspect_job(job_id=job_id)
    logs: list[str] = []
    try:
        for line in fetch_job_logs(job_id=job_id):
            logs.append(line)
            if len(logs) > log_tail:
                logs.pop(0)
    except Exception as exc:
        log.warning("fetch_job_logs(%s) failed: %s", job_id, exc)
    return {"job_id": job_id, "status": _status_str(info), "logs": logs}
