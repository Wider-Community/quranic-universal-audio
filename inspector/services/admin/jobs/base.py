"""Shared infrastructure for kind-dispatched HF Job launches.

One file per ``kind`` owns its launch params + ``complete()`` handler. This
module factors out the cross-kind plumbing: HF Job mechanics (run_job,
status polling, log fetching, terminal-state dispatch), per-slug single-flight
across kinds + global single-flight for ``cut_release``, the
``reciters/<slug>/jobs/<kind>/<id>.json`` record paths, and the webhook /
poll-fallback completion router.

The HF Job container NEVER writes the DB — it writes bucket artifacts only.
DB mutations happen via the per-kind ``complete()`` handlers, called either
by the webhook receiver in ``routes/webhooks`` or by the in-process poll
fallback (every 120s) defined here.
"""

from __future__ import annotations

import datetime
import logging
import os
import threading
from pathlib import Path
from typing import Callable

from services.storage.hf_bucket import StorageNotFound, get_backend

log = logging.getLogger("inspector")


# ---------------------------------------------------------------------------
# Terminal HF stages.
# ---------------------------------------------------------------------------

TERMINAL = (
    "succeeded", "completed",
    "failed", "error", "errored",
    "timed-out", "timeout",
    "stopped", "canceled", "cancelled",
    "deleted",
)
TERMINAL_SUCCESS = ("succeeded", "completed")


# ---------------------------------------------------------------------------
# Repo root + aligner bucket + base job image. Same defaults as the legacy
# timestamps_jobs.py — every kind re-uses them.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[4]
ALIGNER_BUCKET = os.environ.get("INSPECTOR_ALIGNER_BUCKET", "hetchyy/aligner-bucket")
JOB_IMAGE = os.environ.get("INSPECTOR_JOB_IMAGE", "hf.co/spaces/hetchyy/quran-ts-job")
NEEDS_BOOTSTRAP = (
    os.environ.get(
        "INSPECTOR_JOB_IMAGE_BOOTSTRAP",
        "1" if "mambaforge" in JOB_IMAGE else "0",
    ) == "1"
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def hf_job_id(job) -> str | None:
    return getattr(job, "id", None) or getattr(job, "job_id", None)


def hf_status_str(info) -> str:
    status = getattr(info, "status", None)
    stage = getattr(status, "stage", None)
    return str(stage if stage is not None else status or "").lower()


# ---------------------------------------------------------------------------
# Job-record paths: ``reciters/<slug>/jobs/<kind>/<job_id>.json`` for per-slug
# kinds, ``jobs/_global/<kind>/<job_id>.json`` for global kinds (cut_release).
# ---------------------------------------------------------------------------


def job_record_path(kind: str, slug: str | None, job_id: str) -> str:
    if slug is None:
        return f"jobs/_global/{kind}/{job_id}.json"
    return f"reciters/{slug}/jobs/{kind}/{job_id}.json"


def legacy_job_record_path(kind: str, job_id: str) -> str:
    """Pre-2026-05 top-level path (kept for back-compat reads, never written)."""
    return f"jobs/{kind}/{job_id}.json"


# ---------------------------------------------------------------------------
# Single-flight registry: per-slug across kinds + global lock for cut_release.
# ---------------------------------------------------------------------------


def running_job_for(*, kind: str | None = None, slug: str | None = None) -> tuple[str, str] | None:
    """Return ``(kind, job_id)`` of an in-flight job matching the filter, else None.

    ``kind=None, slug=X`` → any kind for that slug (cross-kind mutex).
    ``kind=K, slug=X``    → that specific kind for that slug.
    ``kind=K, slug=None`` → any global instance of that kind (e.g. cut_release).
    """
    from huggingface_hub import list_jobs

    try:
        for job in list_jobs():
            labels = getattr(job, "labels", {}) or {}
            j_kind = labels.get("task")
            j_slug = labels.get("reciter")
            if kind is not None and j_kind != kind:
                continue
            if slug is not None and j_slug != slug:
                continue
            if slug is None and kind is not None and j_slug not in (None, "_global"):
                continue
            status = hf_status_str(job)
            if status in ("running", "pending", "updating"):
                return j_kind, (hf_job_id(job) or "")
    except Exception as exc:
        log.warning("running_job_for(kind=%s, slug=%s) failed: %s", kind, slug, exc)
    return None


def list_in_flight_jobs(kinds: tuple[str, ...]) -> list[dict]:
    """Return ``[{kind, slug, job_id, started_at}, ...]`` for live jobs whose
    ``labels.task`` is in ``kinds``. ``slug`` is None for global kinds.

    Used by the Releases-tab status endpoint to surface "what's running right
    now" to the operator. Wrapped in a 5 s TTL cache
    (``services/storage/cache.py``) — ``list_jobs()`` is rate-limited at the
    HF side and the FE polls every 30 s; the cache absorbs the poll + same-
    page re-renders cheaply. ``hf_publish.launch`` / ``cut_release.launch``
    and their ``complete()`` handlers explicitly invalidate so a freshly
    launched job (or a just-terminated one) shows up immediately.
    """
    from services.storage import cache as _cache
    from huggingface_hub import list_jobs

    cached = _cache.get_in_flight_jobs_cache(kinds)
    if cached is not None:
        return cached
    out: list[dict] = []
    try:
        for job in list_jobs():
            labels = getattr(job, "labels", {}) or {}
            j_kind = labels.get("task")
            if j_kind not in kinds:
                continue
            status = hf_status_str(job)
            if status not in ("running", "pending", "updating"):
                continue
            slug = labels.get("reciter")
            if slug == "_global":
                slug = None
            # ``created_at`` on the HF Jobs SDK is a datetime; ISO-format it
            # for the wire. ``started_at`` is set when execution actually
            # begins (post-pending) — prefer it when present.
            started = (
                getattr(job, "started_at", None)
                or getattr(job, "created_at", None)
            )
            if started is not None and not isinstance(started, str):
                try:
                    started = started.isoformat()
                except Exception:
                    started = None
            out.append({
                "kind": j_kind,
                "slug": slug,
                "job_id": hf_job_id(job) or "",
                "started_at": started,
            })
    except Exception as exc:
        log.warning("list_in_flight_jobs(%s) failed: %s", kinds, exc)
        # Don't cache failures — the next call should retry the HF API.
        return []
    _cache.set_in_flight_jobs_cache(kinds, out)
    return out


# ---------------------------------------------------------------------------
# Job-record I/O — kind-aware. Read prefers the v2 per-kind path, falls back
# to the legacy top-level path so old records still surface.
# ---------------------------------------------------------------------------


def write_record_bytes(kind: str, slug: str | None, job_id: str, payload: bytes) -> None:
    try:
        get_backend().write_bytes(job_record_path(kind, slug, job_id), payload)
    except Exception as exc:
        log.warning("write job record %s/%s/%s failed: %s", kind, slug, job_id, exc)


def read_record_bytes(kind: str, slug: str | None, job_id: str) -> bytes | None:
    backend = get_backend()
    for path in (
        job_record_path(kind, slug, job_id),
        legacy_job_record_path(kind, job_id),
    ):
        try:
            return backend.read_bytes(path)
        except StorageNotFound:
            continue
        except Exception as exc:
            log.warning("read job record %s failed: %s", job_id, exc)
            return None
    return None


# ---------------------------------------------------------------------------
# Stage shared script code once per launch. Same idempotent pattern as v1.
# ---------------------------------------------------------------------------


def stage_job_code() -> None:
    """Upload scripts/lib + scripts/jobs + static refs to
    ``aligner-bucket/code/`` so the HF Job container can import them.
    Idempotent (Xet skips unchanged content).

    Static refs (``data/qpc_hafs.json`` + ``data/surah_info.json``) are
    required by ``publish_hf.py`` for text derivation and by ``cut_release.py``
    for static-refs hashing + the release bundle. They're shipped under
    ``code/data/`` so the job can read them at ``/aux/code/data/<file>``.
    """
    from huggingface_hub import batch_bucket_files

    adds: list[tuple[str, str]] = []
    for sub in ("scripts/lib", "scripts/jobs"):
        base = REPO_ROOT / sub
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            adds.append((str(path), f"code/{rel}"))
    # Static refs — small enough (qpc_hafs.json ~12 MB, surah_info.json ~400 KB)
    # that re-uploading on every launch is fine when unchanged Xet de-dups them.
    for ref_name in ("qpc_hafs.json", "surah_info.json"):
        ref_path = REPO_ROOT / "data" / ref_name
        if ref_path.exists():
            adds.append((str(ref_path), f"code/data/{ref_name}"))
    # LICENSE is shipped as a GH release asset by cut_release.py — needs to be
    # reachable in the staged code dir at /aux/code/LICENSE.
    license_path = REPO_ROOT / "LICENSE"
    if license_path.exists():
        adds.append((str(license_path), "code/LICENSE"))
    if adds:
        batch_bucket_files(ALIGNER_BUCKET, add=adds)
        log.info("staged %d job-code files to %s/code/", len(adds), ALIGNER_BUCKET)


# ---------------------------------------------------------------------------
# Poll-fallback worker registry + driver.
#
# Each kind registers a (TERMINAL_SUCCESS, complete()) handler; the worker
# loops over live HF Jobs every 120s and dispatches terminal completions to
# the right handler. Both this path AND the webhook receiver call the same
# complete() — idempotent on the table's UNIQUE(kind, slug, version) index.
# ---------------------------------------------------------------------------

PollHandler = Callable[[str | None, str], None]
_HANDLERS: dict[str, PollHandler] = {}
POLL_INTERVAL_SECONDS = 120


def register_handler(kind: str, fn: PollHandler) -> None:
    """Register a kind's terminal-success complete() handler for poll dispatch.

    ``fn(slug, job_id)`` is called once per terminal job; ``slug`` is None for
    global kinds (``cut_release``). The handler must be idempotent — both
    webhook + poll can fire concurrently.
    """
    _HANDLERS[kind] = fn


def _poll_terminal_jobs() -> None:
    """Single tick: scan running HF jobs, dispatch any newly terminal to its handler."""
    from huggingface_hub import list_jobs

    try:
        jobs = list(list_jobs())
    except Exception as exc:
        log.warning("poll worker list_jobs failed: %s", exc)
        return
    for job in jobs:
        labels = getattr(job, "labels", {}) or {}
        kind = labels.get("task")
        slug = labels.get("reciter")
        if kind not in _HANDLERS:
            continue
        status = hf_status_str(job)
        if status not in TERMINAL_SUCCESS:
            continue
        jid = hf_job_id(job)
        if not jid:
            continue
        slug_arg = None if slug in (None, "_global") else slug
        try:
            _HANDLERS[kind](slug_arg, jid)
        except Exception as exc:
            log.warning("poll handler %s(%s, %s) failed: %s", kind, slug_arg, jid, exc)


_poll_thread: threading.Thread | None = None
_poll_stop = threading.Event()


def start_poll_worker() -> None:
    """Idempotent — start a single daemon thread that polls every 120s."""
    global _poll_thread
    if _poll_thread is not None and _poll_thread.is_alive():
        return

    def _loop() -> None:
        while not _poll_stop.wait(POLL_INTERVAL_SECONDS):
            _poll_terminal_jobs()

    _poll_thread = threading.Thread(target=_loop, name="jobs-poll-worker", daemon=True)
    _poll_thread.start()
    log.info("jobs poll worker started (interval=%ds)", POLL_INTERVAL_SECONDS)


def stop_poll_worker() -> None:
    """Used by tests."""
    _poll_stop.set()
