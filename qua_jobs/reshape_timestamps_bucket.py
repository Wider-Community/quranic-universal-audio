#!/usr/bin/env python3
"""One-off bucket executor for the timestamps RESHAPE migration.

Reshapes existing ``reciters/<slug>/timestamps/<ch>.json.gz`` shards from the v2
occurrence-list to the temporal segment-array shape **in place on an HF bucket**,
and deletes any stale uncompressed ``<ch>.json`` shadowed by a sibling ``.json.gz``.

This is the bucket-write counterpart to the pure transform in
``qua_shared/timestamps_reshape.py`` (and the local-dir dry-run CLI in
``reshape_timestamps_shards.py``). It reuses ``reshape_shard`` / ``classify_shard``
so the on-bucket result is byte-shape identical to a freshly-generated shard.

Safety:
  - DRY-RUN by default; ``--execute`` is required to write/delete.
  - Refuses the PROD bucket unless ``INSPECTOR_ALLOW_PROD_BUCKET=1`` (mirrors
    ``services/storage/hf_bucket.resolve_bucket_repo``).
  - Touches ONLY canonical ``<ch>.json.gz`` shards (digit stem); skips
    ``<ch>.beam_N.json.gz`` probe sidecars and never reshapes a ``v1``/``target``
    shard (idempotent + leaves regeneration-only shards untouched).

The coordinated cutover ordering (deploy new code, reshape, restart to clear the
shard LRU) lives in ``docs/planning/ts-segment-array-migration.md`` — this script
is just the reshape step.
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys
from pathlib import Path

# Allow ``python qua_jobs/reshape_timestamps_bucket.py`` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qua_shared.timestamps_reshape import classify_shard, reshape_shard  # noqa: E402
from qua_shared.timestamps_shards import gzip_shard  # noqa: E402

DEV_BUCKET = "hetchyy/quranic-inspector-bucket-dev"
PROD_BUCKET = "hetchyy/quranic-inspector-bucket"


def _token() -> str | None:
    return os.environ.get("INSPECTOR_HF_TOKEN") or os.environ.get("HF_TOKEN")


def _login(token: str | None) -> None:
    if token:
        from huggingface_hub import login

        login(token=token, add_to_git_credential=False)


def _uri(bucket: str, path: str) -> str:
    return f"buckets/{bucket}/{path}"


def _list_timestamps(bucket: str, slug: str, token: str | None) -> list[str]:
    """Return basenames under ``reciters/<slug>/timestamps`` (non-recursive)."""
    from huggingface_hub import list_bucket_tree

    prefix = f"reciters/{slug}/timestamps"
    try:
        items = list_bucket_tree(bucket, prefix=prefix, recursive=False, token=token)
    except Exception as e:  # noqa: BLE001 — missing dir → no shards
        if (
            isinstance(e, FileNotFoundError)
            or getattr(getattr(e, "response", None), "status_code", None) == 404
        ):
            return []
        raise
    return sorted(it.path.split("/")[-1] for it in items)


def _read(bucket: str, path: str) -> bytes:
    from huggingface_hub import hffs

    return hffs.cat_file(_uri(bucket, path))


def _write(bucket: str, path: str, data: bytes, token: str | None) -> None:
    from huggingface_hub import batch_bucket_files, hffs

    batch_bucket_files(bucket, add=[(data, path)], token=token)
    try:
        hffs.invalidate_cache(_uri(bucket, path))
    except Exception:  # noqa: BLE001
        pass


def _delete(bucket: str, path: str, token: str | None) -> None:
    from huggingface_hub import batch_bucket_files, hffs

    batch_bucket_files(bucket, delete=[path], token=token)
    try:
        hffs.invalidate_cache(_uri(bucket, path))
    except Exception:  # noqa: BLE001
        pass


def _digit_stem(name: str) -> bool:
    return name.split(".", 1)[0].isdigit()


def reshape_reciter(bucket: str, slug: str, *, execute: bool, token: str | None) -> dict:
    """Reshape every canonical ``<ch>.json.gz`` for ``slug``; delete shadowed ``.json``."""
    names = _list_timestamps(bucket, slug, token)
    gz = [n for n in names if n.endswith(".json.gz") and _digit_stem(n)]
    plain = {
        n for n in names if n.endswith(".json") and not n.endswith(".json.gz") and _digit_stem(n)
    }

    stats = {
        "slug": slug,
        "gz_total": len(gz),
        "reshaped": 0,
        "skipped": {},
        "stale_json_deleted": 0,
        "bytes_before": 0,
        "bytes_after": 0,
        "errors": [],
    }
    for name in sorted(gz, key=lambda n: int(n.split(".", 1)[0])):
        path = f"reciters/{slug}/timestamps/{name}"
        try:
            raw = _read(bucket, path)
            import json

            doc = json.loads(gzip.decompress(raw))
            kind = classify_shard(doc)
            if kind != "v2":
                stats["skipped"][kind] = stats["skipped"].get(kind, 0) + 1
                continue
            out = reshape_shard(doc)
            body = gzip_shard(out)
            stats["bytes_before"] += len(raw)
            stats["bytes_after"] += len(body)
            stats["reshaped"] += 1
            if execute:
                _write(bucket, path, body, token)
        except Exception as e:  # noqa: BLE001
            stats["errors"].append(f"{name}: {type(e).__name__}: {e}")

    # Stale uncompressed shards shadowed by a sibling .gz (audit cleanup).
    shadowed = sorted(p for p in plain if f"{p}.gz" in set(gz))
    for name in shadowed:
        path = f"reciters/{slug}/timestamps/{name}"
        if execute:
            _delete(bucket, path, token)
        stats["stale_json_deleted"] += 1
    stats["stale_json_shadowed"] = shadowed
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--bucket", default=DEV_BUCKET, help=f"HF bucket repo id (default {DEV_BUCKET})"
    )
    ap.add_argument("--reciter", action="append", default=[], help="slug to reshape (repeatable)")
    ap.add_argument("--execute", action="store_true", help="write/delete (default: dry-run)")
    args = ap.parse_args()

    if args.bucket == PROD_BUCKET and os.environ.get("INSPECTOR_ALLOW_PROD_BUCKET") != "1":
        print(
            f"REFUSED: {PROD_BUCKET} is the PROD bucket. Set INSPECTOR_ALLOW_PROD_BUCKET=1 "
            "to reshape prod (coordinated cutover only).",
            file=sys.stderr,
        )
        return 2
    if not args.reciter:
        print("ERROR: pass at least one --reciter <slug>.", file=sys.stderr)
        return 2

    token = _token()
    _login(token)
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"[{mode}] bucket={args.bucket} reciters={args.reciter}\n")

    grand = {"reshaped": 0, "stale_deleted": 0, "errors": 0}
    for slug in args.reciter:
        s = reshape_reciter(args.bucket, slug, execute=args.execute, token=token)
        delta = s["bytes_after"] - s["bytes_before"]
        pct = (100.0 * delta / s["bytes_before"]) if s["bytes_before"] else 0.0
        print(
            f"{slug}: {s['gz_total']} gz | reshaped={s['reshaped']} "
            f"skipped={s['skipped'] or '{}'} stale_json={s['stale_json_deleted']} "
            f"| bytes {s['bytes_before']}->{s['bytes_after']} ({pct:+.1f}%)"
        )
        if s["stale_json_shadowed"]:
            print(f"   stale shadowed .json: {s['stale_json_shadowed']}")
        for err in s["errors"]:
            print(f"   ERROR {err}")
        grand["reshaped"] += s["reshaped"]
        grand["stale_deleted"] += s["stale_json_deleted"]
        grand["errors"] += len(s["errors"])

    print(
        f"\nTOTAL: reshaped={grand['reshaped']} stale_json_deleted={grand['stale_deleted']} "
        f"errors={grand['errors']}  ({mode})"
    )
    if not args.execute:
        print("Re-run with --execute to write.")
    return 1 if grand["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
