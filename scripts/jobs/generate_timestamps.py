#!/usr/bin/env python3
"""HF Job entrypoint: generate timestamps for one reciter, in-container.

Runs MFA forced-alignment inside the job (strategy A — stock conda base +
MFA stack pulled from a mounted private bucket), reading the reciter's
``detailed.json`` from the mounted inspector bucket and writing v2
occurrence-preserving per-chapter shards to
``<mount>/reciters/<slug>/timestamps/<chapter>.json`` (the read-path layout;
``process()`` emits them alongside the historical ``timestamps_full.json``).

Launched by ``inspector/services/admin/timestamps_jobs.py`` via
``huggingface_hub.run_uv_job``. Configured entirely through env vars so the
launcher only has to set ``SLUG`` (+ optional ``BEAMS``).

Env:
  SLUG               (required) reciter slug
  INSPECTOR_BUCKET_MOUNT  bucket mount root (default ``/data``)
  MFA_APP_PATH       aligner app.py from the runtime bucket
                     (default ``/aux/mfa-runtime/app.py``)
  BEAMS              comma-separated beams; first canonical (default ``50``)
  WORKERS            process-pool size (default ``os.cpu_count()``)
  BATCH_SIZE / DOWNLOAD_WORKERS / PADDING / METHOD  pipeline tunables

See docs/planning/inspector-deploy/v2/phases/13-timestamps-job.md.
"""

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.lib.timestamps_pipeline import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    DEFAULT_DOWNLOAD_WORKERS,
    DEFAULT_METHOD,
    DEFAULT_PADDING,
    LocalMfaBackend,
    process,
)

log = logging.getLogger("generate_timestamps")


def _beams(raw: str) -> list[int]:
    out = [int(t) for t in raw.replace(" ", "").split(",") if t]
    return out or [50]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    slug = os.environ.get("SLUG", "").strip()
    if not slug:
        log.error("SLUG env var is required")
        return 2

    mount = Path(os.environ.get("INSPECTOR_BUCKET_MOUNT", "/data"))
    app_path = Path(os.environ.get("MFA_APP_PATH", "/aux/mfa-runtime/app.py"))
    reciter_dir = mount / "reciters" / slug
    detailed = reciter_dir / "detailed.json"

    if not detailed.exists():
        log.error("detailed.json not found at %s", detailed)
        return 3
    if not app_path.exists():
        log.error("MFA app not found at %s (runtime bucket not mounted?)", app_path)
        return 3

    beams = _beams(os.environ.get("BEAMS", "50"))
    # Cap default workers: each pool worker extracts its own ~92 MB MFA model
    # at init, so too many OOM/race during simultaneous KalpyEngine init (16
    # crashed mid-init on cpu-upgrade; 8 verified safe). Override via WORKERS /
    # INSPECTOR_TS_JOB_WORKERS once a flavor's headroom is benched.
    workers = int(os.environ.get("WORKERS") or min(os.cpu_count() or 1, 8))
    batch_size = int(os.environ.get("BATCH_SIZE", str(DEFAULT_BATCH_SIZE)))
    dl_workers = int(os.environ.get("DOWNLOAD_WORKERS", str(DEFAULT_DOWNLOAD_WORKERS)))
    padding = os.environ.get("PADDING", DEFAULT_PADDING)
    method = os.environ.get("METHOD", DEFAULT_METHOD)

    log.info(
        "generate_timestamps slug=%s cores=%s workers=%s beams=%s batch=%s "
        "dl_workers=%s app=%s",
        slug, os.cpu_count(), workers, beams, batch_size, dl_workers, app_path,
    )

    # Inject the per-chapter audio source: detailed.json entries carry no
    # ``audio`` field post-migration (#5) — URLs live in the audio manifest,
    # bytes live in the bucket. Resolve bucket file first (no CDN dependency),
    # manifest URL fallback. process() then reads it from a temp detailed.json
    # (kept named ``<slug>/`` so ``input_dir.name`` stays the slug); output
    # still goes to the real reciter dir in the bucket.
    doc = json.loads(detailed.read_text(encoding="utf-8"))
    manifest_path = mount / "catalog" / "audio_manifest" / f"{slug}.json"
    chapters_meta = {}
    if manifest_path.exists():
        try:
            chapters_meta = (json.loads(manifest_path.read_text(encoding="utf-8"))
                             or {}).get("chapters", {}) or {}
        except Exception as exc:
            log.warning("could not read manifest %s: %s", manifest_path, exc)
    audio_dir = reciter_dir / "audio"
    entries = doc.get("entries", [])
    injected = 0
    for entry in entries:
        ref = str(entry.get("ref", ""))
        local = audio_dir / f"{ref}.mp3"
        if local.exists():
            entry["audio"] = str(local)
            injected += 1
        else:
            url = (chapters_meta.get(ref) or {}).get("url")
            if url:
                entry["audio"] = url
                injected += 1
    log.info("injected audio source for %d/%d chapters", injected, len(entries))

    job_input = Path(tempfile.mkdtemp()) / slug
    job_input.mkdir(parents=True, exist_ok=True)
    (job_input / "detailed.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    # In-container MFA: pool path engages when workers>1 AND mfa_app_path is
    # set (process() gates on this). LocalMfaBackend covers the serial
    # fallback. process() writes v2 shards into reciter_dir/timestamps/.
    process(
        input_dir=job_input,
        backend=LocalMfaBackend(app_path),
        method=method,
        beams=beams,
        shared_cmvn=False,
        resume=False,
        batch_size=batch_size,
        output_dir=reciter_dir,
        padding=padding,
        refresh_verses=None,
        download_workers=dl_workers,
        workers=workers,
        mfa_app_path=app_path,
    )
    log.info("done slug=%s", slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
