"""Reverse the slim-peaks migration: restore each ``<ch>.json.bak`` to
``<ch>.json`` and delete the ``<ch>.json.gz`` slim file.

Use when:
- A bug surfaces in the v3 slim format and we need the legacy reader.
- Re-evaluating density / quantization choices and want a clean baseline.

After rolling back you must also revert ``PEAKS_SCHEMA_VERSION`` in
``inspector/config.py`` to 2 -- the v3 reader expects ``.json.gz`` and will
return ``None`` for the legacy ``.json`` files.

Idempotent: chapters that have no ``.bak`` are skipped (nothing to restore).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable

# Make this script runnable as `python scripts/rollback_peaks_slim.py`
# from the inspector/ directory.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSPECTOR = _REPO_ROOT / "inspector"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_INSPECTOR) not in sys.path:
    sys.path.insert(0, str(_INSPECTOR))

from services.storage import storage_paths  # noqa: E402
from services.storage.hf_bucket import get_backend  # noqa: E402

logger = logging.getLogger("rollback_peaks_slim")


def _iter_all_slugs(backend) -> list[str]:
    """All reciter slugs under ``reciters/`` -- mirrors the backfill script."""
    try:
        return sorted(set(backend.list_dir(storage_paths.RECITERS_PREFIX)))
    except Exception:  # noqa: BLE001
        return []


def _iter_backups(backend, slug: str) -> list[str]:
    """Return chapter ids that have a ``<ch>.json.bak`` to restore."""
    peaks_dir = storage_paths.prefetched_peaks_dir(slug)
    try:
        entries = backend.list_dir(peaks_dir)
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for name in entries:
        if not name.endswith(".json.bak"):
            continue
        stem = name[: -len(".json.bak")]
        if stem:
            out.append(stem)
    return sorted(out)


def _rollback_chapter(backend, slug: str, chapter: str, *, dry_run: bool) -> str:
    new_path = storage_paths.prefetched_peaks_path(slug, chapter)         # .json.gz
    legacy_path = storage_paths.prefetched_peaks_legacy_path(slug, chapter)  # .json
    backup_path = storage_paths.prefetched_peaks_backup_path(slug, chapter)  # .json.bak

    if not backend.exists(backup_path):
        return "no-backup"

    if dry_run:
        return "would-rollback"

    # Step 1: restore .bak → .json. If a .json already exists (operator
    # interrupted mid-rollback), don't clobber it — caller can investigate.
    if backend.exists(legacy_path):
        logger.warning("%s/%s: %s already exists; skipping rename",
                       slug, chapter, legacy_path)
        return "legacy-already-exists"
    try:
        backend.move(backup_path, legacy_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("%s/%s: failed to restore .bak → .json: %s", slug, chapter, e)
        return "restore-error"

    # Step 2: delete the slim .json.gz, if it's there.
    if backend.exists(new_path):
        try:
            backend.delete(new_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("%s/%s: failed to delete %s: %s", slug, chapter, new_path, e)
            return "delete-error"

    return "rolled-back"


def rollback_slug(slug: str, *, dry_run: bool) -> dict[str, int]:
    backend = get_backend()
    counters: dict[str, int] = {}
    for chapter in _iter_backups(backend, slug):
        tag = _rollback_chapter(backend, slug, chapter, dry_run=dry_run)
        counters[tag] = counters.get(tag, 0) + 1
        if tag == "rolled-back":
            logger.info("%s/%s: rolled back", slug, chapter)
    return counters


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slug",
        help="Limit rollback to one reciter slug (default: all under reciters/).",
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
    slugs = [args.slug] if args.slug else _iter_all_slugs(backend)
    if not slugs:
        print("no reciters/ slugs found", file=sys.stderr)
        return 1

    totals: dict[str, int] = {}
    for slug in slugs:
        counters = rollback_slug(slug, dry_run=args.dry_run)
        if not counters:
            continue
        summary = " ".join(f"{tag}={n}" for tag, n in sorted(counters.items()))
        print(f"{slug}: {summary}")
        for tag, n in counters.items():
            totals[tag] = totals.get(tag, 0) + n
    if totals:
        summary = " ".join(f"{tag}={n}" for tag, n in sorted(totals.items()))
        print(f"\nTOTAL ({len(slugs)} reciter(s)): {summary}")
        if not args.dry_run and totals.get("rolled-back"):
            print(
                "\nReminder: revert PEAKS_SCHEMA_VERSION to 2 in inspector/config.py "
                "so the runtime reader stops expecting .json.gz.",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
