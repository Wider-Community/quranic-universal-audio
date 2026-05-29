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

    # cleanup (two-key) — ONLY after the deploy reads reciters/ AND, for prod,
    # the quranic-universal-aligner Space no longer reads published/ from this
    # bucket (it enumerates published/ for its public reciter set). Without
    # --confirm-delete this only previews.
    python3 inspector/scripts/migrate_to_reciters_prefix.py \\
        --bucket prod --allow-prod --delete-old --confirm-delete
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


def _slugs(bucket_id: str, token: str | None, prefix: str) -> list[str]:
    """Distinct slug dirs directly under ``prefix`` on the bucket."""
    out: set[str] = set()
    for path in _list_files(bucket_id, token, prefix):
        parts = path.split("/")
        if len(parts) >= 2:
            out.add(parts[1])
    return sorted(out)


def copy_all(bucket_id: str, token: str | None, *, dry_run: bool) -> dict:
    """Server-side per-slug copy of wip/ + published/ into reciters/.

    Uses ``huggingface_hub.copy_files`` directory copy, which transfers
    Xet-tracked files by content hash (instant, no download/upload) and only
    auto-falls-back to read+reupload for the few non-Xet small files — the
    per-file ``BucketBackend.copy`` path read+reuploaded everything (its
    ``get_bucket_file_metadata`` returns no xet_hash) and was ~1000× slower.
    Re-running is cheap: existing Xet files re-copy by hash in place.
    """
    from huggingface_hub import copy_files  # type: ignore[import-not-found]

    copied = failed = 0
    for prefix in _LEGACY_PREFIXES:
        slugs = _slugs(bucket_id, token, prefix)
        log.info("%s/: %d slugs", prefix, len(slugs))
        for slug in slugs:
            src = f"hf://buckets/{bucket_id}/{prefix}/{slug}/"
            dst = f"hf://buckets/{bucket_id}/{_DEST_PREFIX}/{slug}/"
            if dry_run:
                log.info("[dry-run] copy_files %s -> %s", src, dst)
                copied += 1
                continue
            try:
                copy_files(src, dst)
                copied += 1
                log.info("copied %s -> %s", src, dst)
            except Exception as e:  # noqa: BLE001
                log.error("copy_files FAILED %s -> %s: %s", src, dst, e)
                failed += 1
    log.info("copy summary: slugs_copied=%d failed=%d", copied, failed)
    return {"slugs_copied": copied, "failed": failed}


def verify(backend, bucket_id: str, token: str | None) -> bool:
    existing = set(_list_files(bucket_id, token, _DEST_PREFIX))
    ok = True
    for prefix in _LEGACY_PREFIXES:
        files = _list_files(bucket_id, token, prefix)
        missing = [
            _dest_for(src, prefix)
            for src in files
            if _dest_for(src, prefix) not in existing
        ]
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
    ap.add_argument("--confirm-delete", action="store_true",
                    help="Second key for --delete-old; without it, --delete-old only previews.")
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
        if args.bucket == "prod":
            log.warning(
                "PROD --delete-old: the quranic-universal-aligner Space still "
                "reads published/<slug>/ from this bucket (read-only mount; "
                "repo_loader._list_published_delivery_slugs). Migrate that Space "
                "off published/ FIRST — otherwise its preload (reciter dropdown + "
                "segments/timestamps) breaks irreversibly when published/ is gone."
            )
        if not args.confirm_delete:
            log.warning(
                "--delete-old needs --confirm-delete to actually delete; "
                "showing a dry-run preview instead."
            )
            delete_old(backend, bucket_id, token, dry_run=True)
            return 0
        delete_old(backend, bucket_id, token, dry_run=args.dry_run)
        return 0

    copy_all(bucket_id, token, dry_run=args.dry_run)
    if args.verify and not args.dry_run:
        if not verify(backend, bucket_id, token):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
