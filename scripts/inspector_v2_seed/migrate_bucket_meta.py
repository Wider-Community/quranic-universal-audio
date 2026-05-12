"""Rewrite ``_meta.reciter`` in every per-chapter timestamps file on the bucket
to match the bucket folder slug (the canonical v2 slug from the catalog).

Background. The upstream ``timestamps_full.json`` from the alignment pipeline
embeds a ``_meta.reciter`` field with whatever slug the aligner stamped at
extraction time. For reciters cut over from a pre-v2 naming convention (e.g.
``maher_al_meaqli`` → ``maher_al_muaiqly_mp3quran``) the embedded slug stays
on the legacy form even after the bucket folder is created at the new slug.
The frontend used to trust ``_meta.reciter`` for identity, so a mismatch
broke every navigation that consulted the manifest by slug. The frontend
now ignores ``_meta.reciter`` (see ``ts_client.ts::assembleVerseFromShard``)
but the field is still authored into the file and should match the folder
it lives in.

Usage::

    python -m scripts.inspector_v2_seed.migrate_bucket_meta           # dry-run
    python -m scripts.inspector_v2_seed.migrate_bucket_meta --apply   # mutate
    python -m scripts.inspector_v2_seed.migrate_bucket_meta --slug X  # one slug

Iterates ``state.all_rows()`` (``state in {released, completed}``), lists
``<bucket>/published/<slug>/timestamps/<chapter>.json`` for each, parses,
fixes ``_meta.reciter``, and uploads via the storage backend if changed.
Idempotent: re-running after the migration is a no-op (no writes issued).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable

from ._env import load_repo_env


def _iter_target_slugs(filter_slug: str | None):
    from services import state as state_service

    state_service.hydrate()
    for row in state_service.all_rows():
        if filter_slug and row.slug != filter_slug:
            continue
        if row.state.value not in ("released", "completed"):
            continue
        yield row.slug


def _chapter_paths(slug: str) -> Iterable[tuple[int, str]]:
    """Yield ``(chapter, bucket_path)`` for every TS file under the slug."""
    from services import data_dir
    from services import storage_paths

    chapters = data_dir.list_published_timestamps_chapters(slug)
    for chapter in chapters:
        yield chapter, storage_paths.published_timestamps_path(slug, chapter)


def _fix_one(slug: str, chapter: int, path: str, *, apply: bool) -> tuple[str, str | None]:
    """Return (status, prev_value). status ∈ {ok, fixed, missing, parse_fail}."""
    from services.hf_bucket import StorageNotFound, get_backend

    backend = get_backend()
    try:
        raw = backend.read_bytes(path)
    except StorageNotFound:
        return "missing", None

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return "parse_fail", None

    if not isinstance(doc, dict):
        return "parse_fail", None

    meta = doc.get("_meta")
    if not isinstance(meta, dict):
        return "parse_fail", None

    prev = meta.get("reciter")
    if prev == slug:
        return "ok", prev

    if apply:
        meta["reciter"] = slug
        body = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        backend.write_bytes_atomic(path, body)

    return "fixed", prev if isinstance(prev, str) else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true",
                   help="Actually write fixes. Default is dry-run.")
    p.add_argument("--slug", default=None,
                   help="Process a single slug instead of all completed reciters.")
    args = p.parse_args(argv)

    load_repo_env()
    # Defer service imports until after env load — services hydrate from the
    # bucket at import time and need HF_TOKEN/INSPECTOR_BUCKET_REPO set first.
    sys.path.insert(0, "inspector")
    sys.path.insert(0, ".")

    print(f"==> Migration mode: {'APPLY' if args.apply else 'DRY-RUN'}")

    totals = {"reciters": 0, "files": 0, "fixed": 0, "ok": 0, "missing": 0, "parse_fail": 0}
    for slug in _iter_target_slugs(args.slug):
        totals["reciters"] += 1
        per_slug = {"fixed": 0, "ok": 0, "missing": 0, "parse_fail": 0}
        for chapter, path in _chapter_paths(slug):
            totals["files"] += 1
            status, prev = _fix_one(slug, chapter, path, apply=args.apply)
            per_slug[status] = per_slug.get(status, 0) + 1
            totals[status] = totals.get(status, 0) + 1
            if status == "fixed":
                action = "fixed" if args.apply else "would fix"
                print(f"  {slug}/{chapter:03d}: {action} ({prev!r} -> {slug!r})")
        print(f"  ── {slug}: {per_slug}")

    print(f"\n==> Totals: {totals}")
    if args.apply and totals.get("fixed", 0) > 0:
        # Invalidate the in-process TS LRU so the next request picks up the new
        # bytes if this script is run inside a long-running interpreter; in
        # practice the Space restarts on next deploy so this is belt-and-braces.
        from services import timestamps as ts_serve
        ts_serve.invalidate()
        print("==> Cleared in-process timestamps cache.")

    if not args.apply and totals.get("fixed", 0) > 0:
        print("\n==> DRY-RUN — re-run with --apply to write the fixes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
