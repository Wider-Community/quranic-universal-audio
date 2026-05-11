"""Promote the full dedup catalog + 864 sidecars to the bucket.

Replaces the vocab-only stub uploaded by ``seed_catalog_stub`` with the real
catalog produced by the dedup pipeline in ``.local/dedup/``. Should be run
once when the dedup artifacts are present + verified.

Sources:
- ``.local/dedup/reciter_catalog.json`` → ``<bucket>/catalog/reciter_catalog.json``
- ``.local/dedup/audio_manifest/<slug>.json`` (864 sidecars) →
  ``<bucket>/catalog/audio_manifest/<slug>.json``

Validates both shapes through ``scripts.lib.schemas`` before upload — refuses
to promote if anything fails to parse.

Idempotent: re-running overwrites the same bucket paths.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ._env import load_repo_env, repo_root

load_repo_env()

from huggingface_hub import batch_bucket_files

from scripts.lib.schemas import AudioManifestSidecar, ReciterCatalog
from inspector.services import storage_paths
from inspector.services.hf_bucket import get_backend


def main() -> int:
    root = repo_root()
    dedup_dir = root / ".local" / "dedup"
    catalog_path = dedup_dir / "reciter_catalog.json"
    sidecar_dir = dedup_dir / "audio_manifest"

    if not catalog_path.exists():
        print(f"FAIL: {catalog_path} not found", file=sys.stderr)
        print(
            "Did the dedup pipeline run in this worktree? "
            "Catalog promotion requires .local/dedup/ artifacts.",
            file=sys.stderr,
        )
        return 1
    if not sidecar_dir.is_dir():
        print(f"FAIL: {sidecar_dir} not found", file=sys.stderr)
        return 1

    # ---- Validate catalog ----
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog = ReciterCatalog.model_validate(raw)
    print(
        f"ok  catalog validates: schema_version={catalog.schema_version}, "
        f"reciters={len(catalog.reciters)}, deliveries={len(catalog.deliveries)}, "
        f"generated_at={catalog.generated_at}"
    )

    # ---- Validate all sidecars ----
    sidecar_files = sorted(sidecar_dir.glob("*.json"))
    failed: list[tuple[str, str]] = []
    for f in sidecar_files:
        try:
            sd = json.loads(f.read_text(encoding="utf-8"))
            AudioManifestSidecar.model_validate(sd)
        except Exception as e:  # noqa: BLE001
            failed.append((f.name, f"{type(e).__name__}: {str(e)[:160]}"))
    if failed:
        print(f"FAIL: {len(failed)}/{len(sidecar_files)} sidecars failed to validate", file=sys.stderr)
        for name, err in failed[:5]:
            print(f"  {name}: {err}", file=sys.stderr)
        return 1
    print(f"ok  {len(sidecar_files)} sidecars validate")

    # ---- Confirm slugs match between catalog deliveries + sidecar filenames ----
    delivery_slugs = {d.slug for d in catalog.deliveries}
    sidecar_slugs = {f.stem for f in sidecar_files}
    missing_sidecars = delivery_slugs - sidecar_slugs
    orphan_sidecars = sidecar_slugs - delivery_slugs
    if missing_sidecars:
        print(
            f"WARN: {len(missing_sidecars)} deliveries have no sidecar (proceeding): "
            f"{sorted(missing_sidecars)[:5]}",
            file=sys.stderr,
        )
    if orphan_sidecars:
        print(
            f"WARN: {len(orphan_sidecars)} sidecars have no matching delivery (proceeding): "
            f"{sorted(orphan_sidecars)[:5]}",
            file=sys.stderr,
        )

    # ---- Upload ----
    bucket = os.environ.get(
        "INSPECTOR_BUCKET_REPO", "hetchyy/quranic-inspector-bucket-dev"
    )
    # Construct the backend so login() runs once. We then upload raw bytes via
    # batch_bucket_files — preserves the artifact's exact serialization (no
    # round-trip through pydantic's json dumper). Validation already passed
    # above; bucket bytes match the dedup output bit-for-bit.
    get_backend()

    pairs: list[tuple[str, str]] = [
        (str(catalog_path.resolve()), storage_paths.catalog_path()),
    ]
    for f in sidecar_files:
        pairs.append(
            (str(f.resolve()), storage_paths.audio_manifest_path(f.stem))
        )

    print(f"uploading {len(pairs)} files to bucket {bucket} (catalog + {len(sidecar_files)} sidecars) ...")
    chunk = 200
    for i in range(0, len(pairs), chunk):
        batch_bucket_files(bucket, add=pairs[i : i + chunk])
        print(f"  uploaded {min(i + chunk, len(pairs))}/{len(pairs)}")

    # Drop the in-memory catalog cache so the next Inspector boot re-hydrates
    # from the promoted artifact (rather than the vocab-only stub).
    from inspector.services import catalog as catalog_service

    catalog_service.hydrate()
    snap = catalog_service.snapshot()
    print(
        f"ok  catalog promotion complete; backend now sees "
        f"reciters={len(snap.reciters)}, deliveries={len(snap.deliveries)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
