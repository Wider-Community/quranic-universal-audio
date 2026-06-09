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
from collections.abc import Callable
from pathlib import Path

from services.storage.hf_bucket import StorageNotFound, get_backend

log = logging.getLogger("inspector")


# ---------------------------------------------------------------------------
# Terminal HF stages.
# ---------------------------------------------------------------------------

TERMINAL = (
    "succeeded",
    "completed",
    "failed",
    "error",
    "errored",
    "timed-out",
    "timeout",
    "stopped",
    "canceled",
    "cancelled",
    "deleted",
)
TERMINAL_SUCCESS = ("succeeded", "completed")

# Reciter-label sentinels for jobs that aren't scoped to a single slug:
# ``_global`` (cut_release) and ``_batch`` (hf_publish_batch). Both normalize
# to ``slug=None`` on the wire.
GLOBAL_SLUGS = (None, "_global", "_batch")


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
    )
    == "1"
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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


_hf_namespace: str | None = None
_hf_namespace_resolved = False


def hf_job_url(job_id: str) -> str | None:
    """Best-effort HF job page URL ``https://huggingface.co/jobs/<ns>/<id>``.

    Used to backfill ``url`` for records sourced from the DB / a backfill (which
    never captured the live job object's ``.url``). The namespace is the account
    the HF token runs jobs under — resolved once via ``whoami()`` and cached.
    Returns None when the namespace can't be resolved (link is then hidden)."""
    global _hf_namespace, _hf_namespace_resolved
    if not job_id:
        return None
    if not _hf_namespace_resolved:
        _hf_namespace_resolved = True
        try:
            from huggingface_hub import whoami

            _hf_namespace = (whoami() or {}).get("name")
        except Exception as exc:
            log.warning("hf_job_url: whoami() failed: %s", exc)
            _hf_namespace = None
    if not _hf_namespace:
        return None
    return f"https://huggingface.co/jobs/{_hf_namespace}/{job_id}"


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
            if slug is None and kind is not None and j_slug not in GLOBAL_SLUGS:
                continue
            status = hf_status_str(job)
            if status in ("running", "pending", "updating"):
                return j_kind, (hf_job_id(job) or "")
    except Exception as exc:
        log.warning("running_job_for(kind=%s, slug=%s) failed: %s", kind, slug, exc)
    return None


def kind_for_job(job_id: str) -> str | None:
    """Return the ``labels.task`` (kind) of the HF Job ``job_id``, or None.

    Used by the generic release-job cancel route to pick the right capability
    gate per kind without the caller already knowing the kind."""
    from huggingface_hub import list_jobs

    try:
        for job in list_jobs():
            if (hf_job_id(job) or "") == job_id:
                labels = getattr(job, "labels", {}) or {}
                return labels.get("task")
    except Exception as exc:
        log.warning("kind_for_job(%s) failed: %s", job_id, exc)
    return None


def kind_and_slug_for_job(job_id: str) -> tuple[str | None, str | None]:
    """Return ``(kind, slug)`` from an HF job's labels, ``(None, None)`` if not
    found. ``slug`` is None for global kinds (``_global`` / ``_batch``). Used by
    the cancel route to stamp the right job record terminal."""
    from huggingface_hub import list_jobs

    try:
        for job in list_jobs():
            if (hf_job_id(job) or "") == job_id:
                labels = getattr(job, "labels", {}) or {}
                slug = labels.get("reciter")
                if slug in ("_global", "_batch"):
                    slug = None
                return labels.get("task"), slug
    except Exception as exc:
        log.warning("kind_and_slug_for_job(%s) failed: %s", job_id, exc)
    return None, None


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
    from huggingface_hub import list_jobs

    from services.storage import cache as _cache

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
            if slug in ("_global", "_batch"):
                slug = None
            # ``created_at`` on the HF Jobs SDK is a datetime; ISO-format it
            # for the wire. ``started_at`` is set when execution actually
            # begins (post-pending) — prefer it when present.
            started = getattr(job, "started_at", None) or getattr(job, "created_at", None)
            if started is not None and not isinstance(started, str):
                try:
                    started = started.isoformat()
                except Exception:
                    started = None
            out.append(
                {
                    "kind": j_kind,
                    "slug": slug,
                    "job_id": hf_job_id(job) or "",
                    "started_at": started,
                    # HF job page URL — the FE renders an "Open on HF" link so
                    # the operator can watch logs / the job stream directly.
                    "url": getattr(job, "url", None),
                }
            )
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


# Files every launch MUST get into ``aligner-bucket/code/`` for the HF Job to
# run. Loud preflight prevents silent skips when the deployed image is missing
# something (e.g. a new entrypoint shipped but Dockerfile not updated).
REQUIRED_ENTRYPOINTS = (
    "qua_jobs/generate_timestamps.py",
    "qua_jobs/publish_hf.py",
    "qua_jobs/publish_hf_batch.py",
    "qua_jobs/refresh_hf_catalog.py",
    "qua_jobs/cut_release.py",
    "qua_jobs/shard.py",
    "qua_jobs/check_updates.py",
)
REQUIRED_STATIC_FILES = (
    "data/qpc_hafs.json",
    "data/surah_info.json",
    ".github/config/repo.yml",
    "docs/templates/release_body.md",
    "docs/templates/hf_dataset_card.md",
    "LICENSE",
)


class JobStagingError(RuntimeError):
    """Raised when stage_job_code can't satisfy its file contract.

    Surfaced before ``run_job`` so the operator gets a clear deploy-fix
    message instead of an opaque ``No such file or directory`` from the
    container.
    """


def _is_lfs_pointer(p: Path) -> bool:
    """True if ``p`` is a git-LFS pointer stub, not the real bytes. On an HF
    Space build, ``*.gz`` files are LFS'd by extension and reach the image
    unsmudged (a ~130-byte ``version https://git-lfs…`` stub)."""
    try:
        with p.open("rb") as f:
            return f.read(40).startswith(b"version https://git-lfs")
    except OSError:
        return False


def _resolve_required_static(rel: str) -> tuple[Path | None, bytes | None]:
    """Resolve a REQUIRED_STATIC_FILES entry to either a local path or in-memory bytes.

    For ``data/qpc_hafs.json``: prefer the uncompressed file on disk (dev +
    image when shipped). Otherwise decompress the sibling ``.gz`` on the fly.
    On a deployed Space the ``.gz`` can arrive as an LFS pointer (unsmudged);
    in that case the real bytes live in the bucket at ``reference/qpc_hafs.json.gz``,
    so fall back to reading them from there.
    """
    import gzip as _gzip

    src = REPO_ROOT / rel
    if src.exists() and not _is_lfs_pointer(src):
        return src, None
    if rel == "data/qpc_hafs.json":
        compressed = REPO_ROOT / "data" / "qpc_hafs.json.gz"
        if compressed.exists():
            if not _is_lfs_pointer(compressed):
                return None, _gzip.decompress(compressed.read_bytes())
            # .gz present but an LFS pointer (deployed image) → real bytes
            # live in the bucket reference.
            from services.storage.hf_bucket import get_backend

            return None, _gzip.decompress(get_backend().read_bytes("reference/qpc_hafs.json.gz"))
    return None, None


def stage_job_code() -> None:
    """Upload ``qua_shared`` + ``qua_jobs`` + static refs to
    ``aligner-bucket/code/`` so the HF Job container can import them.

    Walks ``qua_shared`` and ``qua_jobs`` for every ``.py`` then appends
    the curated static files. Raises ``JobStagingError`` BEFORE the upload if
    any required entrypoint or static file can't be resolved on disk —
    catches the "Dockerfile missing a COPY" class of regression at launch.

    Idempotent — Xet de-dupes unchanged content.
    """
    from huggingface_hub import batch_bucket_files

    adds: list[tuple[str, str]] = []
    seen_targets: set[str] = set()
    tmp_files: list[Path] = []

    for sub in ("qua_shared", "qua_jobs"):
        base = REPO_ROOT / sub
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            adds.append((str(path), f"code/{rel}"))
            seen_targets.add(f"code/{rel}")

    import tempfile as _tempfile

    for rel in REQUIRED_STATIC_FILES:
        path, blob = _resolve_required_static(rel)
        target = f"code/{rel}"
        if path is not None:
            adds.append((str(path), target))
            seen_targets.add(target)
        elif blob is not None:
            fd, tmp_path = _tempfile.mkstemp(prefix="stagedref_", suffix=Path(rel).name)
            os.write(fd, blob)
            os.close(fd)
            tmp_files.append(Path(tmp_path))
            adds.append((tmp_path, target))
            seen_targets.add(target)

    expected = {f"code/{p}" for p in REQUIRED_ENTRYPOINTS + REQUIRED_STATIC_FILES}
    missing = sorted(expected - seen_targets)
    if missing:
        for p in tmp_files:
            p.unlink(missing_ok=True)
        raise JobStagingError(
            "stage_job_code: required files missing from the running image: "
            f"{missing}. Likely cause: inspector/Dockerfile doesn't COPY one "
            "of these paths. Fix the Dockerfile, redeploy the Space, then retry."
        )

    try:
        batch_bucket_files(ALIGNER_BUCKET, add=adds)
        log.info("staged %d job-code files to %s/code/", len(adds), ALIGNER_BUCKET)
    finally:
        for p in tmp_files:
            p.unlink(missing_ok=True)


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


#: Kinds whose completion CAN run on the poll path — their ``complete()`` does an
#: idempotent DB write from ``(slug, job_id)`` alone. ``cut_release`` is excluded
#: on purpose: it is webhook-only (its complete() needs the full members payload
#: the poll path cannot reconstruct).
POLL_COMPLETABLE_KINDS = ("ts", "hf_publish", "hf_publish_batch", "refresh_catalog")


def register_poll_handlers() -> None:
    """Register every poll-completable kind's handler in one place.

    Single source of truth for boot wiring so a kind can't be silently dropped —
    ``ts`` was, which left automated TS regens (no webhook, no open drawer) with
    no completion path at all: ``produced_at`` never advanced, so the recitation
    stayed permanently behind-edits and the auto-regen automation relaunched every
    tick. Deferred imports avoid a circular import at module load."""
    from . import hf_publish, hf_publish_batch, refresh_catalog, ts

    ts.register()
    hf_publish.register()
    hf_publish_batch.register()
    refresh_catalog.register()


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
        slug_arg = None if slug in ("_global", "_batch") else slug
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
