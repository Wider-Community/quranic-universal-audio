"""Drift check: compare current validate output against the canonical snapshot.

Usage:
    python bench/drift.py <slug>          # check one slug; exit 0 = identical, 1 = drift
    python bench/drift.py --all           # check every WIP slug; exit 0 only if ALL pass
    python bench/drift.py --slugs a,b,c   # check a comma-separated list

Drift is failure-loud — prints the diff so we know exactly which items/categories
diverged from the canonical snapshot.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSPECTOR = REPO_ROOT / "inspector"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(INSPECTOR))

from services import data_dir  # noqa: E402
from services.cache import invalidate_seg_caches  # noqa: E402
from services.validation import validate_reciter_segments  # noqa: E402

# Reuse snapshot's normalize() / item_sort_key() so semantically-identical
# outputs compare equal across runs.
sys.path.insert(0, str(REPO_ROOT / "bench"))
from snapshot import item_sort_key, normalize  # noqa: E402

GROUND_TRUTH = REPO_ROOT / "bench" / "ground_truth"


def diff_category(name: str, expected: list, actual: list, *, max_items: int = 5) -> list[str]:
    """Return human-readable diff lines for one category, capped to max_items."""
    diffs: list[str] = []
    if len(expected) != len(actual):
        diffs.append(f"    Count: expected {len(expected)}, got {len(actual)}")

    exp_by = {item_sort_key(e): e for e in expected}
    act_by = {item_sort_key(a): a for a in actual}

    missing_keys = sorted(set(exp_by) - set(act_by))
    extra_keys = sorted(set(act_by) - set(exp_by))

    if missing_keys:
        sample = [exp_by[k] for k in missing_keys[:max_items]]
        diffs.append(f"    Missing ({len(missing_keys)}): {json.dumps(sample, ensure_ascii=False)}")
    if extra_keys:
        sample = [act_by[k] for k in extra_keys[:max_items]]
        diffs.append(f"    Extra ({len(extra_keys)}): {json.dumps(sample, ensure_ascii=False)}")

    changed = 0
    for k in sorted(set(exp_by) & set(act_by)):
        if exp_by[k] != act_by[k]:
            if changed < max_items:
                diffs.append(
                    f"    Changed: {k}\n"
                    f"      expected: {json.dumps(exp_by[k], ensure_ascii=False)}\n"
                    f"      actual:   {json.dumps(act_by[k], ensure_ascii=False)}"
                )
            changed += 1
    if changed > max_items:
        diffs.append(f"    ... +{changed - max_items} more changed items")
    return diffs


def check_one(slug: str) -> bool:
    """Return True on identical, False on drift. Prints diff to stdout on drift."""
    gt_path = GROUND_TRUTH / f"{slug}.json"
    if not gt_path.exists():
        print(f"[{slug}] ERROR: no ground truth at {gt_path}", file=sys.stderr)
        return False
    expected = json.loads(gt_path.read_text(encoding="utf-8"))
    invalidate_seg_caches(slug)
    actual = normalize(validate_reciter_segments(slug))

    if expected == actual:
        print(f"[{slug}] PASS")
        return True

    print(f"[{slug}] FAIL")

    # category_counts
    e_cc = expected.get("category_counts", {}) or {}
    a_cc = actual.get("category_counts", {}) or {}
    if e_cc != a_cc:
        print("  category_counts:")
        for cat in sorted(set(e_cc) | set(a_cc)):
            if e_cc.get(cat) != a_cc.get(cat):
                print(f"    {cat}: expected {e_cc.get(cat)}, got {a_cc.get(cat)}")

    # per-category lists
    for key in sorted(set(expected.keys()) | set(actual.keys())):
        if key in ("category_counts", "stats", "low_confidence_v2_meta"):
            continue
        e_val = expected.get(key)
        a_val = actual.get(key)
        if e_val == a_val:
            continue
        if not isinstance(e_val, list) and not isinstance(a_val, list):
            print(f"  {key}: expected={e_val}, got={a_val}")
            continue
        print(f"  category '{key}':")
        for d in diff_category(key, e_val or [], a_val or []):
            print(d)

    # stats — numeric tolerance handled by normalize() (3-decimal rounding)
    if expected.get("stats") != actual.get("stats"):
        print(f"  stats:")
        print(f"    expected: {expected.get('stats')}")
        print(f"    actual:   {actual.get('stats')}")

    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("slug", nargs="?", help="single slug to check")
    group.add_argument("--all", action="store_true", help="check every WIP slug")
    group.add_argument("--slugs", help="comma-separated slugs to check")
    args = ap.parse_args()

    if args.all:
        slugs = sorted(data_dir.list_slugs("wip"))
    elif args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
    else:
        slugs = [args.slug]

    all_pass = True
    for slug in slugs:
        ok = check_one(slug)
        all_pass = all_pass and ok

    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
