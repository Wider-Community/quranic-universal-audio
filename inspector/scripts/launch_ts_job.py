"""Manually launch a timestamps-generation HF Job for one slug, as if it
came from the Reviews-tab UI.

Routes through ``inspector/services/admin/timestamps_jobs.py::launch`` so
the slug's ``timestamps_job_ids`` is linked in SQLite (durable_transaction
syncs the row back to the prod bucket) and the same initial ``running``
record is written under ``reciters/<slug>/jobs/ts/<job_id>.json``. On
success the deployed Space's poll fallback (Reviews drawer → ``job_status``)
auto-publishes the reciter; if the webhook secret is wired into prod, the
job's self-POST publishes immediately and no Space restart is needed.

Operational notes:
* Targets the PROD bucket. Requires ``INSPECTOR_ALLOW_PROD_BUCKET=1`` so
  ``resolve_bucket_repo`` does not refuse — this script is the legitimate
  out-of-Space writer.
* The DB write reaches prod via ``durable_transaction``. The deployed
  Space won't observe the new ``timestamps_job_ids`` entry until it
  restarts (its in-memory SQLite snapshot is per-process). Restart once
  before the user opens the Reviews drawer so the poll fallback can fire.
* No new code lives here — this is just a CLI wrapper around ``launch()``
  + an inline ``inspect_job`` / ``fetch_job_logs`` follow loop.

Usage:
    python inspector/scripts/launch_ts_job.py SLUG [--beams 30,2]
        [--no-persist-audio] [--no-gen-peaks] [--workers N] [--dl-workers N]
        [--flavor cpu-upgrade] [--timeout 2h] [--monitor]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def _bootstrap_env() -> None:
    """Wire up env + sys.path so the inspector services are importable.

    Two non-obvious requirements:
      - ``INSPECTOR_BUCKET_REPO`` + ``INSPECTOR_ALLOW_PROD_BUCKET`` so the
        bucket resolver picks prod (otherwise dev is the safe default).
      - The repo root (``scripts/``) on the path so the launcher's lazy
        imports (``services.state.state``, ``scripts.lib.schemas``) work.
    """
    repo_root = Path(__file__).resolve().parents[2]
    inspector_root = repo_root / "inspector"
    for p in (repo_root, inspector_root):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    os.environ.setdefault("INSPECTOR_BUCKET_REPO", "hetchyy/quranic-inspector-bucket")
    os.environ["INSPECTOR_ALLOW_PROD_BUCKET"] = "1"
    # Use a script-private DB path so we don't collide with a running
    # local dev inspector (Windows os.replace fails if another process
    # holds the default ``tempdir/inspector.db`` open). Same bucket
    # data lands here on pull().
    if not os.environ.get("INSPECTOR_DB_PATH"):
        import tempfile
        os.environ["INSPECTOR_DB_PATH"] = str(
            Path(tempfile.gettempdir()) / "inspector_ts_launch.db")
    # Read HF_TOKEN from root .env if not already in env.
    if not os.environ.get("HF_TOKEN"):
        env_file = repo_root / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("HF_TOKEN="):
                    os.environ["HF_TOKEN"] = line.split("=", 1)[1].strip()
                    break


def _beams(raw: str) -> list[int]:
    return [int(t) for t in raw.replace(" ", "").split(",") if t]


def _print(msg: str) -> None:
    """One-line stamp to make the follow loop greppable."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", help="reciter slug, e.g. mahmoud_khalil_al_husary_mp3quran")
    parser.add_argument("--beams", default="30,2")
    parser.add_argument("--no-persist-audio", action="store_true")
    parser.add_argument("--no-gen-peaks", action="store_true")
    parser.add_argument("--workers", type=int, default=None,
                        help="MFA pool workers (default: in-container min(cpu,8))")
    parser.add_argument("--dl-workers", type=int, default=None,
                        help="ffmpeg/producer workers (default: pipeline DEFAULT_DOWNLOAD_WORKERS=4)")
    parser.add_argument("--flavor", default=None, help="HF Job flavor (default: cpu-upgrade)")
    parser.add_argument("--timeout", default=None, help="HF Job timeout (default: 2h)")
    parser.add_argument("--monitor", action="store_true",
                        help="Stream logs until the job reaches a terminal state.")
    parser.add_argument("--poll-secs", type=int, default=15)
    args = parser.parse_args()

    _bootstrap_env()

    # Lazy imports: must run after env bootstrap so bucket-aware modules see prod.
    from scripts.lib.schemas import TsJobSettings
    from services import db as _db
    from services.admin import timestamps_jobs
    from services.db import sync as _db_sync
    from services.state import state as state_service

    # Mirror app.py's boot sequence: pull prod DB → init writer + migrate.
    # ``state.get_row`` returns None for an unopened DB, which is what
    # tripped a first attempt here. After this the writer connection sees
    # the canonical prod row set.
    _db_sync.pull()
    _db.init_db()

    row = state_service.get_row(args.slug)
    if row is None:
        _print(f"ERR: unknown slug {args.slug}")
        return 2
    _print(f"slug={args.slug} state={row.state.value} marked_ready={row.marked_ready}")
    existing = timestamps_jobs.running_job_for(args.slug)
    if existing:
        _print(f"ERR: a job is already in-flight for {args.slug}: {existing}")
        return 3

    settings = TsJobSettings(
        beams=_beams(args.beams),
        persist_audio=not args.no_persist_audio,
        gen_peaks=not args.no_gen_peaks,
        workers=args.workers,
        download_workers=args.dl_workers,
        flavor=args.flavor,
        timeout=args.timeout,
    )
    _print(f"settings: {settings.model_dump(exclude_none=False)}")

    # Webhook base: only useful when the deployed Space has the matching
    # secret env (we can't read it from here). Pass it anyway — the
    # launcher gates on the local secret env, which is absent in this
    # CLI, so it's effectively a no-op until configured.
    webhook_base = "https://hetchyy-quranic-universal-audio.hf.space"
    result = timestamps_jobs.launch(args.slug, settings=settings,
                                    webhook_base=webhook_base)
    job_id = result.get("job_id")
    url = result.get("url")
    _print(f"launched job_id={job_id}")
    _print(f"  URL: {url}")

    if not args.monitor:
        return 0

    # Follow loop. Print only NEW log lines each tick, plus the current
    # HF stage. Exits when the stage is terminal.
    from huggingface_hub import fetch_job_logs, inspect_job
    terminal = {"succeeded", "completed", "failed", "error", "errored",
                "timed-out", "timeout", "stopped", "canceled", "cancelled",
                "deleted"}
    seen = 0
    last_status = None
    while True:
        try:
            info = inspect_job(job_id=job_id)
            stage_obj = getattr(info, "status", None)
            stage = (getattr(stage_obj, "stage", None) or stage_obj or "").lower()
        except Exception as exc:
            _print(f"inspect_job error: {exc}")
            stage = ""
        if stage and stage != last_status:
            _print(f"status → {stage}")
            last_status = stage
        try:
            lines = list(fetch_job_logs(job_id=job_id))
        except Exception as exc:
            lines = []
            _print(f"fetch_job_logs error: {exc}")
        for line in lines[seen:]:
            print(f"   | {line}")
        seen = len(lines)
        if stage in terminal:
            _print(f"terminal: {stage}")
            return 0 if stage in ("succeeded", "completed") else 1
        time.sleep(args.poll_secs)


if __name__ == "__main__":
    raise SystemExit(main())
