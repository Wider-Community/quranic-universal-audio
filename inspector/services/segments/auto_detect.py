"""Auto-detect reconciler — server-side acceptance of pending requests.

When the alignment pipeline produces files under ``wip/<slug>/`` (Katana /
HPC / CI job), this reconciler notices the new folder and fires
``reciter.alignment_completed`` for any slug in ``AWAITING_ALIGNMENT``.
The state handler then applies the pending catalog edits (if any) and
transitions the row to ``AWAITING_REVIEW`` ("Available for review" pill).

This is the replacement for a manual "Accept" button: by the time files
exist in the bucket, the request has effectively been accepted — the
human work is now reviewing the alignment, not approving the metadata.

Two trigger points:

1. Periodic background loop (``start_background_loop``) — polls every
   ``AUTO_DETECT_INTERVAL_SECONDS`` (default 60) in the single-worker
   deployed profile.
2. On-demand admin trigger — ``POST /api/admin/reconcile`` calls
   ``reconcile_once`` synchronously. Useful in dev and as a backstop.

The "seen" set is process-local, seeded at boot from the current state of
the bucket. After a restart a re-fire would no-op because the row is no
longer in ``AWAITING_ALIGNMENT``, so durability isn't needed.

The audit record carries a synthetic system actor (``hf_user_id="system"``,
role=owner). This is also the actor that subsequently calls
``catalog.edit_reciter`` / ``catalog.edit_delivery`` via
``pending_requests.apply_and_archive_completed`` — owner role is required by those
mutations.
"""

from __future__ import annotations

import logging
import threading
import time

from scripts.lib.schemas import Actor, ReciterState, Role

from services.audio.peaks_backfill import backfill_pipeline_peaks
from services.state import state as state_service
from services.storage.hf_bucket import get_backend

logger = logging.getLogger(__name__)


# The synthetic actor used for every auto-fired transition. Exposed for tests.
SYSTEM_ACTOR: Actor = Actor(
    hf_user_id="system",
    login_at_time="system",
    role=Role.OWNER,
)


_seen_wip_slugs: set[str] = set()
_seen_lock = threading.Lock()
_background_thread: threading.Thread | None = None


def hydrate_initial_seen() -> None:
    """Boot-time: snapshot current ``wip/`` slugs into the seen set, AND
    fire ``alignment_completed`` for any slug that's still in
    ``AWAITING_ALIGNMENT`` despite having files in ``wip/``.

    The catch-up firing handles the case where a wip/ upload completed
    while the server was down (or between an upload and a redeploy) —
    without it, the slug would stay stuck in ``AWAITING_ALIGNMENT`` forever
    because the seen-set diff in ``reconcile_once`` would never see the
    folder as "new".

    Idempotent: a second call no-ops because the slugs are already in the
    seen set and the rows are no longer in ``AWAITING_ALIGNMENT``.
    """
    backend = get_backend()
    try:
        slugs = backend.list_dir("wip")
    except Exception:  # noqa: BLE001
        logger.exception("auto_detect: list_dir('wip') failed during initial seed")
        return
    with _seen_lock:
        _seen_wip_slugs.update(slugs)

    fired = 0
    for slug in slugs:
        row = state_service.get_row(slug)
        if row is None or row.state != ReciterState.AWAITING_ALIGNMENT:
            continue
        try:
            state_service.transition(
                slug, "reciter.alignment_completed", actor=SYSTEM_ACTOR,
            )
            fired += 1
        except state_service.StateError:
            logger.exception(
                "auto_detect: catch-up alignment_completed failed for slug=%s",
                slug,
            )
    logger.info(
        "auto_detect: hydrated initial seen set (%d wip/ slugs, %d catch-up "
        "transition(s) fired)", len(slugs), fired,
    )

    # Peaks backfill — idempotent. Runs for EVERY wip slug (not only the
    # ones we just transitioned) so slugs that arrived before this code
    # shipped also get their pipeline-op peaks. One failure does not block
    # the others, and never blocks boot.
    for slug in slugs:
        try:
            backfill_pipeline_peaks(slug)
        except Exception:  # noqa: BLE001
            logger.exception(
                "auto_detect: peaks backfill failed for slug=%s", slug,
            )


def reconcile_once() -> int:
    """Single reconcile pass. Returns the number of transitions fired.

    Safe to call from any thread. Slugs not in ``AWAITING_ALIGNMENT`` are
    no-ops (the state handler raises ``InvalidTransition`` which we
    swallow). Each new slug is added to the seen set whether or not the
    transition fired — avoids re-trying every loop iteration for slugs
    that don't yet have a state row or are in a different state.
    """
    backend = get_backend()
    try:
        current = set(backend.list_dir("wip"))
    except Exception:  # noqa: BLE001
        logger.exception("auto_detect: list_dir('wip') failed; skipping pass")
        return 0

    with _seen_lock:
        new_slugs = current - _seen_wip_slugs
        _seen_wip_slugs.update(current)

    fired = 0
    transitioned: list[str] = []
    for slug in new_slugs:
        row = state_service.get_row(slug)
        if row is None or row.state != ReciterState.AWAITING_ALIGNMENT:
            # Manual upload outside the request flow, or row not yet seeded.
            # Either way, no transition to fire — the slug is now in the seen
            # set so we won't retry on every poll tick.
            continue
        try:
            state_service.transition(
                slug, "reciter.alignment_completed", actor=SYSTEM_ACTOR,
            )
            fired += 1
            transitioned.append(slug)
        except state_service.StateError:
            logger.exception(
                "auto_detect: alignment_completed failed for slug=%s", slug,
            )
    if fired:
        logger.info(
            "auto_detect: fired alignment_completed for %d slug(s)", fired,
        )
    # Peaks backfill for the slugs we just transitioned — idempotent, won't
    # block the reconcile loop on a per-slug failure.
    for slug in transitioned:
        try:
            backfill_pipeline_peaks(slug)
        except Exception:  # noqa: BLE001
            logger.exception(
                "auto_detect: peaks backfill failed for slug=%s", slug,
            )
    return fired


def start_background_loop(interval_seconds: int = 60) -> threading.Thread:
    """Spawn the polling thread. Idempotent — returns the existing thread if
    one was already started.

    The thread is a daemon so it dies with the process; reconcile_once
    failures are caught and logged so a single hiccup doesn't kill the
    loop.
    """
    global _background_thread
    if _background_thread is not None and _background_thread.is_alive():
        return _background_thread

    def _loop() -> None:
        logger.info(
            "auto_detect: background loop started (interval=%ss)", interval_seconds,
        )
        while True:
            try:
                reconcile_once()
            except Exception:  # noqa: BLE001
                logger.exception("auto_detect: reconcile_once errored")
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True, name="auto-detect")
    t.start()
    _background_thread = t
    return t


def _reset_seen_for_tests() -> None:
    """Tests only — reset the seen set so each test starts clean."""
    with _seen_lock:
        _seen_wip_slugs.clear()


__all__ = [
    "SYSTEM_ACTOR",
    "hydrate_initial_seen",
    "reconcile_once",
    "start_background_loop",
]
