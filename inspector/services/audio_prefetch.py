"""Background audio prefetch + 1-week sweeper for in-review reciters.

Trigger events (registered in ``app.py`` as a post-transition hook):

* ``state → AWAITING_REVIEW`` (any path) — enqueue the slug for prefetch.
* ``reciter.claimed`` → ``UNDER_REVIEW`` — lazy fallback enqueue iff the
  ``_done.json`` sentinel isn't present yet.
* ``reciter.timestamps_completed`` → ``RELEASED`` — stamp the row with
  ``prefetch_purge_at = now + 7d`` (handled in ``services.state``).
* ``admin.unlocked_for_revision`` → ``AWAITING_REVIEW`` — re-enqueue and
  rely on the AWAITING_REVIEW handler to clear ``prefetch_purge_at``.

Single-FIFO queue, max one active job. Reuses ``cache._AUDIO_DL_PROGRESS``
for live progress so the existing prepare-audio status endpoint keeps working
as a free admin observability surface.

Sweeper: a daemon thread wakes hourly, scans the in-memory state store, and
deletes ``wip/<slug>/{audio,peaks}/`` for rows whose ``prefetch_purge_at`` is
in the past. Single-worker invariant guarantees one sweeper per deploy.

No Flask imports.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from config import AUDIO_DL_WORKER_COUNT
from scripts.lib.schemas import Actor, Role
from services import audio_fetch, audio_meta, audit, cache, state, storage_paths
from services.hf_bucket import get_backend

logger = logging.getLogger(__name__)

# ---- System actor for unattended audit appends ----

_SYSTEM_ACTOR = Actor(
    hf_user_id="system",
    login_at_time="audio_prefetch",
    role=Role.MAINTAINER,
)

# ---- Queue + worker state ----

_LOCK = threading.Lock()
_COND = threading.Condition(_LOCK)
_QUEUE: deque[str] = deque()
_ACTIVE: str | None = None
_WORKER_THREAD: threading.Thread | None = None
_WORKER_STARTED = False
_STOPPING = False

# Sweeper handle
_CLEANUP_THREAD: threading.Thread | None = None
_CLEANUP_STARTED = False
_CLEANUP_INTERVAL_S = 3600  # 1 hour


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


def is_prefetched(slug: str) -> bool:
    """Return True iff the ``_done.json`` sentinel exists in the bucket."""
    try:
        return get_backend().exists(storage_paths.prefetch_done_marker_path(slug))
    except Exception as e:  # noqa: BLE001
        logger.warning("is_prefetched(%s) backend probe failed: %s", slug, e)
        return False


def progress(slug: str) -> dict | None:
    """In-flight progress dict written by ``_run_one``. None when no job is
    active or queued for ``slug``."""
    with _LOCK:
        if _ACTIVE != slug and slug not in _QUEUE:
            # Not active and not queued — but the cache might still hold the
            # last-known progress for an already-finished slug. Surface it so
            # admin tooling can see "completed at" without scanning audit.
            return cache.get_audio_dl_progress(slug)
        return cache.get_audio_dl_progress(slug)


def enqueue(slug: str, *, actor: Actor | None = None, force: bool = False) -> bool:
    """Schedule ``slug`` for prefetch. Returns True if newly queued, False if
    already active or queued (idempotent). When ``force`` is True, the
    artifacts get re-fetched even if already present (admin re-trigger).

    Spawns the worker thread on first call.
    """
    actor = actor or _SYSTEM_ACTOR
    _ensure_worker()

    with _LOCK:
        if _ACTIVE == slug or slug in _QUEUE:
            return False
        if not force and is_prefetched(slug):
            # Nothing to do — emit a `queued` audit event with a `skipped`
            # marker so the timeline still reflects the trigger fired.
            _emit("audio_prefetch.queued", slug, actor, {"skipped": True})
            return False
        _QUEUE.append(slug)
        _emit(
            "audio_prefetch.queued",
            slug,
            actor,
            {"force": force, "queue_depth": len(_QUEUE)},
        )
        _COND.notify_all()
        return True


def on_state_transition(before, after, event: str, actor: Actor) -> None:
    """Post-transition hook. Dispatch prefetch + cleanup actions.

    ``before`` may be None (first insert into the state file). ``after`` is
    the freshly-persisted row.
    """
    # ReciterState enum compared by .value to keep this module free of state
    # import cycles (state.py imports audit; audit imports schemas only).
    new_state = after.state.value if hasattr(after.state, "value") else after.state

    # Any path into AWAITING_REVIEW → enqueue prefetch + clear purge stamp if
    # set by a prior RELEASED roundtrip. The actual purge-stamp clearing for
    # admin.unlocked_for_revision happens in the state handler.
    if new_state == "awaiting_review":
        enqueue(after.slug, actor=actor)
        return

    # Lazy fallback: if someone claims a reciter that was never prefetched
    # (e.g. Space rebooted before the alignment_completed hook fired), kick
    # off the job now so segment playback degrades from "CDN every time" to
    # "CDN until we catch up".
    if event == "reciter.claimed" and new_state == "under_review":
        if not is_prefetched(after.slug):
            enqueue(after.slug, actor=actor)


# ----------------------------------------------------------------------
# Worker
# ----------------------------------------------------------------------


def _ensure_worker() -> None:
    global _WORKER_THREAD, _WORKER_STARTED
    if _WORKER_STARTED:
        return
    with _LOCK:
        if _WORKER_STARTED:
            return
        _WORKER_THREAD = threading.Thread(
            target=_worker_loop, name="audio-prefetch", daemon=True
        )
        _WORKER_THREAD.start()
        _WORKER_STARTED = True


def _worker_loop() -> None:
    global _ACTIVE
    while True:
        with _COND:
            while not _QUEUE and not _STOPPING:
                _COND.wait()
            if _STOPPING:
                return
            slug = _QUEUE.popleft()
            _ACTIVE = slug
        try:
            _run_one(slug)
        except Exception:  # noqa: BLE001
            logger.exception("audio_prefetch worker crashed on slug=%s", slug)
        finally:
            with _LOCK:
                _ACTIVE = None
                _COND.notify_all()


def _run_one(slug: str) -> None:
    """Drive one full prefetch job for ``slug``.

    Fans out chapter fetches across a thread pool, mirrors live progress into
    the existing ``_AUDIO_DL_PROGRESS`` cache, and writes the ``_done.json``
    sentinel only after every chapter succeeded. Partial failures keep the
    slug recoverable on the next trigger.
    """
    chapter_urls = audio_meta.chapter_urls(slug)
    if not chapter_urls:
        _emit(
            "audio_prefetch.failed",
            slug,
            _SYSTEM_ACTOR,
            {"reason": "no_chapter_urls"},
        )
        return

    total = len(chapter_urls)
    _emit("audio_prefetch.started", slug, _SYSTEM_ACTOR, {"total": total})
    started_at_ms = audio_fetch.now_ms()

    lock = cache.get_audio_dl_lock()
    with lock:
        cache.set_audio_dl_progress(
            slug,
            {"total": total, "downloaded": 0, "complete": False, "errors": 0},
        )

    errors = 0
    completed = 0
    with ThreadPoolExecutor(max_workers=AUDIO_DL_WORKER_COUNT) as pool:
        futures = {
            pool.submit(audio_fetch.fetch_and_persist_chapter, slug, ch, url): ch
            for ch, url in chapter_urls.items()
        }
        for fut in as_completed(futures):
            chapter = futures[fut]
            try:
                artifact = fut.result()
            except audio_fetch.ChapterFetchError as e:
                errors += 1
                _emit(
                    "audio_prefetch.chapter_failed",
                    slug,
                    _SYSTEM_ACTOR,
                    {"chapter": chapter, "stage": e.stage, "detail": e.detail[:160]},
                    result="error",
                )
            except Exception as e:  # noqa: BLE001
                errors += 1
                _emit(
                    "audio_prefetch.chapter_failed",
                    slug,
                    _SYSTEM_ACTOR,
                    {"chapter": chapter, "stage": "unknown", "detail": str(e)[:160]},
                    result="error",
                )
            else:
                completed += 1
                _emit(
                    "audio_prefetch.chapter_done",
                    slug,
                    _SYSTEM_ACTOR,
                    {
                        "chapter": chapter,
                        "bytes": artifact.bytes_written,
                        "duration_ms": artifact.duration_ms,
                        "ffmpeg_remuxed": artifact.ffmpeg_remuxed,
                    },
                )
            with lock:
                cache.set_audio_dl_progress(
                    slug,
                    {
                        "total": total,
                        "downloaded": completed,
                        "complete": False,
                        "errors": errors,
                    },
                )

    finished_at_ms = audio_fetch.now_ms()
    if errors == 0:
        audio_fetch.write_done_marker(
            slug, total_chapters=total, completed_at_ms=finished_at_ms
        )
        _emit(
            "audio_prefetch.completed",
            slug,
            _SYSTEM_ACTOR,
            {
                "total": total,
                "duration_ms": finished_at_ms - started_at_ms,
            },
        )
    else:
        _emit(
            "audio_prefetch.failed",
            slug,
            _SYSTEM_ACTOR,
            {
                "total": total,
                "completed": completed,
                "errors": errors,
                "duration_ms": finished_at_ms - started_at_ms,
            },
            result="error",
        )

    with lock:
        cache.set_audio_dl_progress(
            slug,
            {
                "total": total,
                "downloaded": completed,
                "complete": errors == 0,
                "errors": errors,
            },
        )


# ----------------------------------------------------------------------
# Sweeper
# ----------------------------------------------------------------------


def start_cleanup_daemon() -> None:
    """Idempotently start the hourly sweeper thread."""
    global _CLEANUP_THREAD, _CLEANUP_STARTED
    if _CLEANUP_STARTED:
        return
    _CLEANUP_THREAD = threading.Thread(
        target=_cleanup_loop, name="audio-prefetch-sweeper", daemon=True
    )
    _CLEANUP_THREAD.start()
    _CLEANUP_STARTED = True


def _cleanup_loop() -> None:
    while not _STOPPING:
        try:
            sweep_due()
        except Exception:  # noqa: BLE001
            logger.exception("audio_prefetch sweeper tick crashed")
        time.sleep(_CLEANUP_INTERVAL_S)


def sweep_due() -> int:
    """Delete prefetched audio + peaks for any row whose ``prefetch_purge_at``
    is in the past. Returns the count of slugs purged. Exposed for tests + a
    one-shot CLI entry-point.
    """
    purged = 0
    now = datetime.now(timezone.utc)
    for row in state.all_rows():
        if row.prefetch_purge_at is None or row.prefetch_purge_at > now:
            continue
        audio_fetch.clear_prefetch(row.slug)
        try:
            get_backend().delete(storage_paths.prefetch_done_marker_path(row.slug))
        except Exception:  # noqa: BLE001
            pass
        _emit(
            "audio_prefetch.purged",
            row.slug,
            _SYSTEM_ACTOR,
            {"purge_at": row.prefetch_purge_at.isoformat()},
        )
        # Clear the stamp so the same row doesn't re-trigger every hour.
        try:
            state.transition(
                row.slug,
                "admin.clear_prefetch_purge_at",
                actor=_SYSTEM_ACTOR,
            )
        except state.UnknownEvent:
            # Stamp cleared via a direct row patch instead — handled at app
            # boot once the corresponding state handler lands. For now we
            # accept that the row keeps the stale stamp until next deploy.
            pass
        purged += 1
    return purged


# ----------------------------------------------------------------------
# Boot helpers
# ----------------------------------------------------------------------


def resume_orphaned() -> int:
    """At app boot, enqueue every ``awaiting_review`` row that lacks the
    ``_done.json`` sentinel. Returns the count enqueued.

    Restarts during a prefetch job land back here — the per-chapter idempotent
    short-circuit in ``fetch_and_persist_chapter`` skips already-uploaded
    artifacts, so resumed jobs are cheap.
    """
    count = 0
    for row in state.all_rows():
        state_val = row.state.value if hasattr(row.state, "value") else row.state
        if state_val != "awaiting_review":
            continue
        if is_prefetched(row.slug):
            continue
        if enqueue(row.slug):
            count += 1
    return count


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _emit(event: str, slug: str, actor: Actor, payload: dict, *, result: str = "ok") -> None:
    try:
        audit.append(
            event=event,
            actor=actor,
            slug=slug,
            payload=payload,
            result=result,  # type: ignore[arg-type]
        )
    except Exception:  # noqa: BLE001
        logger.exception("audio_prefetch: audit append failed event=%s slug=%s", event, slug)
