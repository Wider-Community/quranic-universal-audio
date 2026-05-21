"""Wip-audio sweeper: 1-week post-release cleanup of bucket audio + peaks.

A daemon thread wakes hourly, scans the in-memory state store, and deletes
``wip/<slug>/{audio,peaks}/`` for rows whose ``prefetch_purge_at`` is in the
past. The single-worker Flask invariant guarantees one sweeper per deploy.

Trigger flow (handled in ``services.state``):

* ``reciter.timestamps_completed`` → ``RELEASED`` — stamps the row with
  ``prefetch_purge_at = now + 7d``.
* ``admin.unlocked_for_revision`` → ``AWAITING_REVIEW`` — clears the stamp.
* ``admin.clear_prefetch_purge_at`` — emitted by the sweeper itself once a
  row's wip artifacts are purged.

The original module also drove a foreground prefetch worker that downloaded
from upstream CDN and warmed the bucket on state transitions. That worker
was removed once the katana extraction pipeline became the only writer of
bucket audio (its prefetch_xing remux was also broken — a non-existent
ffmpeg bsf — so the inspector worker shipped raw upstream bytes anyway and
had no correctness advantage over CDN passthrough). See git history for the
removal; ``audio_fetch.py`` retains only the bucket-read primitives.

No Flask imports.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from scripts.lib.schemas import Actor, Role
from . import audio_fetch
from services.state import audit, state
from services.storage import storage_paths
from services.storage.hf_bucket import get_backend

logger = logging.getLogger(__name__)

# ---- System actor for unattended audit appends ----

_SYSTEM_ACTOR = Actor(
    hf_user_id="system",
    login_at_time="audio_prefetch",
    role=Role.MAINTAINER,
)

# ---- Sweeper state ----

_CLEANUP_THREAD: threading.Thread | None = None
_CLEANUP_STARTED = False
_CLEANUP_INTERVAL_S = 3600  # 1 hour
_STOPPING = False


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


def is_prefetched(slug: str) -> bool:
    """Return True iff the ``_done.json`` sentinel exists in the bucket.

    Sentinel is written by ``.local/extraction/upload_to_bucket.py`` at the
    end of a katana extraction run. The audio-proxy and peaks route gate
    their bucket-vs-CDN routing on this.
    """
    try:
        return get_backend().exists(storage_paths.prefetch_done_marker_path(slug))
    except Exception as e:  # noqa: BLE001
        logger.warning("is_prefetched(%s) backend probe failed: %s", slug, e)
        return False


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
            logger.exception("wip-audio sweeper tick crashed")
        time.sleep(_CLEANUP_INTERVAL_S)


def sweep_due() -> int:
    """Delete bucket audio + peaks for any row whose ``prefetch_purge_at`` is
    in the past. Returns the count of slugs purged. Exposed for tests + a
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
