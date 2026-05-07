"""Migrate a reciter's segment boundaries from symmetric `pad_ms` to
asymmetric `pad_left_ms`/`pad_right_ms`/`min_silence_floor_ms` without
re-extracting from audio.

Strategy: peel the recorded symmetric pad off each non-frozen segment to
recover its cleaned VAD bound, then re-pad with the new params. Frozen
(human-edited) bounds are preserved verbatim and act as walls for
neighbour pad allocation.

A segment is *frozen* if any historical operation has explicitly
modified its `time_start` or `time_end`. Operations that only touch
`matched_ref` / `matched_text` (auto_fix_missing_word, edit_reference,
confirm_reference, ignore_issue) leave bounds unchanged and do not
freeze.

Outputs:
- Rewrites detailed.json + segments.json with new bounds and new _meta
  fields (`pad_left_ms`, `pad_right_ms`, `min_silence_floor_ms`).
- Appends a `pad_migration` audit batch to edit_history.jsonl with
  one operation per shifted segment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Allow `from inspector.utils.uuid7 import uuid7` etc.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inspector.utils.uuid7 import uuid7  # noqa: E402

# Boundary-modifying op types — kept for documentation. Actual freeze
# decision is bound-diff based (more robust against new op types).
BOUND_MODIFYING_OPS = {
    "trim_segment", "split_segment", "merge_segments",
    "waqf_sakt", "auto_fix_boundary",
}


def _utc_now_ms() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _seg_snapshot(seg: dict, index: int) -> dict:
    return {
        "segment_uid": seg.get("segment_uid"),
        "index_at_save": index,
        "audio_url": seg.get("audio_url"),
        "time_start": seg["time_start"],
        "time_end": seg["time_end"],
        "matched_ref": seg.get("matched_ref", ""),
        "matched_text": seg.get("matched_text", ""),
        "confidence": seg.get("confidence", 0.0),
    }


def collect_frozen_uids(history_path: Path) -> set:
    """Walk edit_history.jsonl. Freeze any UID that ever had its
    time_start or time_end mutated by an op."""
    frozen: set = set()
    if not history_path.exists():
        return frozen
    for line in history_path.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("record_type") == "genesis":
            continue
        for op in rec.get("operations", []):
            tb = op.get("targets_before") or []
            ta = op.get("targets_after") or []
            # 1. Same-UID bound diff (trim_segment, possibly others)
            by_uid_before = {
                t.get("segment_uid"): t for t in tb if t.get("segment_uid")
            }
            for a in ta:
                uid = a.get("segment_uid")
                if not uid:
                    continue
                b = by_uid_before.get(uid)
                if b is None:
                    # New UID introduced by this op (split / merge / waqf_sakt
                    # / auto-deleted-then-recreated). Always freeze — its
                    # bounds were chosen by the op, not by extraction.
                    frozen.add(uid)
                    continue
                if (a.get("time_start") != b.get("time_start")
                        or a.get("time_end") != b.get("time_end")):
                    frozen.add(uid)
    return frozen


def pad_with_walls(
    intervals: list[tuple[int, int]],
    pl_ms: int,
    pr_ms: int,
    fl_ms: int,
    left_wall: Optional[int],
    right_wall: Optional[int],
) -> list[tuple[int, int]]:
    """Apply asymmetric pad to a contiguous run of cleaned intervals
    bounded by hard walls (frozen-segment bounds, or audio start/end).

    Internal gaps split proportionally after reserving floor.
    Outer endpoints clamp against the walls — full pad if the wall is
    audio start/end (left_wall=0 or right_wall=None), else `pad - floor`
    against a frozen neighbour to preserve the daylight guarantee.
    """
    n = len(intervals)
    if n == 0:
        return []
    left_pad = [0] * n
    right_pad = [0] * n
    want = pl_ms + pr_ms

    # Internal gaps
    for i in range(n - 1):
        gap = max(0, intervals[i + 1][0] - intervals[i][1])
        budget = max(0, gap - fl_ms)
        if want == 0:
            continue
        if budget >= want:
            right_pad[i] = pr_ms
            left_pad[i + 1] = pl_ms
        else:
            right_pad[i] = budget * pr_ms // want
            left_pad[i + 1] = budget * pl_ms // want

    # First seg's left pad: cap against left_wall.
    if left_wall is None or left_wall == 0:
        # Audio start — full pad clamped at 0
        avail = intervals[0][0]
        left_pad[0] = min(pl_ms, max(0, avail))
    else:
        avail = intervals[0][0] - left_wall
        left_pad[0] = max(0, min(pl_ms, avail - fl_ms))

    # Last seg's right pad: cap against right_wall.
    if right_wall is None:
        right_pad[-1] = pr_ms
    else:
        avail = right_wall - intervals[-1][1]
        right_pad[-1] = max(0, min(pr_ms, avail - fl_ms))

    out = []
    for i, (s, e) in enumerate(intervals):
        ns = s - left_pad[i]
        ne = e + right_pad[i]
        if left_wall is not None and i == 0:
            ns = max(ns, left_wall)
        ns = max(0, ns)
        if right_wall is not None and i == n - 1:
            ne = min(ne, right_wall)
        out.append((ns, ne))
    return out


def migrate_entry(
    entry: dict,
    old_pad_ms: int,
    pl_ms: int,
    pr_ms: int,
    fl_ms: int,
    frozen: set,
) -> list[dict]:
    """Mutate entry["segments"] bounds in place. Returns list of
    (uid, before_bounds, after_bounds) for segments whose bounds shifted."""
    segs = entry.get("segments", [])
    n = len(segs)
    if n == 0:
        return []

    # Per-seg "is frozen?" mask.
    is_frozen = [seg.get("segment_uid") in frozen for seg in segs]

    # Walk maximal runs of consecutive non-frozen segments.
    shifts = []
    i = 0
    while i < n:
        if is_frozen[i]:
            i += 1
            continue
        j = i
        while j < n and not is_frozen[j]:
            j += 1
        # Run is segs[i:j]
        # Peel old pad to recover cleaned bounds
        cleaned = []
        for k in range(i, j):
            ts = int(segs[k]["time_start"])
            te = int(segs[k]["time_end"])
            cs = ts + old_pad_ms
            ce = te - old_pad_ms
            # Defensive: peel could over-shrink for a tiny seg (shouldn't
            # happen since min_speech filters those, but be safe).
            if ce < cs:
                cs, ce = ts, te
            cleaned.append((cs, ce))
        # Walls
        left_wall = segs[i - 1]["time_end"] if i > 0 else 0
        right_wall = segs[j]["time_start"] if j < n else None
        new_bounds = pad_with_walls(
            cleaned, pl_ms, pr_ms, fl_ms, left_wall, right_wall,
        )
        for k_off, (ns, ne) in enumerate(new_bounds):
            k = i + k_off
            ts_old = int(segs[k]["time_start"])
            te_old = int(segs[k]["time_end"])
            if ns != ts_old or ne != te_old:
                shifts.append({
                    "segment_uid": segs[k].get("segment_uid"),
                    "index_at_save": k,
                    "before": {"time_start": ts_old, "time_end": te_old},
                    "after": {"time_start": int(ns), "time_end": int(ne)},
                })
                segs[k]["time_start"] = int(ns)
                segs[k]["time_end"] = int(ne)
        i = j
    return shifts


def rebuild_segments_json(entries: list, meta: dict, segments_path: Path) -> None:
    verse_data: dict[str, list[list]] = defaultdict(list)
    for entry in entries:
        for seg in entry.get("segments", []):
            ref = seg.get("matched_ref", "")
            if not ref or ref in (
                "Basmala", "Isti'adha", "Amin", "Takbir",
                "Tahmeed", "Tasleem", "Sadaqa",
            ):
                continue
            parts = ref.split("-")
            if len(parts) != 2:
                continue
            sp, ep = parts[0].split(":"), parts[1].split(":")
            if len(sp) != 3 or len(ep) != 3:
                continue
            s_sura, s_ayah, s_word = int(sp[0]), int(sp[1]), int(sp[2])
            e_ayah, e_word = int(ep[1]), int(ep[2])
            key = f"{s_sura}:{s_ayah}" if s_ayah == e_ayah else ref
            row = [s_word, e_word, seg["time_start"], seg["time_end"]]
            wrap_ranges = seg.get("wrap_word_ranges")
            if wrap_ranges:
                row.append({"wrap_word_ranges": wrap_ranges})
            verse_data[key].append(row)

    def _key(k):
        return tuple(int(x) for x in k.split("-")[0].split(":"))

    seg_doc = {"_meta": meta}
    for key in sorted(verse_data, key=_key):
        seg_doc[key] = verse_data[key]
    with open(segments_path, "w", encoding="utf-8") as f:
        json.dump(seg_doc, f, ensure_ascii=False)


def migrate(
    reciter_dir: Path,
    pl_ms: int = 150,
    pr_ms: int = 500,
    fl_ms: int = 30,
    dry_run: bool = False,
) -> None:
    detailed_path = reciter_dir / "detailed.json"
    segments_path = reciter_dir / "segments.json"
    history_path = reciter_dir / "edit_history.jsonl"

    detailed = json.loads(detailed_path.read_text())
    meta = dict(detailed.get("_meta", {}))
    entries = detailed.get("entries", [])

    old_pad_ms = int(meta.get("pad_ms", 0))
    if old_pad_ms == 0:
        # Already migrated or genesis used new fields — bail unless forced
        if "pad_left_ms" in meta:
            print(f"  ! {reciter_dir.name}: already on asymmetric pad — skipping")
            return

    frozen = collect_frozen_uids(history_path)
    print(f"  frozen UIDs (bounds touched by edits): {len(frozen)}")

    all_shifts = []
    for entry in entries:
        shifts = migrate_entry(entry, old_pad_ms, pl_ms, pr_ms, fl_ms, frozen)
        try:
            ch = int(str(entry.get("ref", "")).split(":")[0])
        except (ValueError, IndexError):
            ch = None
        for s in shifts:
            s["chapter"] = ch
            s["entry_ref"] = entry.get("ref")
            s["matched_ref"] = entry.get("segments", [])[s["index_at_save"]].get("matched_ref", "")
        all_shifts.extend(shifts)

    print(f"  shifted {len(all_shifts)} segments "
          f"(of {sum(len(e.get('segments', [])) for e in entries)} total)")

    if dry_run:
        print(f"  DRY RUN — no files written")
        return

    # Update meta
    meta["pad_left_ms"] = pl_ms
    meta["pad_right_ms"] = pr_ms
    meta["min_silence_floor_ms"] = fl_ms
    # Keep pad_ms as a back-compat shim (legacy readers expect 2*pad_ms ≈ L+R)
    meta["pad_ms"] = (pl_ms + pr_ms) // 2
    meta["pad_migrated_at"] = _utc_now_ms()
    meta["pad_migrated_from_pad_ms"] = old_pad_ms

    # Write detailed.json
    with open(detailed_path, "w", encoding="utf-8") as f:
        json.dump({"_meta": meta, "entries": entries}, f, ensure_ascii=False)
    rebuild_segments_json(entries, meta, segments_path)

    # Append audit batch — one batch per chapter to mirror existing convention
    file_hash = "sha256:" + hashlib.sha256(detailed_path.read_bytes()).hexdigest()
    now = _utc_now_ms()
    by_chapter = defaultdict(list)
    for s in all_shifts:
        by_chapter[s["chapter"]].append(s)

    with open(history_path, "a", encoding="utf-8") as f:
        for chapter, shifts in sorted(by_chapter.items(), key=lambda x: (x[0] is None, x[0])):
            ops = []
            for s in shifts:
                ops.append({
                    "op_id": uuid7(),
                    "op_type": "pad_migration",
                    "op_context_category": None,
                    "fix_kind": "auto_fix",
                    "started_at_utc": now,
                    "applied_at_utc": now,
                    "ready_at_utc": now,
                    "targets_before": [{
                        "segment_uid": s["segment_uid"],
                        "index_at_save": s["index_at_save"],
                        "audio_url": None,
                        "time_start": s["before"]["time_start"],
                        "time_end": s["before"]["time_end"],
                        "matched_ref": s.get("matched_ref", ""),
                        "matched_text": "",
                        "confidence": 1.0,
                    }],
                    "targets_after": [{
                        "segment_uid": s["segment_uid"],
                        "index_at_save": s["index_at_save"],
                        "audio_url": None,
                        "time_start": s["after"]["time_start"],
                        "time_end": s["after"]["time_end"],
                        "matched_ref": s.get("matched_ref", ""),
                        "matched_text": "",
                        "confidence": 1.0,
                    }],
                })
            batch = {
                "schema_version": 1,
                "batch_id": uuid7(),
                "batch_type": "pad_migration",
                "reciter": reciter_dir.name,
                "chapter": chapter,
                "saved_at_utc": now,
                "save_mode": "full_replace",
                "file_hash_after": file_hash,
                "validation_summary_before": {},
                "validation_summary_after": {},
                "extraction_params": {
                    "pad_ms_before": old_pad_ms,
                    "pad_left_ms": pl_ms,
                    "pad_right_ms": pr_ms,
                    "min_silence_floor_ms": fl_ms,
                },
                "operations": ops,
            }
            f.write(json.dumps(batch, ensure_ascii=False) + "\n")

    print(f"  wrote detailed.json + segments.json + edit_history.jsonl")
    print(f"  new _meta: pad_left_ms={pl_ms} pad_right_ms={pr_ms} "
          f"min_silence_floor_ms={fl_ms}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reciter_dir", type=Path,
                    help="Path to data/recitation_segments/<reciter>/")
    ap.add_argument("--pad-left", type=int, default=150)
    ap.add_argument("--pad-right", type=int, default=500)
    ap.add_argument("--min-silence-floor", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"\n=== migrating {args.reciter_dir.name} ===")
    migrate(
        args.reciter_dir,
        pl_ms=args.pad_left,
        pr_ms=args.pad_right,
        fl_ms=args.min_silence_floor,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
