"""Backfill ``is_boundary_adj`` per-segment in ``detailed.json``.

Stamps the result of ``compute_is_boundary_adj`` (the classifier's raw
boundary-adjustment rule, structural + phonemic side) onto every segment
in ``detailed.json`` so the validate fast-path can skip the per-segment
computation.

Parallel-then-promote flow (same shape as backfill_qalqala_letter.py):
1. Read ``wip/<slug>/detailed.json``.
2. Compute ``is_boundary_adj`` for every seg using the same classifier
   helper the runtime path uses — passes ``canonical`` phonemes so the
   phonemic side fires identically to today's validate output.
3. Write the augmented doc to ``archive/backfill/<slug>/detailed.json``.
4. Run validate in-memory against the backfilled bytes, compare to
   ``bench/ground_truth/<slug>.json``; abort on drift.
5. On byte-equivalent match: atomically promote to ``wip/<slug>/detailed.json``.

The Inspector runtime never reads canonical phonemes — the persisted
``is_boundary_adj`` already captures the phonemic-side detections at
backfill time. This script is the sole ``quranic_phonemizer`` consumer
in the project and rebuilds canonical phonemes in-memory on each
invocation; no on-disk cache.

Usage:
    python inspector/scripts/backfill_boundary_adj.py --slug bandar_baleela_mp3quran
    python inspector/scripts/backfill_boundary_adj.py --all-wip
    python inspector/scripts/backfill_boundary_adj.py --slug X --dry-run
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
from services import state as state_service  # noqa: E402
from services.data_loader import get_word_counts, load_detailed  # noqa: E402
from services.hf_bucket import get_backend  # noqa: E402
from services.validation import validate_reciter_segments  # noqa: E402
from services.validation.classifier import compute_is_boundary_adj  # noqa: E402

try:
    from quranic_phonemizer import Phonemizer  # noqa: E402
    _HAS_PHONEMIZER = True
except Exception:
    _HAS_PHONEMIZER = False

_BACKFILL_DIR = "archive/backfill"
_PHONEMIZER_SINGLETON: object | None = None


def _build_canonical_phonemes(slug: str) -> dict[str, list[str]] | None:
    """Phonemize the entire Quran with this reciter's segment-end stop refs.

    Returns ``{word_location_key: [phoneme, ...]}`` or ``None`` if the
    phonemizer isn't installed / no segments are loaded. Recomputed per
    backfill invocation; this script is offline and runs once per slug so
    caching across runs is not worth the disk dependency.
    """
    global _PHONEMIZER_SINGLETON
    if not _HAS_PHONEMIZER:
        return None
    entries = load_detailed(slug)
    if not entries:
        return None
    stop_refs: set[str] = set()
    for entry in entries:
        for seg in entry.get("segments", []):
            matched_ref = seg.get("matched_ref", "")
            if not matched_ref:
                continue
            parts = matched_ref.split("-")
            if len(parts) == 2:
                stop_refs.add(parts[1])
    if _PHONEMIZER_SINGLETON is None:
        _PHONEMIZER_SINGLETON = Phonemizer()
    result = _PHONEMIZER_SINGLETON.phonemize(ref="1-114", stop_refs=list(stop_refs))
    return {word.location.location_key: word.get_phonemes() for word in result._words}


def _stamp_entries(entries: list[dict], single_word_verses: set, canonical: dict | None) -> tuple[int, int]:
    """Mutate entries in place; return (segs_stamped, n_with_boundary_adj)."""
    n = 0
    fires = 0
    for entry in entries:
        for seg in entry.get("segments", []):
            n += 1
            matched_ref = seg.get("matched_ref") or ""
            parts = matched_ref.split("-")
            if len(parts) != 2:
                seg["is_boundary_adj"] = False
                continue
            sp = parts[0].split(":")
            ep = parts[1].split(":")
            if len(sp) != 3 or len(ep) != 3:
                seg["is_boundary_adj"] = False
                continue
            try:
                surah = int(sp[0])
                s_ayah = int(sp[1])
                s_word = int(sp[2])
                e_word = int(ep[2])
            except ValueError:
                seg["is_boundary_adj"] = False
                continue
            val = compute_is_boundary_adj(
                seg, surah, s_ayah, s_word, e_word, single_word_verses, canonical,
            )
            seg["is_boundary_adj"] = val
            if val:
                fires += 1
    return n, fires


def _normalize_for_drift(result: dict) -> dict:
    sys.path.insert(0, str(_REPO_ROOT / "bench"))
    from snapshot import normalize  # noqa: E402
    return normalize(result)


def _drift_check_against_ground_truth(slug: str) -> tuple[bool, str]:
    gt_path = _REPO_ROOT / "bench" / "ground_truth" / f"{slug}.json"
    if not gt_path.exists():
        return False, f"no ground truth at {gt_path}"
    expected = json.loads(gt_path.read_text(encoding="utf-8"))
    actual = _normalize_for_drift(validate_reciter_segments(slug))
    if expected == actual:
        return True, "ok"
    e_cc = expected.get("category_counts", {})
    a_cc = actual.get("category_counts", {})
    diffs = []
    for cat in sorted(set(e_cc) | set(a_cc)):
        if e_cc.get(cat) != a_cc.get(cat):
            diffs.append(f"{cat}={e_cc.get(cat)}->{a_cc.get(cat)}")
    return False, "counts diff: " + ("; ".join(diffs) or "(deep field diff — run bench/drift.py)")


def _archive_path(slug: str) -> str:
    return f"{_BACKFILL_DIR}/{slug}/detailed.json"


def process_slug(slug: str, *, dry_run: bool) -> dict:
    backend = get_backend()
    raw = data_dir.read_detailed_bytes(slug)
    if raw is None:
        return {"slug": slug, "status": "missing"}

    meta, entries = load_entries_from_bytes(raw)
    word_counts = get_word_counts()
    single_word_verses = {k for k, v in word_counts.items() if v == 1}
    canonical = _build_canonical_phonemes(slug)  # None if phonemizer missing

    n_segs, n_fires = _stamp_entries(entries, single_word_verses, canonical)
    augmented_doc = {"_meta": meta or {}, "entries": entries}

    cache.invalidate_seg_caches(slug)
    cache.set_seg_cache(slug, entries)
    if meta:
        cache.set_seg_meta(slug, meta)

    drift_ok, drift_msg = _drift_check_against_ground_truth(slug)
    if not drift_ok:
        return {
            "slug": slug, "status": "drift_fail",
            "n_segs": n_segs, "n_fires": n_fires,
            "msg": drift_msg,
        }

    if dry_run:
        return {
            "slug": slug, "status": "dry_run_ok",
            "n_segs": n_segs, "n_fires": n_fires,
            "would_write_archive": _archive_path(slug),
            "would_promote_to": data_dir.detailed_path(slug),
        }

    backend.write_json_atomic(_archive_path(slug), augmented_doc)
    backend.write_json_atomic(data_dir.detailed_path(slug), augmented_doc)
    cache.invalidate_seg_caches(slug)
    cache.set_seg_cache(slug, entries)
    if meta:
        cache.set_seg_meta(slug, meta)
    return {"slug": slug, "status": "promoted", "n_segs": n_segs, "n_fires": n_fires}


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slug")
    g.add_argument("--all-wip", action="store_true")
    g.add_argument("--all-published", action="store_true")
    g.add_argument("--all", action="store_true",
                   help="both wip + published")
    g.add_argument("--slugs", help="comma-separated")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Hydrate state so data_dir.kind_for resolves wip vs published correctly.
    state_service.hydrate()

    if args.all_wip:
        slugs = sorted(data_dir.list_slugs("wip"))
    elif args.all_published:
        slugs = sorted(data_dir.list_slugs("published"))
    elif args.all:
        slugs = sorted(data_dir.list_slugs("wip")) + sorted(data_dir.list_slugs("published"))
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
            print(f"OK  segs={r['n_segs']}  is_boundary_adj=true count={r['n_fires']}  ({r['status']})")
        elif r["status"] == "drift_fail":
            print(f"DRIFT FAIL  segs={r['n_segs']}  fires={r['n_fires']}\n    {r['msg']}")
        else:
            print(r["status"])

    return 1 if any(r["status"] not in ("promoted", "dry_run_ok") for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
