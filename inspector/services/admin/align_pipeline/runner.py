"""Worker threads that drive an align run through its stages.

One daemon thread per active run. ``resume_active()`` at boot restarts every
pending/running row (a ``running`` row after a restart means the previous
process died mid-stage); a ``failed`` row waits for an explicit retry. Every
stage is resumable from its staged files, so a restarted worker skips what the
previous one finished.

Stage transitions are the only DB writes (``durable_transaction`` pushes the
whole database to the bucket each time); per-chapter progress is in
``progress`` + the staged files.
"""

from __future__ import annotations

import logging
import threading

from services.audio import audio_meta
from services.db import repo_align_runs
from services.db.sync import durable_transaction
from services.storage import cache

from . import progress, stage_acquire, stage_align, stage_assemble, stage_sidecars
from .params import AlignParams

log = logging.getLogger("inspector")

STAGES = ("acquire", "align", "sidecars", "assemble")

_lock = threading.Lock()
_workers: dict[str, threading.Thread] = {}


def ensure_worker(run: dict | None) -> None:
    """Start a worker for ``run`` unless one is already alive."""
    if run is None:
        return
    run_id = run["run_id"]
    with _lock:
        existing = _workers.get(run_id)
        if existing is not None and existing.is_alive():
            return
        t = threading.Thread(target=_drive, args=(run_id,), name=f"align-{run_id[:8]}", daemon=True)
        _workers[run_id] = t
        t.start()


def is_alive(run_id: str) -> bool:
    with _lock:
        t = _workers.get(run_id)
    return t is not None and t.is_alive()


def resume_active() -> int:
    """Boot: restart every pending/running run. Returns how many were started."""
    started = 0
    for run in repo_align_runs.list_active():
        if run["status"] in ("pending", "running"):
            ensure_worker(run)
            started += 1
    if started:
        log.info("align: resumed %d run(s)", started)
    return started


# ---------------------------------------------------------------------------
# The drive loop
# ---------------------------------------------------------------------------


def _drive(run_id: str) -> None:
    run = repo_align_runs.get(run_id)
    if run is None:
        return
    slug = run["slug"]
    params = AlignParams.from_json(run.get("params_json"))
    try:
        chapters = audio_meta.chapter_numbers(slug)
        sources = audio_meta.chapter_urls(slug)
        source_by_ch = {int(k): v for k, v in sources.items()}
        stage = run["stage"]
        for name in STAGES[STAGES.index(stage) :]:
            progress.check_cancel(run_id)
            _mark(run_id, stage=name, status="running", last_error=None)
            run = repo_align_runs.get(run_id) or run
            if name == "acquire":
                _acquire(run, chapters, sources)
            elif name == "align":
                stage_align.run(slug, run_id, params, chapters)
            elif name == "sidecars":
                stage_sidecars.run(slug, run_id, params, chapters, source_by_ch)
            else:
                stage_assemble.run(
                    slug, run_id, params, chapters, source_by_ch, started_at=run["started_at"]
                )
        _mark(run_id, stage="done", status="succeeded")
        progress.clear_detail(run_id)
        log.info("align %s: done (%s)", run_id, slug)
        _reconcile()
    except progress.Canceled:
        _mark(run_id, status="canceled")
        progress.clear_detail(run_id)
        log.info("align %s: canceled (%s)", run_id, slug)
    except Exception as exc:  # noqa: BLE001 — every failure lands on the row
        log.exception("align %s: failed at stage %s", run_id, run["stage"])
        _mark(run_id, status="failed", last_error=f"{type(exc).__name__}: {exc}"[:2000])
    finally:
        progress.clear_cancel(run_id)


def _acquire(run: dict, chapters: list[int], sources: dict[str, str]) -> None:
    slug, run_id = run["slug"], run["run_id"]
    job_id = run.get("acquire_job_id")
    if not job_id:
        needs_ytdlp = any(_needs_ytdlp(u) for u in sources.values())
        from services.db import repo_catalog

        delivery = repo_catalog.find_delivery(slug)
        channels = delivery.channels if delivery else None
        job_id = stage_acquire.launch(slug, run_id, needs_ytdlp=needs_ytdlp, channels=channels)
        _mark(run_id, acquire_job_id=job_id)
    stage_acquire.wait(slug, run_id, job_id)
    progress.set_detail(run_id, chapters_done=len(chapters))


def _needs_ytdlp(url: str) -> bool:
    from pathlib import Path

    return Path(url.split("?")[0]).suffix.lower() not in (
        ".mp3",
        ".m4a",
        ".wav",
        ".flac",
        ".ogg",
        ".aac",
        ".opus",
    )


def _mark(run_id: str, **fields) -> None:
    with durable_transaction():
        repo_align_runs.update(run_id, **fields)
    cache.invalidate_admin_requests_cache()


def _reconcile() -> None:
    """Let auto_detect fire ``alignment_completed`` now rather than on its next tick."""
    try:
        from services.segments import auto_detect

        auto_detect.reconcile_once()
    except Exception as exc:  # noqa: BLE001 — the periodic loop is the backstop
        log.warning("align: post-assemble reconcile failed: %s", exc)


def _reset_for_tests() -> None:
    with _lock:
        _workers.clear()
