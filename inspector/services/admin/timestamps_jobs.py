"""Launch + inspect the in-container timestamps-generation HF Job.

Flask-free. The Reviews tab triggers ``launch()`` for an under-review
reciter; the job runs MFA alignment in-container (strategy A — stock conda
base + the MFA stack pulled from the private ``aligner-bucket``) and writes
v2 per-chapter shards into the inspector bucket. Status is read live from HF
(``inspect_job`` / ``fetch_job_logs``); the launched id is appended to the
reciter's ``timestamps_job_ids``.

Each run also gets a durable record at ``reciters/<slug>/jobs/ts/<job_id>.json``
(settings + status + logs) so the side panel can show past runs after HF log
retention expires. The record is written at launch (``running``), overwritten
by the job on completion, and backstopped by ``job_status`` if the job is
killed before self-writing. No SQLite — the record is a plain bucket file.

Launching does NOT transition the reciter at launch — it stays UNDER_REVIEW
(marked_ready) while the job runs, so a failed job is recoverable (just re-run).
On *success* the reciter is published: ``complete_timestamps_job`` fires
``reciter.published`` (under_review marked_ready → released) with
``SYSTEM_ACTOR``. Two triggers reach it: the job POSTs to the webhook route on
success (prod), and ``job_status`` calls it as an idempotent fallback when the
drawer poll sees a terminal-success status (dev / missed webhook). See
docs/planning/inspector-deploy/v2/phases/13-timestamps-job.md.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from pathlib import Path

from scripts.lib.schemas import TsJobRecord, TsJobSettings
from services.state import state as state_service
from services.storage.hf_bucket import StorageNotFound, get_backend, resolve_bucket_repo

log = logging.getLogger("inspector")

# Terminal HF stages (anything not in this set is treated as in-flight).
_TERMINAL = ("succeeded", "completed", "failed", "error", "errored",
             "timed-out", "timeout", "stopped", "canceled", "cancelled",
             "deleted")
# Terminal stages that mean the alignment finished cleanly. HF has reported
# both "succeeded" and "completed" for clean exits across job types, so the
# auto-release path treats either as success (the job's own self-POST always
# sends the literal "succeeded").
_TERMINAL_SUCCESS = ("succeeded", "completed")


def _job_record_path(slug: str, job_id: str) -> str:
    """Bucket path for a job's durable record. Per-reciter under
    ``reciters/<slug>/jobs/ts/`` — colocated with all the reciter's other
    content (detailed/audio/peaks/timestamps/edit_history), consistent with the
    bucket convention that everything for a reciter lives under its folder."""
    return f"reciters/{slug}/jobs/ts/{job_id}.json"


def _legacy_job_record_path(job_id: str) -> str:
    """Pre-2026-05 top-level path. Read-only fallback so records written before
    the per-reciter move still surface in the panel."""
    return f"jobs/ts/{job_id}.json"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Private bucket holding the MFA runtime (mfa-runtime/) + the staged job code
# (code/). Mounted read-only at /aux in the job.
ALIGNER_BUCKET = os.environ.get("INSPECTOR_ALIGNER_BUCKET", "hetchyy/aligner-bucket")

# Job image. Two modes, selected by ``INSPECTOR_JOB_IMAGE``:
#   - Prebuilt mode (set ``INSPECTOR_JOB_IMAGE`` to the HF Docker Space
#     ``hf.co/spaces/hetchyy/quran-ts-job``): the MFA framework + pip deps are
#     baked into ``/env`` (see .local/spaces/quran_ts_job/Dockerfile). No ~300 MB
#     conda solve per launch — the image is pulled from cache (~30-60 s). The
#     gitignored acoustic MODEL is NOT baked; it stays bucket-mounted at /aux, so
#     the image is open-source-only. The Space is PUBLIC: HF Jobs cannot pull a
#     *private* Space image (verified — private 500s "Failed to call Jobs
#     backend"; public pulls fine), and nothing private is in the image.
#   - Bootstrap mode (default, stock ``condaforge/mambaforge:latest``): installs
#     the stack at runtime via ``_INSTALL``. Stays the default fallback; flip the
#     env to the prebuilt image in each deploy that wants the faster startup.
# Default = the verified prebuilt image (fast startup, no ~300 MB solve).
# Instant rollback: set INSPECTOR_JOB_IMAGE=condaforge/mambaforge:latest
# (or INSPECTOR_JOB_IMAGE_BOOTSTRAP=1) to fall back to the runtime install.
JOB_IMAGE = os.environ.get("INSPECTOR_JOB_IMAGE", "hf.co/spaces/hetchyy/quran-ts-job")
# Whether the image still needs the runtime conda/pip install. True only for the
# stock mambaforge base; the prebuilt Space already has /env.
_NEEDS_BOOTSTRAP = (
    os.environ.get("INSPECTOR_JOB_IMAGE_BOOTSTRAP",
                   "1" if "mambaforge" in JOB_IMAGE else "0") == "1"
)
JOB_FLAVOR = os.environ.get("INSPECTOR_TS_JOB_FLAVOR", "cpu-upgrade")
JOB_TIMEOUT = os.environ.get("INSPECTOR_TS_JOB_TIMEOUT", "2h")
_REPO_ROOT = Path(__file__).resolve().parents[3]

# python 3.11 pin: 3.14 breaks MFA (Path.copy() conflict). quranic-phonemizer
# is public on PyPI. The MFA acoustic model is pulled from the bucket at
# runtime (not installed), keeping the gitignored stack out of any image.
# Bootstrap-mode only — the prebuilt image bakes this same set into /env.
_INSTALL = (
    "mamba install -y -c conda-forge python=3.11 montreal-forced-aligner "
    "&& /opt/conda/bin/pip install gradio soundfile tgt numpy PyYAML requests psutil "
    "'quranic-phonemizer>=2.0' 'huggingface_hub>=1.8.0' "
    "&& mkdir -p /scratch"
)
_ENTRYPOINT = "python /aux/code/scripts/jobs/generate_timestamps.py"


def _job_command() -> list[str]:
    """Container command. Bootstrap mode installs the stack first; prebuilt mode
    activates the baked ``/env`` conda env and runs the entrypoint directly."""
    if _NEEDS_BOOTSTRAP:
        return ["bash", "-lc", f"{_INSTALL} && {_ENTRYPOINT}"]
    return ["bash", "-lc",
            f"mkdir -p /scratch && conda run -p /env --no-capture-output {_ENTRYPOINT}"]


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


def _resolve_launched_job_id(slug: str) -> str | None:
    """Return the canonical HF job id for the most recently launched job for
    ``slug``. ``run_job()``'s returned id is transient and does not match the
    container's injected ``JOB_ID``; ``list_jobs`` reports the canonical id
    (the one the job self-writes its record under). Picks the newest
    non-terminal job with our label."""
    from huggingface_hub import list_jobs

    try:
        candidates = []
        for job in list_jobs():
            labels = getattr(job, "labels", {}) or {}
            if labels.get("task") == "timestamps" and labels.get("reciter") == slug:
                candidates.append(job)
        # Prefer the newest non-terminal job with our label (the one just
        # launched). If the new job isn't listed yet (brief post-submit race),
        # the caller falls back to run_job()'s id — job_status() later reconciles
        # via the terminal-status backstop once the canonical id is known.
        for job in reversed(candidates):
            if _status_str(job) not in _TERMINAL:
                return _job_id(job)
        if candidates:
            return _job_id(candidates[-1])
    except Exception as exc:  # never block a launch on a list failure
        log.warning("resolve launched job id for %s failed: %s", slug, exc)
    return None


def launch(slug: str, *, settings: TsJobSettings, webhook_base: str | None = None) -> dict:
    """Launch the timestamps job for ``slug`` and link its id to the reciter.

    ``settings`` carries the admin's form choices (beams, persist_audio,
    gen_peaks, + advanced workers/flavor/timeout/batch_size/download_workers).
    Writes the initial ``running`` job record at launch so the panel can show
    it even if the job dies before self-writing. Returns ``{"job_id", "url"}``.
    Caller must enforce single-flight via ``running_job_for`` first.

    Does NOT transition the reciter — it stays UNDER_REVIEW (marked_ready) while
    the job runs. On *success* the reciter is published by
    ``complete_timestamps_job`` (webhook + poll fallback). ``webhook_base`` is
    the public URL root the route resolves from ``request.url_root`` (deployed
    ProxyFix → ``https://…hf.space/``); combined with the
    ``INSPECTOR_WEBHOOK_SECRET`` env it's threaded to the job so it can POST the
    completion callback. Both absent (dev) → no callback; the poll fallback
    releases instead.
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
    if settings.beams:
        env["BEAMS"] = ",".join(str(b) for b in settings.beams)
    if settings.persist_audio:
        env["PERSIST_AUDIO"] = "1"
    if settings.gen_peaks:
        env["GEN_PEAKS"] = "1"
    # Advanced overrides: form value > server env default.
    workers = settings.workers or _env_int("INSPECTOR_TS_JOB_WORKERS")
    if workers:
        env["WORKERS"] = str(workers)
    if settings.batch_size:
        env["BATCH_SIZE"] = str(settings.batch_size)
    if settings.download_workers:
        env["DOWNLOAD_WORKERS"] = str(settings.download_workers)
    flavor = settings.flavor or JOB_FLAVOR
    timeout = settings.timeout or JOB_TIMEOUT

    secrets = {"HF_TOKEN": get_token()}
    # Completion callback: thread the webhook URL + shared secret only when both
    # the server has a secret configured AND we resolved a public base URL. The
    # job POSTs {slug, job_id, status:"succeeded"} here on success so the
    # reciter publishes immediately (the poll fallback covers the rest).
    webhook_secret = os.environ.get("INSPECTOR_WEBHOOK_SECRET", "").strip()
    if webhook_secret and webhook_base:
        env["INSPECTOR_WEBHOOK_URL"] = (
            webhook_base.rstrip("/") + "/api/webhooks/ts-job-complete"
        )
        secrets["INSPECTOR_WEBHOOK_SECRET"] = webhook_secret

    job = run_job(
        image=JOB_IMAGE,
        command=_job_command(),
        flavor=flavor,
        timeout=timeout,
        env=env,
        secrets=secrets,
        volumes=[
            Volume(type="bucket", source=bucket, mount_path="/data"),
            Volume(type="bucket", source=ALIGNER_BUCKET, mount_path="/aux", read_only=True),
        ],
        labels={"task": "timestamps", "reciter": slug},
    )
    # CAVEAT: ``run_job()`` returns a transient submission id that does NOT
    # match the container's injected ``JOB_ID`` (the canonical id ``list_jobs``
    # / ``inspect_job`` use, and the one the job self-writes its record under).
    # Resolve the canonical id from the freshly-labelled job so the launcher,
    # the reciter link, and the job's self-written record all agree.
    job_id = _resolve_launched_job_id(slug) or _job_id(job)
    url = getattr(job, "url", None)
    if job_id:
        state_service.record_timestamps_job(slug, job_id)
        # Persist the launch record up front (status=running). The job
        # overwrites it on completion; job_status() backstops if it's killed.
        _write_job_record(TsJobRecord(
            job_id=job_id, slug=slug,
            settings=settings.model_copy(update={"flavor": flavor, "timeout": timeout}),
            status="running", started_at=_now_iso(), url=url,
        ))
    log.info("launched timestamps job %s for %s (flavor=%s)", job_id, slug, flavor)
    return {"job_id": job_id, "url": url}


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _write_job_record(rec: TsJobRecord) -> None:
    """Write the durable job record to the bucket (best-effort)."""
    try:
        get_backend().write_json_atomic(
            _job_record_path(rec.slug, rec.job_id), rec.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001
        log.warning("write job record %s failed: %s", rec.job_id, exc)


def _read_record_bytes(slug: str, job_id: str) -> bytes | None:
    """Read the record bytes, preferring the per-reciter path and falling back
    to the legacy top-level ``jobs/ts/`` location for pre-move records."""
    backend = get_backend()
    for path in (_job_record_path(slug, job_id), _legacy_job_record_path(job_id)):
        try:
            return backend.read_bytes(path)
        except StorageNotFound:
            continue
        except Exception as exc:  # noqa: BLE001
            log.warning("read job record %s failed: %s", job_id, exc)
            return None
    return None


def read_job_record(slug: str, job_id: str) -> dict | None:
    """Return the persisted record for one job, or None if absent/unreadable."""
    raw = _read_record_bytes(slug, job_id)
    if raw is None:
        return None
    try:
        return TsJobRecord.model_validate(json.loads(raw)).model_dump(exclude_none=True)
    except Exception:  # noqa: BLE001 — tolerate older/forward shapes
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return None


def list_job_records(slug: str) -> list[dict]:
    """Persisted records for every job linked to ``slug`` (newest first).

    Reads ``reciters/<slug>/jobs/ts/<id>.json`` for each id in the reciter's
    ``timestamps_job_ids``. Missing records (e.g. a launch that never wrote)
    surface as a minimal stub so the panel can still show the id."""
    row = state_service.get_row(slug)
    ids = list(getattr(row, "timestamps_job_ids", []) or []) if row else []
    out: list[dict] = []
    for jid in ids:
        rec = read_job_record(slug, jid)
        out.append(rec or {"job_id": jid, "slug": slug, "type": "ts",
                           "status": "unknown"})
    out.reverse()  # timestamps_job_ids is append-order → newest last
    return out


def job_status(slug: str, job_id: str, *, log_tail: int = 400) -> dict:
    """Live status + bounded log tail for a job (HF is authoritative).

    Backstop: when HF reports a terminal status but the persisted record is
    still ``running`` (job was hard-killed / OOM'd before self-writing), rewrite
    the record with the terminal status + captured log tail so the panel's
    history stays accurate after HF log retention expires.
    """
    from huggingface_hub import fetch_job_logs, inspect_job

    info = inspect_job(job_id=job_id)
    status = _status_str(info)
    # Canonical HF job page URL (keyed on the id we pass, so always correct).
    # Surfaced so the panel can link out — HF streams logs live there, whereas
    # fetch_job_logs only returns the tail in bulk near completion.
    url = getattr(info, "url", None)
    logs: list[str] = []
    truncated = False
    try:
        for line in fetch_job_logs(job_id=job_id):
            logs.append(line)
            if len(logs) > log_tail:
                logs.pop(0)
                truncated = True
    except Exception as exc:
        log.warning("fetch_job_logs(%s) failed: %s", job_id, exc)

    if status in _TERMINAL:
        existing = read_job_record(slug, job_id)
        base = dict(existing) if existing else {"job_id": job_id, "slug": slug, "type": "ts"}
        changed = False
        # The job self-writes its terminal status + timestamps but NOT its logs;
        # if it was hard-killed (OOM/timeout) it may still read running/unknown.
        # Reconcile both, idempotently — only rewrite when something actually changed.
        if existing is None or existing.get("status") in (None, "running", "unknown"):
            base["status"] = status
            base.setdefault("ended_at", _now_iso())
            changed = True
        if logs and not base.get("logs"):
            base["logs"] = logs
            base["log_truncated"] = truncated
            changed = True
        if changed:
            try:
                _write_job_record(TsJobRecord.model_validate(base))
            except Exception as exc:  # noqa: BLE001
                log.warning("backstop record %s failed: %s", job_id, exc)

    # Auto-release fallback: if the job finished cleanly, publish the reciter.
    # Idempotent + best-effort — the webhook is the primary trigger in prod;
    # this catches dev (job can't reach localhost) when the drawer is polling,
    # and any missed/late webhook. Never let a release failure break status.
    if status in _TERMINAL_SUCCESS:
        try:
            complete_timestamps_job(slug, job_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("auto-release on poll for %s failed: %s", slug, exc)

    return {"job_id": job_id, "status": status, "url": url, "logs": logs,
            "log_truncated": truncated}


def complete_timestamps_job(slug: str, job_id: str) -> dict:
    """Publish ``slug`` after its timestamps job succeeded. Idempotent.

    The single auto-release path, reached from both the job-completion webhook
    (prod) and the ``job_status`` poll fallback (dev / missed webhook). Reads
    the row first and only fires when it's genuinely publishable, so a
    double-fire (webhook + poll, or two concurrent webhooks) no-ops the loser:

    - ``released`` → already done, no-op.
    - ``under_review`` + ``marked_ready`` + at least one shard on the bucket →
      ``reciter.published`` (→ released) via ``SYSTEM_ACTOR`` (role OWNER, so
      the ``reciter.publish`` gate passes).
    - anything else (not marked_ready, no shards, other state) → log + no-op.

    The ``transition()`` call is wrapped in ``StateError`` handling to absorb
    the TOCTOU window where two callers both read ``under_review`` before
    either commits (the single-writer + ``BEGIN IMMEDIATE`` serializes them; the
    loser's handler raises ``_state_precondition`` once the row is already
    released). Returns ``{slug, state, released: bool, reason?}``.
    """
    # Lazy import: SYSTEM_ACTOR lives in the segments package, which pulls
    # bucket loaders — keep it off this module's import-time graph.
    from services.segments.auto_detect import SYSTEM_ACTOR

    row = state_service.get_row(slug)
    if row is None:
        return {"slug": slug, "state": None, "released": False,
                "reason": "unknown slug"}
    if row.state.value == "released":
        return {"slug": slug, "state": "released", "released": False,
                "reason": "already released"}
    if row.state.value != "under_review" or not row.marked_ready:
        log.info("complete_timestamps_job(%s): not publishable (state=%s "
                 "marked_ready=%s) — leaving as-is", slug, row.state.value,
                 row.marked_ready)
        return {"slug": slug, "state": row.state.value, "released": False,
                "reason": "not marked-ready / wrong state"}
    if not _has_any_shard(slug):
        log.warning("complete_timestamps_job(%s): job %s succeeded but no "
                    "timestamps shards on the bucket — not publishing",
                    slug, job_id)
        return {"slug": slug, "state": row.state.value, "released": False,
                "reason": "no shards"}

    try:
        new_row = state_service.transition(
            slug, "reciter.published", actor=SYSTEM_ACTOR,
            payload={"job_id": job_id},
        )
    except state_service.StateError as exc:
        # Lost a double-fire race, or the row changed under us (e.g. reviewer
        # un-marked). Benign — the winning caller (or a re-run) handles it.
        log.info("complete_timestamps_job(%s): transition skipped: %s", slug, exc)
        return {"slug": slug, "state": (state_service.get_row(slug) or row).state.value,
                "released": False, "reason": "transition skipped"}
    log.info("complete_timestamps_job(%s): published (job=%s)", slug, job_id)
    return {"slug": slug, "state": new_row.state.value, "released": True}


def _has_any_shard(slug: str) -> bool:
    """True if at least one per-chapter timestamps shard exists for ``slug``.

    Guards auto-release against a job that exits 0 without writing shards. One
    cheap bucket listing of ``reciters/<slug>/timestamps/``."""
    try:
        names = get_backend().list_dir(f"reciters/{slug}/timestamps")
        return any(str(n).endswith((".json", ".json.gz")) for n in names)
    except StorageNotFound:
        return False
    except Exception as exc:  # noqa: BLE001 — never let the check break release
        log.warning("shard-existence check for %s failed: %s", slug, exc)
        return False
