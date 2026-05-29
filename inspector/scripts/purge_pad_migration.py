"""One-off: separate `batch_type == "pad_migration"` audit batches out of every
edit_history.jsonl into a parallel archive file, leaving the live edit-history
free of the migration noise.

Layout produced:
    reciters/<slug>/edit_history.jsonl                 — non-pad_migration batches only
    archive/pad_migration/<slug>/edit_history.jsonl — moved batches
    archive/pad_migration/<slug>/edit_history.jsonl.<ts>.bak — pre-purge copy

Dry-run by default. Pass --apply to actually mutate the bucket.
Processes every reciter under reciters/.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.storage import data_dir, storage_paths
from services.storage.hf_bucket import StorageNotFound, get_backend


PURGE_TYPE = "pad_migration"
ARCHIVE_ROOT = "archive/pad_migration"


def archive_history_path(slug: str) -> str:
    return f"{ARCHIVE_ROOT}/{slug}/edit_history.jsonl"


def archive_backup_path(slug: str, stamp: str) -> str:
    return f"{ARCHIVE_ROOT}/{slug}/edit_history.jsonl.{stamp}.bak"


def split_records(raw: bytes) -> tuple[list[dict], list[dict], list[bytes]]:
    """Return (keep, purge, raw_lines). Lines that fail JSON parse are kept verbatim
    in raw_lines and skipped from both buckets — we never silently drop data."""
    keep: list[dict] = []
    purge: list[dict] = []
    bad_lines: list[bytes] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
        except json.JSONDecodeError:
            bad_lines.append(line)
            continue
        if rec.get("batch_type") == PURGE_TYPE:
            purge.append(rec)
        else:
            keep.append(rec)
    return keep, purge, bad_lines


def encode_jsonl(records: list[dict]) -> bytes:
    if not records:
        return b""
    return ("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n").encode("utf-8")


def process_slug(backend, slug: str, *, apply: bool, stamp: str) -> dict:
    path = storage_paths.edit_history_path(slug)
    try:
        raw = backend.read_bytes(path)
    except StorageNotFound:
        return {"slug": slug, "status": "missing", "bytes_before": 0,
                "bytes_after": 0, "batches_kept": 0, "batches_purged": 0}

    keep, purge, bad = split_records(raw)
    bytes_before = len(raw)
    kept_bytes = encode_jsonl(keep)
    purged_bytes = encode_jsonl(purge)
    bytes_after = len(kept_bytes)

    result = {
        "slug": slug,
        "status": "ok",
        "bytes_before": bytes_before,
        "bytes_after": bytes_after,
        "saved": bytes_before - bytes_after,
        "batches_kept": len(keep),
        "batches_purged": len(purge),
        "bad_lines": len(bad),
    }

    if not apply:
        return result

    if not purge:
        result["status"] = "noop"
        return result

    # Order: write archive backup of current full file first (worst-case recoverable),
    # then write archive of purged records, then overwrite live with kept records.
    backup_path = archive_backup_path(slug, stamp)
    backend.write_bytes_atomic(backup_path, raw)
    backend.write_bytes_atomic(archive_history_path(slug), purged_bytes)
    backend.write_bytes_atomic(path, kept_bytes)
    result["status"] = "applied"
    result["backup_path"] = backup_path
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Mutate the bucket (default: dry-run)")
    ap.add_argument("--slug", help="Process only this slug (debugging)")
    args = ap.parse_args()

    backend = get_backend()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if args.slug:
        targets = [args.slug]
    else:
        targets = list(data_dir.list_slugs())

    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Stamp: {stamp}")
    print(f"Targets: {len(targets)}")
    print()

    rows = []
    for slug in targets:
        r = process_slug(backend, slug, apply=args.apply, stamp=stamp)
        rows.append(r)

    # Report
    fmt = "{:<42} {:<10} {:>12} {:>12} {:>12} {:>7} {:>8}"
    print(fmt.format("slug", "status", "before", "after", "saved", "kept", "purged"))
    print("-" * 116)
    total_before = total_after = total_saved = total_purged = 0
    for r in rows:
        print(fmt.format(r["slug"][:42], r["status"],
                         r["bytes_before"], r["bytes_after"],
                         r.get("saved", 0), r["batches_kept"], r["batches_purged"]))
        total_before += r["bytes_before"]
        total_after += r["bytes_after"]
        total_saved += r.get("saved", 0)
        total_purged += r["batches_purged"]
    print("-" * 116)
    print(fmt.format("TOTAL", "", total_before, total_after, total_saved, "", total_purged))
    print()
    if total_before:
        print(f"Reduction: {100 * total_saved / total_before:.1f}% across {len(rows)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
