"""Convert legacy plain ``peaks/<ch>.json`` files to the v3 slim gzipped shape.

Migration #5 wire shape for per-chapter peaks is
``peaks/<ch>.json.gz`` containing one gzip member of one JSON document
that mirrors ``inspector/services/audio/peaks_slim.py::pack_slim``'s
output. Legacy reciters that pre-date that move have plain
``peaks/<ch>.json`` files in the verbose v2 shape (``schema_version: 2``
+ ``peaks: [[mn, mx], ...]``).

This script walks a directory of plain ``.json`` peaks files and emits
``.json.gz`` siblings. Original plain files are deleted by default so
the dir contains only the canonical wire shape afterwards (pass
``--keep-legacy`` to preserve them).

Usage::

    python3 scripts/backfills/convert_peaks_v2_to_v3.py --dir /tmp/<slug>/peaks/

Designed to run before re-upload in a download → migrate → re-upload
workflow — the upload step ships the ``.json.gz`` files; orphaned plain
``.json`` files on the bucket need a separate ``delete`` pass.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger("convert_peaks_v2_to_v3")


def _setup_paths() -> None:
    """Insert repo root + inspector/ so we can import the shared packer."""
    here = Path(__file__).resolve()
    repo = here.parents[2]
    sys.path.insert(0, str(repo / "inspector"))
    sys.path.insert(0, str(repo))


def convert_dir(peaks_dir: Path, *, keep_legacy: bool, apply: bool) -> dict:
    """Convert every plain ``.json`` (no ``.gz``) under *peaks_dir*."""
    from services.audio.peaks_slim import pack_slim

    plain = sorted(
        p
        for p in peaks_dir.iterdir()
        if p.is_file() and p.suffix == ".json" and not p.name.endswith(".json.gz")
    )
    if not plain:
        log.info("No plain .json peaks files in %s", peaks_dir)
        return {"converted": 0, "deleted": 0, "skipped": 0, "errors": 0}

    converted = 0
    skipped = 0
    deleted = 0
    errors = 0
    bytes_before = 0
    bytes_after = 0

    for src in plain:
        out = src.with_suffix(".json.gz")
        if out.is_file():
            log.info("skip %s — %s already exists", src.name, out.name)
            skipped += 1
            continue
        try:
            raw = src.read_text(encoding="utf-8")
            doc = json.loads(raw)
        except Exception as e:
            log.warning("read fail %s: %s", src.name, e)
            errors += 1
            continue
        try:
            blob = pack_slim(doc)
        except Exception as e:
            log.warning("pack_slim fail %s: %s", src.name, e)
            errors += 1
            continue

        bytes_before += len(raw.encode("utf-8"))
        bytes_after += len(blob)

        if apply:
            out.write_bytes(blob)
            if not keep_legacy:
                src.unlink()
                deleted += 1
        converted += 1

    log.info(
        "Converted %d files: %d KB → %d KB (%.1f%% saved); deleted %d legacy; "
        "skipped %d; %d errors",
        converted,
        bytes_before // 1024,
        bytes_after // 1024,
        (1 - (bytes_after / max(bytes_before, 1))) * 100,
        deleted,
        skipped,
        errors,
    )

    return {
        "converted": converted,
        "deleted": deleted,
        "skipped": skipped,
        "errors": errors,
        "bytes_before": bytes_before,
        "bytes_after": bytes_after,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--dir", type=Path, required=True, help="Peaks directory (e.g. /tmp/<slug>/peaks/)."
    )
    ap.add_argument(
        "--keep-legacy",
        action="store_true",
        help="Don't delete plain .json files after writing .json.gz.",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Report what would change without writing."
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _setup_paths()

    if not args.dir.is_dir():
        raise SystemExit(f"not a directory: {args.dir}")

    result = convert_dir(args.dir, keep_legacy=args.keep_legacy, apply=not args.dry_run)
    log.info("DONE: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
