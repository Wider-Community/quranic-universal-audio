"""One-shot migration: convert ``wip/<slug>/peaks/<ch>.json`` to the slim
canonical shape (``<ch>.json.gz``, schema v3) on the dev bucket.

What it does, per chapter file:

1. Skip if a sibling ``<ch>.json.gz`` already exists (idempotent — safe to
   re-run after partial failures).
2. Read the legacy float-JSON, pack via ``peaks_slim.pack_slim`` (int8,
   decimated to 10 bps, gzipped).
3. Atomic-write the slim blob to ``<ch>.json.gz``.
4. Rename the original ``<ch>.json`` to ``<ch>.json.bak`` so
   ``rollback_peaks_slim.py`` can restore it.

The corresponding rollback at ``rollback_peaks_slim.py`` reverses steps 3+4.
Both are gitignored at ``.gitignore`` (``*.bak``), so backups don't leak.

Wall-clock budget: ~5-10 s per reciter on local FUSE mount; ~30-60 s on
HF Space NFS for the heavier chapters. Single-threaded by design — we don't
need parallelism for a one-shot run and serial keeps the bucket happier.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable

# Make this script runnable as `python scripts/backfill_peaks_slim.py`
# from the inspector/ directory (matches the sibling scripts in this dir).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSPECTOR = _REPO_ROOT / "inspector"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_INSPECTOR) not in sys.path:
    sys.path.insert(0, str(_INSPECTOR))

from services.audio.peaks_slim import pack_slim  # noqa: E402
from services.storage import storage_paths  # noqa: E402
from services.storage.hf_bucket import get_backend  # noqa: E402

logger = logging.getLogger("backfill_peaks_slim")


def _iter_wip_slugs(backend) -> Iterable[str]:
    try:
        return sorted(backend.list_dir("wip"))
    except Exception:  # noqa: BLE001
        return []


def _iter_chapters(backend, slug: str) -> list[str]:
    """Return chapter ids (as strings) that have a legacy ``<ch>.json`` file.

    Filters out anything that looks like the new ``.json.gz`` or backup
    ``.json.bak`` so re-runs only see the still-legacy entries.
    """
    peaks_dir = storage_paths.prefetched_peaks_dir(slug)
    try:
        entries = backend.list_dir(peaks_dir)
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for name in entries:
        if not name.endswith(".json"):
            continue  # skips .json.gz, .json.bak, _done.json, etc.
        if name.startswith("_"):
            continue  # _done.json sentinel
        stem = name[: -len(".json")]
        if stem:
            out.append(stem)
    return sorted(out)


def _migrate_chapter(backend, slug: str, chapter: str, *, dry_run: bool) -> str:
    """Migrate one chapter. Returns a status tag for the summary counters."""
    new_path = storage_paths.prefetched_peaks_path(slug, chapter)         # .json.gz
    legacy_path = storage_paths.prefetched_peaks_legacy_path(slug, chapter)  # .json
    backup_path = storage_paths.prefetched_peaks_backup_path(slug, chapter)  # .json.bak

    if backend.exists(new_path):
        # Already migrated — but the legacy file should be renamed to .bak.
        # Idempotent cleanup: if a prior run wrote the .gz but crashed before
        # the rename, finish the job.
        if backend.exists(legacy_path) and not backend.exists(backup_path):
            if dry_run:
                return "would-finish-rename"
            backend.move(legacy_path, backup_path)
            return "finished-rename"
        return "already-migrated"

    if not backend.exists(legacy_path):
        return "no-legacy"

    if dry_run:
        return "would-migrate"

    try:
        raw = backend.read_json(legacy_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("%s/%s: failed to read legacy JSON: %s", slug, chapter, e)
        return "read-error"

    try:
        slim_bytes = pack_slim(raw)
    except (ValueError, TypeError) as e:
        logger.warning("%s/%s: failed to pack slim: %s", slug, chapter, e)
        return "pack-error"

    try:
        backend.write_bytes_atomic(new_path, slim_bytes)
    except Exception as e:  # noqa: BLE001
        logger.warning("%s/%s: failed to write %s: %s", slug, chapter, new_path, e)
        return "write-error"

    try:
        backend.move(legacy_path, backup_path)
    except Exception as e:  # noqa: BLE001
        # .json.gz is written but the original wasn't renamed. The reader
        # uses the .gz path, so the bucket is functionally migrated — but
        # rollback won't have a .bak to restore. Operator should re-run.
        logger.warning("%s/%s: wrote .json.gz but backup rename failed: %s",
                       slug, chapter, e)
        return "backup-error"

    return "migrated"


def migrate_slug(slug: str, *, dry_run: bool) -> dict[str, int]:
    backend = get_backend()
    counters: dict[str, int] = {}
    chapters = _iter_chapters(backend, slug)
    for chapter in chapters:
        tag = _migrate_chapter(backend, slug, chapter, dry_run=dry_run)
        counters[tag] = counters.get(tag, 0) + 1
        if tag == "migrated":
            logger.info("%s/%s: migrated", slug, chapter)
    return counters


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slug",
        help="Limit migration to one reciter slug (default: all under wip/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts without modifying the bucket.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    backend = get_backend()
    if args.slug:
        slugs = [args.slug]
    else:
        slugs = list(_iter_wip_slugs(backend))
    if not slugs:
        print("no wip/ slugs found", file=sys.stderr)
        return 1

    totals: dict[str, int] = {}
    for slug in slugs:
        counters = migrate_slug(slug, dry_run=args.dry_run)
        if not counters:
            continue
        summary = " ".join(f"{tag}={n}" for tag, n in sorted(counters.items()))
        print(f"{slug}: {summary}")
        for tag, n in counters.items():
            totals[tag] = totals.get(tag, 0) + n
    if totals:
        summary = " ".join(f"{tag}={n}" for tag, n in sorted(totals.items()))
        print(f"\nTOTAL ({len(slugs)} reciter(s)): {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
