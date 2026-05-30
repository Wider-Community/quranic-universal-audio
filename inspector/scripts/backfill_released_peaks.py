#!/usr/bin/env python3
"""Backfill slim 10bps chapter peaks for released reciters.

Released reciters' ``audio/`` + ``peaks/`` were swept post-release; the
Timestamps tab now reuses baked slim peaks (``peaks/<ch>.json.gz`` via
``/api/seg/peaks``) and only falls back to a 289-762ms live ffmpeg decode when
they're absent. This one-shot recomputes the peaks from the sidecar CDN URLs.

Writes go to the DEV bucket by default. Peaks are CONTENT-ONLY (no SQLite DB
sync), so a peaks write does NOT carry the state-clobber risk the prod-bucket
refusal guards — but prod is still explicit: ``--bucket prod`` additionally
needs ``INSPECTOR_ALLOW_PROD_BUCKET=1``.

Usage:
  python inspector/scripts/backfill_released_peaks.py --slug maher_al_muaiqly_mp3quran
  python inspector/scripts/backfill_released_peaks.py --slug A --slug B --dry-run
  INSPECTOR_ALLOW_PROD_BUCKET=1 python inspector/scripts/backfill_released_peaks.py \
      --bucket prod --slug maher_al_muaiqly_mp3quran --workers 4
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_INSPECTOR = _REPO / "inspector"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", action="append", default=[],
                    help="reciter slug (repeatable)")
    ap.add_argument("--bucket", choices=["dev", "prod"], default="dev")
    ap.add_argument("--chapters", default="",
                    help="comma-separated chapter filter (default: all)")
    ap.add_argument("--force", action="store_true", help="overwrite existing peaks")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel chapters (default 4; full-chapter decode is "
                         "memory-heavy for long surahs, so keep this modest)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    if not args.slug:
        ap.error("at least one --slug required")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    # Quiet the per-request HEAD/GET chatter from huggingface_hub unless -v.
    if not args.verbose:
        logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
    log = logging.getLogger("backfill")

    for p in (str(_REPO), str(_INSPECTOR)):
        if p not in sys.path:
            sys.path.insert(0, p)

    from services.storage.hf_bucket import DEV_BUCKET_REPO, PROD_BUCKET_REPO
    if args.bucket == "prod":
        os.environ["INSPECTOR_BUCKET_REPO"] = PROD_BUCKET_REPO
        if os.environ.get("INSPECTOR_ALLOW_PROD_BUCKET") != "1":
            ap.error("refusing prod write: re-run with INSPECTOR_ALLOW_PROD_BUCKET=1 "
                     "(peaks are content-only, no DB sync, but prod is explicit)")
    else:
        os.environ["INSPECTOR_BUCKET_REPO"] = DEV_BUCKET_REPO

    from services.audio import audio_meta, peaks_bake
    from services.storage import storage_paths
    from services.storage.data_dir import get_backend

    backend = get_backend()
    chapter_filter = {c.strip() for c in args.chapters.split(",") if c.strip()} or None
    log.info("bucket=%s slugs=%s workers=%d force=%s dry_run=%s",
             os.environ["INSPECTOR_BUCKET_REPO"], args.slug, args.workers,
             args.force, args.dry_run)

    grand = {"baked": 0, "skipped": 0, "failed": 0}
    for slug in args.slug:
        urls = audio_meta.chapter_urls(slug)
        by_surah = {k: u for k, u in urls.items() if ":" not in k and u}
        if not by_surah:
            log.error("[%s] no by_surah chapters in sidecar (by_ayah delivery or "
                      "missing sidecar) — skipping (per-verse baking unimplemented)", slug)
            continue
        items = [(k, u) for k, u in sorted(by_surah.items(), key=lambda kv: int(kv[0]))
                 if chapter_filter is None or k in chapter_filter]
        todo, already = [], 0
        for k, u in items:
            if not args.force and backend.exists(storage_paths.prefetched_peaks_path(slug, k)):
                already += 1
            else:
                todo.append((k, u))
        log.info("[%s] %d chapters: %d already baked, %d to bake%s",
                 slug, len(items), already, len(todo),
                 " (DRY RUN)" if args.dry_run else "")
        grand["skipped"] += already
        if args.dry_run:
            preview = ",".join(k for k, _ in todo[:25])
            log.info("[%s] would bake: %s%s", slug, preview,
                     "..." if len(todo) > 25 else "")
            continue

        def _one(item: tuple[str, str]) -> str:
            k, u = item
            try:
                return peaks_bake.bake_chapter_peaks(slug, k, u, overwrite=args.force)
            except Exception as exc:  # noqa: BLE001
                log.warning("[%s] ch%s error: %s", slug, k, exc)
                return "fail"

        baked = failed = 0
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for (k, _u), r in zip(todo, pool.map(_one, todo)):
                if r == "baked":
                    baked += 1
                    log.debug("[%s] ch%s baked", slug, k)
                elif r == "fail":
                    failed += 1
                    log.warning("[%s] ch%s FAILED", slug, k)
                else:
                    grand["skipped"] += 1
        log.info("[%s] done: baked=%d failed=%d", slug, baked, failed)
        grand["baked"] += baked
        grand["failed"] += failed
        if todo and baked == 0 and failed == len(todo):
            log.error("[%s] ALL chapters failed — ffmpeg lacks https support or "
                      "no network?", slug)

    log.info("GRAND TOTAL: baked=%d skipped=%d failed=%d",
             grand["baked"], grand["skipped"], grand["failed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
