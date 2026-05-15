"""Reconcile cutover-seeded slugs with the v2 catalog's canonical delivery slugs.

Phase 1's cutover seed used the v1 ``data/recitation_segments/<slug>/``
directory names verbatim (e.g. ``maher_al_meaqli``). The v2 dedup pipeline
applied 114 naming-style corrections (see Phase 1 outcomes log), so the
canonical reciter_ids in the catalog differ from the v1 directory names:

    v1 dir name (bucket today)            canonical reciter_id (catalog)
    -----------------------------------   --------------------------------
    maher_al_meaqli                       maher_al_muaiqly
    mishary_alafasi                       mishary_rashid_al_afasy
    mohammed_siddiq_al_minshawi           mohammed_siddiq_al_minshawi  (no change)
    nasser_alqatami                       nasser_al_qatami
    saad_al_ghamdi                        saad_al_ghamdi               (no change)
    yasser_al_dosari                      yasser_al_dosari             (no change)

All 6 published deliveries are ``mp3quran by_surah Hafs Murattal``
(confirmed via ``segments.json _meta.audio_source``), so the canonical
delivery slug is ``<canonical_reciter_id>_mp3quran``.

The catalog already has the correct reciter + delivery + sidecar entries
under the canonical names. This script just moves the bucket bytes + state
file slugs to match — no catalog patching needed.

Steps:
1. Move ``published/<v1_name>/...`` → ``published/<canonical_delivery_slug>/...``
   (segments + detailed + edit_history + edit_history_peaks + low_confidence_v2
   at the root, plus 114 timestamps shards).
2. Update ``state/reciter_state.json``: the 6 ``reciters[].slug`` flip from
   v1 names to canonical delivery slugs.

Idempotent: re-running detects what's already moved.
"""

from __future__ import annotations

import os
import sys

from ._env import load_repo_env

load_repo_env()

from huggingface_hub import batch_bucket_files, hffs, list_bucket_tree

from inspector.services import storage_paths
from inspector.services.hf_bucket import get_backend
from scripts.lib.schemas import ReciterStateFile


# Pulled from seed_state.py so the two stay in sync. Covers all 14 cutover
# reciters (6 completed + 8 wip). For each on-disk v1 slug we know the
# canonical delivery slug; the reconcile moves bucket bytes + state slugs
# to match.
from scripts.inspector_v2_seed.seed_state import CUTOVER_CANONICAL_MAP as V1_TO_CANONICAL_DELIVERY


def main() -> int:
    bucket = os.environ.get(
        "INSPECTOR_BUCKET_REPO", "hetchyy/quranic-inspector-bucket-dev"
    )
    backend = get_backend()  # forces login() once

    # ---- Sanity: every canonical target exists in the catalog ----
    from scripts.lib.schemas import ReciterCatalog

    catalog_raw = backend.read_json(storage_paths.catalog_path())
    catalog = ReciterCatalog.model_validate(catalog_raw)
    catalog_delivery_slugs = {d.slug for d in catalog.deliveries}
    missing = [
        slug
        for slug in V1_TO_CANONICAL_DELIVERY.values()
        if slug not in catalog_delivery_slugs
    ]
    if missing:
        print(
            f"FAIL: target canonical delivery slugs missing from catalog: {missing}",
            file=sys.stderr,
        )
        return 1
    print(
        f"ok  all 6 canonical delivery slugs verified in catalog "
        f"({len(catalog_delivery_slugs)} total deliveries)"
    )

    # ---- 1. Move bucket dirs (covers both wip/ and published/ subtrees) ----
    copy_ops: list[tuple[bytes, str]] = []
    delete_ops: list[str] = []
    # Process exact-prefix matches first so the "skip if already-moved" check
    # is correctly seeded by the canonical-target listing before we look at
    # broader prefixes that could shadow them.
    new_targets: set[str] = set()

    for kind in ("published", "wip"):
        for v1_name, canonical in V1_TO_CANONICAL_DELIVERY.items():
            if v1_name == canonical:
                continue
            old_prefix = f"{kind}/{v1_name}"
            new_prefix = f"{kind}/{canonical}"

            # Don't re-process if we already queued ops or files already exist at canonical.
            if new_prefix in new_targets:
                continue
            if backend.exists(f"{new_prefix}/segments.json"):
                continue

            try:
                old_entries = [
                    it.path
                    for it in list_bucket_tree(bucket, prefix=old_prefix, recursive=True)
                    if it.type == "file"
                ]
            except Exception as e:  # noqa: BLE001
                print(f"  {old_prefix}: list failed: {e}", file=sys.stderr)
                continue
            if not old_entries:
                continue

            # Filter out files that already match a different new_target prefix —
            # avoids the nested-mp3quran bug where a fuzzy prefix match returns
            # files that should belong to a more specific iteration.
            filtered: list[str] = []
            for p in old_entries:
                # Reject if this path is actually a child of some already-queued
                # new_target dir (i.e. a more-specific canonical we've already
                # processed in this same outer iteration).
                if any(p.startswith(t + "/") for t in new_targets):
                    continue
                filtered.append(p)
            if not filtered:
                continue

            for p in filtered:
                tail = p[len(old_prefix) + 1 :]
                new_path = f"{new_prefix}/{tail}"
                body = hffs.cat_file(f"buckets/{bucket}/{p}")
                copy_ops.append((body, new_path))
                delete_ops.append(p)
            new_targets.add(new_prefix)
            print(
                f"  {old_prefix:50s} queued {len(filtered):3d} files -> {new_prefix}/"
            )

    if copy_ops:
        chunk = 100
        print(f"\nuploading {len(copy_ops)} files at canonical paths ...")
        for i in range(0, len(copy_ops), chunk):
            batch_bucket_files(bucket, add=copy_ops[i : i + chunk])
            print(f"  copied {min(i + chunk, len(copy_ops))}/{len(copy_ops)}")
        print(f"deleting {len(delete_ops)} old paths ...")
        for i in range(0, len(delete_ops), chunk):
            batch_bucket_files(bucket, delete=delete_ops[i : i + chunk])
            print(f"  deleted {min(i + chunk, len(delete_ops))}/{len(delete_ops)}")
        print(f"ok  moved {len(copy_ops)} files\n")
    else:
        print("ok  no bucket files needed moving\n")

    # ---- 2. Patch state file: reciters[].slug → canonical delivery slug ----
    state_raw = backend.read_json(storage_paths.state_path())
    state_file = ReciterStateFile.model_validate(state_raw)
    state_dirty = False
    for row in state_file.reciters:
        canonical = V1_TO_CANONICAL_DELIVERY.get(row.slug)
        if canonical and row.slug != canonical:
            print(f"  state slug {row.slug:35s} -> {canonical}")
            row.slug = canonical
            state_dirty = True
    if state_dirty:
        backend.write_json_atomic(
            storage_paths.state_path(), state_file.model_dump(mode="json")
        )
        print("ok  state file rewritten with canonical delivery slugs")
    else:
        print("ok  state file already reconciled")

    print("\nok  cutover slug reconciliation complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
