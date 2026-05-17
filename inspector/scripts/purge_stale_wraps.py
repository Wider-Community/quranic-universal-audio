"""One-off: strip stale ``wrap_word_ranges`` from segments where the wrap
geometry does not match the segment's ``matched_ref``.

Two failure modes are detected:

1. **Stale (split-inheritance):** a parent repetition seg was split into N
   pieces; the inherited wrap describes the parent's read sequence and no
   longer fits any individual child. Detected when any wrap entry references
   a word position outside the child's ``matched_ref`` word range. Fix
   (now landed): apply-command split drops wrap on every piece, save_payload
   no longer auto-resurrects from existing. This script back-fills the data
   that was already corrupted before the fix.

2. **Corrupted (pipeline-original):** wrap geometry that can't represent any
   valid reading sequence — e.g. ``repeat_end`` lies before ``jump_to`` in
   surah word order. Two known cases (raad_al_kurdi 4:128, abdulwadood 3:153)
   look like aligner false positives. Stripping is safe; flag in report so
   the segs can be re-aligned later if needed.

Both fixes also drop ``has_repeated_words`` since the seg no longer
represents a multi-pass reading.

Dry-run by default. Pass ``--apply`` to actually mutate the bucket.
By default scans both ``wip/`` and ``published/``; pass ``--wip-only`` to
restrict.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import orjson

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import data_dir, storage_paths
from services.hf_bucket import StorageNotFound, get_backend
from utils.repetitions import _word_position, is_wrap_consistent


# ---------------------------------------------------------------------------
# Wrap classification — split the consistency check into stale vs corrupted
# so the report can distinguish split-inheritance leaks from pipeline bugs.
# ---------------------------------------------------------------------------

def _parse_word_ref(r: str) -> tuple[int, int, int] | None:
    p = r.split(":")
    if len(p) != 3:
        return None
    try:
        return int(p[0]), int(p[1]), int(p[2])
    except ValueError:
        return None


def classify_wrap(matched_ref: str, wrap: list, vwc: dict) -> str | None:
    """Return ``None`` if the wrap is consistent with ``matched_ref``;
    otherwise ``"stale"`` (outside matched_ref range) or ``"corrupted"``
    (geometry inconsistent or unparseable).
    """
    if is_wrap_consistent(matched_ref, wrap, vwc):
        return None
    # Re-classify the failure reason for the report.
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return "corrupted"
    rf = _parse_word_ref(parts[0])
    rt = _parse_word_ref(parts[1])
    if not rf or not rt or rf[0] != rt[0]:
        return "corrupted"
    surah = rf[0]
    rf_pos = _word_position(rf, vwc)
    rt_pos = _word_position(rt, vwc)
    if rf_pos is None or rt_pos is None:
        return None
    for w in wrap:
        if not isinstance(w, list) or len(w) < 3:
            return "corrupted"
        wt = _parse_word_ref(w[0])
        wf = _parse_word_ref(w[1])
        we = _parse_word_ref(w[2])
        if not wt or not wf or not we or wt[0] != surah or wf[0] != surah or we[0] != surah:
            return "corrupted"
        wt_pos = _word_position(wt, vwc)
        wf_pos = _word_position(wf, vwc)
        we_pos = _word_position(we, vwc)
        if wt_pos is None or wf_pos is None or we_pos is None:
            return None
        if wf_pos < wt_pos or we_pos < wt_pos:
            return "corrupted"
        for p in (wt_pos, wf_pos, we_pos):
            if p < rf_pos or p > rt_pos:
                return "stale"
    return None


# ---------------------------------------------------------------------------
# Per-reciter pass
# ---------------------------------------------------------------------------

def process_slug(backend, slug: str, kind: str, *, vwc: dict, apply: bool,
                 stamp: str) -> dict:
    path = storage_paths.detailed_path(slug, kind)
    try:
        raw = backend.read_bytes(path)
    except StorageNotFound:
        return {"slug": slug, "kind": kind, "status": "missing",
                "wraps_total": 0, "wraps_stale": 0, "wraps_corrupted": 0,
                "segs_modified": 0, "details": []}

    doc = orjson.loads(raw)
    n_total = n_stale = n_corrupt = n_mod = 0
    details: list[dict] = []
    for entry in doc.get("entries", []):
        for seg in entry.get("segments", []):
            wrap = seg.get("wrap_word_ranges")
            if not wrap:
                continue
            n_total += 1
            verdict = classify_wrap(seg.get("matched_ref", ""), wrap, vwc)
            if verdict is None:
                continue
            if verdict == "stale":
                n_stale += 1
            else:
                n_corrupt += 1
            n_mod += 1
            details.append({
                "ref": seg.get("matched_ref", ""),
                "uid": seg.get("segment_uid", ""),
                "time_start": seg.get("time_start"),
                "time_end": seg.get("time_end"),
                "wrap": wrap,
                "verdict": verdict,
            })
            if apply:
                seg.pop("wrap_word_ranges", None)
                # Migration #5: has_repeated_words is no longer written by any
                # path. Keep the pop for in-place purges on legacy on-disk data.
                seg.pop("has_repeated_words", None)

    result = {
        "slug": slug, "kind": kind, "status": "ok",
        "wraps_total": n_total, "wraps_stale": n_stale,
        "wraps_corrupted": n_corrupt, "segs_modified": n_mod,
        "details": details,
    }

    if apply and n_mod:
        backup_path = f"archive/stale_wraps/{slug}/detailed.json.{stamp}.bak"
        backend.write_bytes_atomic(backup_path, raw)
        new_raw = orjson.dumps(doc, option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE)
        backend.write_bytes_atomic(path, new_raw)
        result["status"] = "applied"
        result["backup_path"] = backup_path
    elif apply:
        result["status"] = "noop"
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_word_counts() -> dict:
    """Eager numpy-free import of get_word_counts."""
    from services.data_loader import get_word_counts
    return get_word_counts()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Mutate the bucket (default: dry-run, only report)")
    ap.add_argument("--wip-only", action="store_true",
                    help="Skip published/ slugs (default: scan both tiers)")
    ap.add_argument("--slug", help="Process only this slug (debugging)")
    ap.add_argument("--show-details", action="store_true",
                    help="Print per-seg details (always shown when --slug)")
    args = ap.parse_args()

    backend = get_backend()
    vwc = _load_word_counts()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    targets: list[tuple[str, str]] = []
    if args.slug:
        # Try wip first then published
        for k in ("wip", "published"):
            try:
                backend.read_bytes(storage_paths.detailed_path(args.slug, k))
                targets.append((args.slug, k))
                break
            except StorageNotFound:
                continue
        if not targets:
            print(f"slug {args.slug!r} not found in wip or published")
            return 1
    else:
        for s in data_dir.list_slugs("wip"):
            targets.append((s, "wip"))
        if not args.wip_only:
            for s in data_dir.list_slugs("published"):
                targets.append((s, "published"))

    print(f"Mode:    {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Stamp:   {stamp}")
    print(f"Targets: {len(targets)}")
    print()

    rows: list[dict] = []
    for slug, kind in targets:
        rows.append(process_slug(backend, slug, kind, vwc=vwc, apply=args.apply,
                                 stamp=stamp))

    fmt = "{:<42} {:<10} {:<8} {:>6} {:>6} {:>9} {:>6}"
    print(fmt.format("slug", "kind", "status", "wraps", "stale", "corrupted", "modif"))
    print("-" * 96)
    tot_wraps = tot_stale = tot_corrupt = tot_mod = 0
    for r in rows:
        if r["wraps_total"] == 0 and not args.show_details:
            continue
        print(fmt.format(r["slug"][:42], r["kind"], r["status"],
                         r["wraps_total"], r["wraps_stale"],
                         r["wraps_corrupted"], r["segs_modified"]))
        tot_wraps += r["wraps_total"]
        tot_stale += r["wraps_stale"]
        tot_corrupt += r["wraps_corrupted"]
        tot_mod += r["segs_modified"]
    print("-" * 96)
    print(fmt.format("TOTAL", "", "",
                     tot_wraps, tot_stale, tot_corrupt, tot_mod))
    print()

    if args.show_details or args.slug:
        for r in rows:
            if not r["details"]:
                continue
            print(f"=== {r['slug']} ({r['kind']}) — {len(r['details'])} segs to clean")
            for d in r["details"]:
                print(f"  [{d['verdict']:<9}] ref={d['ref']:<22} "
                      f"ts=[{d['time_start']},{d['time_end']}]  wrap={d['wrap']}")
            print()

    if not args.apply and tot_mod:
        print(f"Dry-run: would strip wrap from {tot_mod} segs across {sum(1 for r in rows if r['segs_modified'])} reciters.")
        print("Re-run with --apply to mutate the bucket (backups go to archive/stale_wraps/).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
