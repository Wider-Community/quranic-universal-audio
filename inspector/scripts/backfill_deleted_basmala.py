"""Backfill ``pipeline_meta.json`` for legacy reciters.

The post-#5 inspector reads ``deleted_basmala_chapters`` from this sidecar
instead of re-deriving it from ``edit_history.jsonl`` on every cold
validate pass. This script derives the field for reciters that pre-date
the extraction-time write of the sidecar.

Derivation logic lives in ``scripts/lib/pipeline_meta.py::collect_deleted_basmalas``
— the same helper extraction calls, so the byte shape is identical.

The script is **deterministic**: re-running on unchanged history produces
a byte-equal sidecar. Run as a drift check after the first pass.

Usage::

    python inspector/scripts/backfill_deleted_basmala.py --slug some_reciter
    python inspector/scripts/backfill_deleted_basmala.py --all
    python inspector/scripts/backfill_deleted_basmala.py --all --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSPECTOR = _REPO_ROOT / "inspector"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_INSPECTOR) not in sys.path:
    sys.path.insert(0, str(_INSPECTOR))

from scripts.lib.pipeline_meta import collect_deleted_basmalas  # noqa: E402
from scripts.lib.schemas import PipelineMeta  # noqa: E402
from services.storage import data_dir  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def process_slug(slug: str, *, dry_run: bool) -> dict:
    """Returns a result dict with status + counts."""
    batches = list(data_dir.iter_edit_history(slug))
    if not batches:
        # No history yet → nothing was ever stripped. Still write an empty
        # sidecar so downstream callers don't hard-fail on missing file.
        deleted: set[int] = set()
    else:
        deleted = collect_deleted_basmalas(batches)

    sidecar = PipelineMeta(
        schema_version=1,
        generated_at=_utc_now_iso(),
        deleted_basmala_chapters=sorted(deleted),
    ).model_dump(mode="json")

    # Determinism check: compare against an existing sidecar (if any) to
    # confirm the derivation is stable. ``generated_at`` is excluded from
    # the comparison since it changes every run by design.
    existing = data_dir.read_pipeline_meta_doc(slug)
    drift_ok = True
    if existing is not None:
        comparable_existing = {k: v for k, v in existing.items() if k != "generated_at"}
        comparable_new = {k: v for k, v in sidecar.items() if k != "generated_at"}
        drift_ok = comparable_existing == comparable_new

    if dry_run:
        return {
            "slug": slug,
            "status": "dry_run_ok" if drift_ok else "drift_detected",
            "n_chapters": len(deleted),
            "chapters": sorted(deleted),
            "would_write_to": data_dir.pipeline_meta_path(slug),
        }

    data_dir.write_pipeline_meta_doc(slug, sidecar)
    return {
        "slug": slug,
        "status": "written" if drift_ok else "written_with_drift",
        "n_chapters": len(deleted),
        "chapters": sorted(deleted),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slug")
    g.add_argument("--slugs", help="comma-separated")
    g.add_argument("--all", action="store_true",
                   help="every reciter under reciters/")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute and report but do not write the sidecar")
    args = ap.parse_args()

    if args.all:
        slugs = sorted(data_dir.list_slugs())
    elif args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
    else:
        slugs = [args.slug]

    exit_code = 0
    for slug in slugs:
        try:
            result = process_slug(slug, dry_run=args.dry_run)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {slug}: {type(e).__name__}: {e}")
            exit_code = 1
            continue
        chs = ", ".join(str(c) for c in result["chapters"][:8])
        if len(result["chapters"]) > 8:
            chs += f", ... (+{len(result['chapters']) - 8} more)"
        print(f"{result['status']:25s} {slug}  n={result['n_chapters']:3d}  [{chs}]")
        if result["status"] in ("drift_detected", "written_with_drift"):
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
