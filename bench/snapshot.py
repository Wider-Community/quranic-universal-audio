"""Capture canonical validation output for drift checking.

For each WIP slug, runs ``validate_reciter_segments`` in-process and writes a
normalized JSON snapshot to ``bench/ground_truth/<slug>.json``.

Also writes ``bench/results/baseline_counts.csv`` with per-reciter, per-category
counts plus TOTAL_SEGS (so we have scale awareness across reciters).
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSPECTOR = REPO_ROOT / "inspector"
# Mirror inspector/app.py: repo root first (so `scripts.lib.X` resolves), then
# INSPECTOR so `services`, `domain`, etc. import flat.
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(INSPECTOR))

from services import data_dir  # noqa: E402
from services.cache import invalidate_seg_caches  # noqa: E402
from services.data_loader import load_detailed  # noqa: E402
from services.validation import validate_reciter_segments  # noqa: E402

GROUND_TRUTH = REPO_ROOT / "bench" / "ground_truth"
RESULTS = REPO_ROOT / "bench" / "results"

# Accordion-order categories (registry-defined). Stays in lockstep with
# services/validation/registry.py + frontend's domain/registry.ts.
CATEGORIES = [
    "failed",
    "missing_verses",
    "missing_words",
    "structural_errors",
    "low_confidence",
    "low_confidence_v2",
    "repetitions",
    "audio_bleeding",
    "boundary_adj",
    "cross_verse",
    "qalqala",
    "muqattaat",
    "basmala_amin",
]


def item_sort_key(item: dict) -> str:
    """Stable sort key for a category item.

    Prefer ``segment_uid`` (most per-segment categories), else fall back to
    ``verse_key`` + ``chapter`` (per-verse categories), else a stable JSON dump.
    """
    if isinstance(item, dict):
        if "segment_uid" in item:
            return f"seg:{item['segment_uid']}"
        if "verse_key" in item:
            return f"verse:{item.get('chapter', 0)}:{item['verse_key']}"
    return f"json:{json.dumps(item, sort_keys=True, ensure_ascii=False)}"


def _round_floats(obj):
    """Recursively round floats to 3 decimals to suppress float-precision noise."""
    if isinstance(obj, float):
        return round(obj, 3)
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v) for v in obj]
    return obj


def normalize(result: dict | None) -> dict | None:
    """Sort every list deterministically and round floats. Required for
    byte-equivalent comparison of semantically-identical outputs."""
    if result is None:
        return None
    norm: dict = {}
    for k, v in result.items():
        if isinstance(v, list):
            norm[k] = sorted((_round_floats(item) for item in v), key=item_sort_key)
        else:
            norm[k] = _round_floats(v)
    return norm


def snapshot_one(slug: str) -> dict | None:
    """Compute validation and normalize. Clears caches first for a clean run."""
    invalidate_seg_caches(slug)
    return normalize(validate_reciter_segments(slug))


def main() -> int:
    GROUND_TRUTH.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)

    wip_slugs = sorted(data_dir.list_slugs("wip"))
    print(f"Capturing ground truth for {len(wip_slugs)} WIP reciter(s)...\n")

    counts_rows = []
    for slug in wip_slugs:
        print(f"  {slug:<45s}", end=" ", flush=True)
        snap = snapshot_one(slug)
        if snap is None:
            print("EMPTY (no detailed.json)")
            continue
        out_path = GROUND_TRUTH / f"{slug}.json"
        out_path.write_text(
            json.dumps(snap, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        cc = snap.get("category_counts", {})
        entries = load_detailed(slug) or []
        total_segs = sum(len(e.get("segments", [])) for e in entries)
        row = {"slug": slug}
        for c in CATEGORIES:
            row[c] = cc.get(c, 0)
        row["TOTAL_SEGS"] = total_segs
        counts_rows.append(row)
        size_kb = out_path.stat().st_size / 1024
        print(f"OK  segs={total_segs:>6d}  issues={sum(cc.values()):>5d}  snap={size_kb:.1f}KB")

    csv_path = RESULTS / "baseline_counts.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["slug", *CATEGORIES, "TOTAL_SEGS"])
        writer.writeheader()
        writer.writerows(counts_rows)
    print(f"\nWrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
