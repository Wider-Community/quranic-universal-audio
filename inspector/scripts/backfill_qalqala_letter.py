"""Backfill ``qalqala_letter`` per-segment in ``detailed.json``.

Schema: each segment under ``entries[*].segments[*]`` gets a new field
``qalqala_letter: str | None``:
- a single Arabic letter when the seg's text (derived from ``matched_ref``
  via ``dk_text_for_ref``) ends in one of the qalqala letters (ق ط ب ج د)
- ``None`` when the last letter is not a qalqala letter (or no letter exists)

Computed by reusing ``utils.arabic_text.last_arabic_letter`` + the qalqala
check from ``services.validation.classifier`` — byte-equivalent to runtime.

Parallel-then-promote flow (safe rollback):
1. Read ``reciters/<slug>/detailed.json``, compute the field for every seg.
2. Write the augmented doc to ``archive/backfill/<slug>/detailed.json``.
3. Run validate against the backfilled bytes IN-MEMORY (no bucket promotion
   yet), normalize, compare to ``bench/ground_truth/<slug>.json``.
4. Only on byte-equivalent match: atomically promote backfilled bytes to
   ``reciters/<slug>/detailed.json`` via ``data_dir.write_detailed_doc``.

Usage:
    python inspector/scripts/backfill_qalqala_letter.py --slug bandar_baleela_mp3quran
    python inspector/scripts/backfill_qalqala_letter.py --all
    python inspector/scripts/backfill_qalqala_letter.py --slug X --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSPECTOR = _REPO_ROOT / "inspector"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_INSPECTOR) not in sys.path:
    sys.path.insert(0, str(_INSPECTOR))

from adapters.detailed_json import load_entries_from_bytes  # noqa: E402
from services import cache, data_dir  # noqa: E402
from services.hf_bucket import get_backend  # noqa: E402
from services.qalqala import compute_qalqala_letter  # noqa: E402
from services.validation import validate_reciter_segments  # noqa: E402

_BACKFILL_DIR = "archive/backfill"


def _stamp_entries(entries: list[dict]) -> int:
    """Mutate *entries* in place; return count of segs stamped.

    Uses the same ``compute_qalqala_letter`` helper as save.py and the
    classifier fall-through — byte-equivalent stamping across all writers.
    """
    n = 0
    for entry in entries:
        for seg in entry.get("segments", []):
            seg["qalqala_letter"] = compute_qalqala_letter(seg)
            n += 1
    return n


def _normalize_for_drift(result: dict) -> dict:
    """Match bench/snapshot.py's normalization so drift hashing is fair."""
    sys.path.insert(0, str(_REPO_ROOT / "bench"))
    from snapshot import normalize  # noqa: E402
    return normalize(result)


def _drift_check_against_ground_truth(slug: str) -> tuple[bool, str]:
    """Run validate IN-MEMORY against currently-cached entries; compare to ground truth."""
    gt_path = _REPO_ROOT / "bench" / "ground_truth" / f"{slug}.json"
    if not gt_path.exists():
        return False, f"no ground truth at {gt_path} (run bench/snapshot.py first)"

    expected = json.loads(gt_path.read_text(encoding="utf-8"))
    # NOTE: caller has already populated seg_cache with backfilled entries.
    actual = _normalize_for_drift(validate_reciter_segments(slug))
    if expected == actual:
        return True, "ok"
    # produce a short summary
    e_cc = expected.get("category_counts", {})
    a_cc = actual.get("category_counts", {})
    diffs = []
    for cat in sorted(set(e_cc) | set(a_cc)):
        if e_cc.get(cat) != a_cc.get(cat):
            diffs.append(f"{cat}={e_cc.get(cat)}->{a_cc.get(cat)}")
    return False, "counts diff: " + ("; ".join(diffs) or "(deep field diff — run bench/drift.py for details)")


def _archive_path(slug: str) -> str:
    return f"{_BACKFILL_DIR}/{slug}/detailed.json"


def process_slug(slug: str, *, dry_run: bool) -> dict:
    """Returns a result dict with status + counts."""
    backend = get_backend()
    raw = data_dir.read_detailed_bytes(slug)
    if raw is None:
        return {"slug": slug, "status": "missing"}

    meta, entries = load_entries_from_bytes(raw)
    n_segs = _stamp_entries(entries)
    n_with_letter = sum(
        1 for e in entries for s in e.get("segments", []) if s.get("qalqala_letter")
    )
    augmented_doc = {"_meta": meta or {}, "entries": entries}

    # Prime caches so validate_reciter_segments reads the backfilled entries
    # IN-MEMORY (no bucket fetch). invalidate_seg_caches first to clear stale
    # entries/meta/etc., then set_seg_cache / set_seg_meta with new content.
    cache.invalidate_seg_caches(slug)
    cache.set_seg_cache(slug, entries)
    if meta:
        cache.set_seg_meta(slug, meta)

    drift_ok, drift_msg = _drift_check_against_ground_truth(slug)
    if not drift_ok:
        return {
            "slug": slug, "status": "drift_fail",
            "n_segs": n_segs, "n_with_letter": n_with_letter,
            "msg": drift_msg,
        }

    archive = _archive_path(slug)
    if dry_run:
        return {
            "slug": slug, "status": "dry_run_ok",
            "n_segs": n_segs, "n_with_letter": n_with_letter,
            "would_write_archive": archive,
            "would_promote_to": data_dir.detailed_path(slug),
        }

    # Step 1: write to archive/backfill/<slug>/detailed.json
    backend.write_json_atomic(archive, augmented_doc)
    # Step 2: atomically promote to reciters/<slug>/detailed.json
    backend.write_json_atomic(data_dir.detailed_path(slug), augmented_doc)
    # Refresh caches with the promoted state.
    cache.invalidate_seg_caches(slug)
    cache.set_seg_cache(slug, entries)
    if meta:
        cache.set_seg_meta(slug, meta)
    return {
        "slug": slug, "status": "promoted",
        "n_segs": n_segs, "n_with_letter": n_with_letter,
        "archive": archive,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slug")
    g.add_argument("--all", action="store_true",
                   help="every reciter under reciters/")
    g.add_argument("--slugs", help="comma-separated")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + drift-check but skip the bucket promotion")
    args = ap.parse_args()

    if args.all:
        slugs = sorted(data_dir.list_slugs())
    elif args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
    else:
        slugs = [args.slug]

    print(f"Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print(f"Slugs: {len(slugs)}")
    print()

    rows = []
    for slug in slugs:
        print(f"  {slug:<45s}", end=" ", flush=True)
        r = process_slug(slug, dry_run=args.dry_run)
        rows.append(r)
        if r["status"] in ("promoted", "dry_run_ok"):
            print(f"OK  segs={r['n_segs']}  qalqala_letters={r['n_with_letter']}  "
                  f"({r['status']})")
        elif r["status"] == "drift_fail":
            print(f"DRIFT FAIL  segs={r['n_segs']}  qalqala_letters={r['n_with_letter']}\n"
                  f"    {r['msg']}")
        else:
            print(r["status"])

    failures = [r for r in rows if r["status"] not in ("promoted", "dry_run_ok")]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
