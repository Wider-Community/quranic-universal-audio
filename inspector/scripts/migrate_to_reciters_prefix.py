"""One-shot bucket migration: unify ``wip/<slug>/`` + ``published/<slug>/`` into ``reciters/<slug>/``.

Background: per-reciter content used to live under two state-driven prefixes
(``wip/`` for in-flight, ``published/`` once RELEASED). The code now uses a
single ``reciters/<slug>/`` prefix so lifecycle is a pure DB attribute and a
transition never moves files (see docs/reference/data-migrations.md). This
script relocates the existing bucket content to match the new code.

The ``wip/`` and ``published/`` slug sets are disjoint, so this is a
conflict-free union — no per-slug merge. Copies are server-side Xet-hash copies
(no data transfer for audio/peaks). The copy is **idempotent**: a file whose
destination already exists is skipped, so a re-run only moves the delta — run
once for the bulk, then again right before the deploy to catch any last-minute
edits. (If a slug somehow existed under both prefixes, first-writer-wins via the
skip; today the sets are disjoint so this never triggers.)

Default = copy only; the old ``wip/`` + ``published/`` trees are left in place
as the rollback. After confirming the deploy reads from ``reciters/``, run
``--delete-old`` to remove them.

Usage::

    # dev bucket (default)
    python3 inspector/scripts/migrate_to_reciters_prefix.py --verify

    # prod (explicit two-key opt-in)
    python3 inspector/scripts/migrate_to_reciters_prefix.py \\
        --bucket prod --allow-prod --verify

    # cleanup, only after the deploy is confirmed reading reciters/
    python3 inspector/scripts/migrate_to_reciters_prefix.py \\
        --bucket prod --allow-prod --delete-old
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("migrate_to_reciters_prefix")

_BUCKETS = {
    "dev": "hetchyy/quranic-inspector-bucket-dev",
    "prod": "hetchyy/quranic-inspector-bucket",
}
_LEGACY_PREFIXES = ("wip", "published")
_DEST_PREFIX = "reciters"


def _setup_paths_and_env(bucket: str, *, allow_prod: bool) -> None:
    here = Path(__file__).resolve()
    repo = here.parents[2]
    sys.path.insert(0, str(repo / "inspector"))
    sys.path.insert(0, str(repo))
    os.environ["INSPECTOR_BUCKET_REPO"] = _BUCKETS[bucket]
    if bucket == "prod" and allow_prod:
        # Clears the local-process prod-write guard in hf_bucket.resolve_bucket_repo.
        os.environ["INSPECTOR_ALLOW_PROD_BUCKET"] = "1"


def _list_files(bucket_id: str, token: str | None, prefix: str) -> list[str]:
    """All blob paths (recursive) under ``prefix`` on the bucket."""
    from huggingface_hub import list_bucket_tree  # type: ignore[import-not-found]

    try:
        items = list_bucket_tree(
            bucket_id, prefix=prefix, recursive=True, token=token
        )
    except Exception as e:  # noqa: BLE001
        log.warning("list_bucket_tree(%s) failed: %s", prefix, e)
        return []
    want = prefix.rstrip("/") + "/"
    out: list[str] = []
    for it in items:
        if getattr(it, "type", "file") == "directory":
            continue  # object stores have no real dirs; be defensive anyway
        p = getattr(it, "path", None)
        if p and p.startswith(want):
            out.append(p)
    return out


def _dest_for(src: str, prefix: str) -> str:
    """``<prefix>/<slug>/<rest>`` -> ``reciters/<slug>/<rest>``."""
    rest = src[len(prefix) + 1:]  # strip "<prefix>/"
    return f"{_DEST_PREFIX}/{rest}"


def copy_all(backend, bucket_id: str, token: str | None, *, dry_run: bool) -> dict:
    copied = skipped = failed = 0
    for prefix in _LEGACY_PREFIXES:
        files = _list_files(bucket_id, token, prefix)
        log.info("%s/: %d files", prefix, len(files))
        for src in files:
            dst = _dest_for(src, prefix)
            try:
                if backend.exists(dst):
                    skipped += 1
                    continue
            except Exception:  # noqa: BLE001
                pass
            if dry_run:
                log.info("[dry-run] copy %s -> %s", src, dst)
                copied += 1
                continue
            try:
                backend.copy(src, dst)
                copied += 1
            except Exception as e:  # noqa: BLE001
                log.error("copy FAILED %s -> %s: %s", src, dst, e)
                failed += 1
    log.info(
        "copy summary: copied=%d skipped(existing)=%d failed=%d",
        copied, skipped, failed,
    )
    return {"copied": copied, "skipped": skipped, "failed": failed}


def verify(backend, bucket_id: str, token: str | None) -> bool:
    ok = True
    for prefix in _LEGACY_PREFIXES:
        files = _list_files(bucket_id, token, prefix)
        missing: list[str] = []
        for src in files:
            dst = _dest_for(src, prefix)
            try:
                present = backend.exists(dst)
            except Exception:  # noqa: BLE001
                present = False
            if not present:
                missing.append(dst)
        log.info(
            "verify %s/: %d source files, %d missing under reciters/",
            prefix, len(files), len(missing),
        )
        for m in missing[:20]:
            log.warning("  MISSING: %s", m)
        if missing:
            ok = False
    log.info("VERIFY %s", "OK" if ok else "FAILED")
    return ok


def delete_old(backend, bucket_id: str, token: str | None, *, dry_run: bool) -> int:
    deleted = 0
    for prefix in _LEGACY_PREFIXES:
        files = _list_files(bucket_id, token, prefix)
        log.info("delete %s/: %d files", prefix, len(files))
        for src in files:
            if dry_run:
                log.info("[dry-run] delete %s", src)
                deleted += 1
                continue
            try:
                backend.delete(src)
                deleted += 1
            except Exception as e:  # noqa: BLE001
                log.error("delete FAILED %s: %s", src, e)
    log.info("delete summary: deleted=%d", deleted)
    return deleted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bucket", choices=sorted(_BUCKETS), default="dev")
    ap.add_argument("--allow-prod", action="store_true",
                    help="Required acknowledgement to touch the prod bucket.")
    ap.add_argument("--verify", action="store_true",
                    help="After copy, assert every source file exists under reciters/.")
    ap.add_argument("--delete-old", action="store_true",
                    help="Delete wip/ + published/ (run only after the deploy reads reciters/).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print actions without copying/deleting.")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.bucket == "prod" and not args.allow_prod:
        raise SystemExit("Refusing to touch the prod bucket without --allow-prod.")

    _setup_paths_and_env(args.bucket, allow_prod=args.allow_prod)

    from services.storage.hf_bucket import get_backend, resolve_bucket_repo
    backend = get_backend()
    bucket_id = resolve_bucket_repo()
    token = os.environ.get("INSPECTOR_HF_TOKEN") or os.environ.get("HF_TOKEN")
    log.info("bucket=%s delete_old=%s dry_run=%s", bucket_id, args.delete_old, args.dry_run)

    if args.delete_old:
        delete_old(backend, bucket_id, token, dry_run=args.dry_run)
        return 0

    copy_all(backend, bucket_id, token, dry_run=args.dry_run)
    if args.verify and not args.dry_run:
        if not verify(backend, bucket_id, token):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
