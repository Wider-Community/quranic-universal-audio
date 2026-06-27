#!/usr/bin/env python3
"""Fetch cross-verse waṣl/waqf annotation data for reciter(s) from a bucket.

A *cross-verse* boundary is created when a reviewer SPLITS a compound segment
that spanned two verses (``17:2:1-17:3:9`` → ``17:2`` + ``17:3``) and marks the
join **waṣl** (continued, no stop → ``is_wasl=True``) or **waqf** (stopped →
``is_wasl=False``). The choice rides on the split's first child; a later
``set_is_wasl`` pill toggle can override it.

GROUND TRUTH is the edit-history replay (split after-state + later ``set_is_wasl``,
latest non-null wins), reconciled with ``detailed.json`` (which also carries
auto-detected waṣl that never went through a manual edit). Per boundary:
  waṣl        — authoritative is_wasl True (phonemize continuously across the join)
  waqf        — authoritative is_wasl False (a real stop; do NOT phonemize as waṣl)
  unannotated — a cross-verse split with no waṣl/waqf choice (legacy: split before
                the waṣl feature shipped). Treated as waqf by the pipeline (safe).

Usage:
  cross_verse_wasl.py                                   # dev, all reciters, table
  cross_verse_wasl.py --bucket prod --reciter husary    # one reciter (substring)
  cross_verse_wasl.py --bucket prod --chapter 56         # one chapter, all reciters
  cross_verse_wasl.py --bucket all --status wasl --json   # waṣl only, JSON, dev+prod

KNOWN DEFERRED DISCREPANCIES (detailed.json ↔ edit_history; later set_is_wasl pill
toggle did not re-materialize into detailed.json — inspector materialization fix
deferred). Verdicts confirmed by the data owner:
  • mahmoud_khalil_al_husary_mujawwad_tarteel  56:66  → waṣl   (detailed.json missing it)
  • abdulwadood_haneef_mp3quran                39:14  → waqf   (toggle was wrong; detailed.json correct)
  • abdul_hamid_ghraio_2025_yt / _2026_yt      (e.g. 14:24) → waṣl (detailed.json missing it)
This script reports the *authoritative* (replayed) status, so these three already
read correctly here; the deferred work is fixing detailed.json/the inspector.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bucket"))
import _bootstrap as bs  # noqa: E402, I001  (must follow the sys.path insert)


# Owner-confirmed verdicts for the 3 deferred detailed.json↔edit_history
# discrepancies (a later set_is_wasl pill toggle the replay alone can't
# adjudicate). Applied on top of the replay so this script reports GROUND TRUTH;
# the upstream detailed.json / inspector-materialization fix is DEFERRED.
#   husary_mujawwad 56:66 → waṣl (replay agrees; detailed.json is the stale one)
#   haneef          39:14 → waqf (replay says waṣl, but the toggle was wrong)
#   ghraio 2025/2026      → waṣl (replay already agrees; no override needed)
VERDICT_OVERRIDES = {
    ("mahmoud_khalil_al_husary_mujawwad_tarteel", "56:66→56:67"): "wasl",
    ("abdulwadood_haneef_mp3quran", "39:14→39:15"): "waqf",
}


def _vparts(mref: str):
    """(first_verse, last_verse) as (surah, ayah) from a matched_ref; None on junk."""
    for p in ("Basmala+", "Isti'adha+"):
        if mref.startswith(p):
            mref = mref[len(p):]
    parts = mref.split("-")
    try:
        a = parts[0].split(":")
        b = parts[-1].split(":")
        return (int(a[0]), int(a[1])), (int(b[0]), int(b[1]))
    except (ValueError, IndexError):
        return None, None


def replay_is_wasl(edit_history_lines: list[str]):
    """Replay edit_history → (uid→authoritative is_wasl, uid→(vN,vN+1) for cross-verse
    split first-children). Only an EXPLICIT non-null is_wasl is an annotation;
    unrelated ops carry the seg with is_wasl absent→None and must not clobber."""
    rows = []
    for ln in edit_history_lines:
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        sa = rec.get("saved_at_utc", "")
        for op in rec.get("operations", []):
            rows.append((sa, op))
    rows.sort(key=lambda x: x[0])
    uid_wasl: dict[str, bool] = {}
    split_boundary: dict[str, tuple] = {}
    for _sa, op in rows:
        ot = op.get("op_type") or op.get("kind")
        after = (op.get("patch") or {}).get("after") or []
        if ot == "split_segment" and op.get("op_context_category") == "cross_verse" and len(after) >= 2:
            (_, last0) = _vparts(after[0].get("matched_ref", ""))
            (first1, _) = _vparts(after[1].get("matched_ref", ""))
            uid0 = after[0].get("segment_uid")
            if uid0 and last0 and first1:
                split_boundary[uid0] = (last0, first1)
        for s in after:
            uid = s.get("segment_uid")
            if uid and s.get("is_wasl") is not None:
                uid_wasl[uid] = bool(s["is_wasl"])
    return uid_wasl, split_boundary


def reciter_boundaries(fs, bucket_id: str, reciter: str, chapter: int | None):
    """Yield {chapter, junction, status, source} for each reviewed cross-verse boundary."""
    base = bs.abs_path(bucket_id, f"reciters/{reciter}")
    try:
        detailed = json.loads(fs.open(f"{base}/detailed.json", "rb").read())
    except FileNotFoundError:
        return
    try:
        eh = fs.open(f"{base}/edit_history.jsonl", "rb").read().decode("utf-8", "replace").splitlines()
    except FileNotFoundError:
        eh = []
    uid_wasl, split_boundary = replay_is_wasl(eh)

    for entry in detailed.get("entries", []):
        segs = [s for s in entry.get("segments", []) if (s.get("matched_ref") or "").count(":")]
        segs.sort(key=lambda s: s.get("time_start", 0))
        for i, seg in enumerate(segs):
            uid = seg.get("segment_uid")
            is_split = uid in split_boundary
            explicit = uid in uid_wasl
            if not is_split and not explicit and not seg.get("is_wasl"):
                continue  # not a reviewed cross-verse junction
            # verse pair
            if is_split:
                (vN, vN1) = split_boundary[uid]
            else:
                _, last = _vparts(seg.get("matched_ref", ""))
                nxt = segs[i + 1] if i + 1 < len(segs) else None
                first = _vparts(nxt.get("matched_ref", ""))[0] if nxt else None
                if not (last and first):
                    continue
                vN, vN1 = last, first
            if not (vN1[0] == vN[0] and vN1[1] == vN[1] + 1):
                continue  # not actually consecutive cross-verse
            ch = vN[0]
            if chapter is not None and ch != chapter:
                continue
            if explicit:
                status, source = ("wasl" if uid_wasl[uid] else "waqf"), "edit"
            elif seg.get("is_wasl"):
                status, source = "wasl", "auto"
            else:
                status, source = "unannotated", "legacy-split"
            junction = f"{vN[0]}:{vN[1]}→{vN1[0]}:{vN1[1]}"
            ov = VERDICT_OVERRIDES.get((reciter, junction))
            if ov:
                status, source = ov, "owner-verdict"
            yield {"chapter": ch, "junction": junction, "status": status, "source": source}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bucket", choices=["dev", "prod", "all"], default="dev")
    p.add_argument("--reciter", help="reciter slug (substring match); default all")
    p.add_argument("--chapter", type=int, help="restrict to one chapter (surah number)")
    p.add_argument("--status", choices=["wasl", "waqf", "unannotated", "all"], default="all")
    p.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    a = p.parse_args()
    bs.ensure_utf8_stdout()
    bs.load_hf_token()
    from huggingface_hub import HfFileSystem
    fs = HfFileSystem()

    bucket_ids = (["dev", "prod"] if a.bucket == "all" else [a.bucket])
    out = []
    for bkey in bucket_ids:
        bid = bs.BUCKETS[bkey]
        if a.reciter:
            reciters = [r.split("/")[-1] for r in fs.ls(bs.abs_path(bid, "reciters"), detail=False)
                        if a.reciter in r.split("/")[-1]]
        else:
            reciters = [r.split("/")[-1] for r in fs.ls(bs.abs_path(bid, "reciters"), detail=False)]
        for r in sorted(reciters):
            for b in reciter_boundaries(fs, bid, r, a.chapter):
                if a.status != "all" and b["status"] != a.status:
                    continue
                out.append({"bucket": bkey, "reciter": r, **b})

    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    # table + per-reciter summary
    from collections import Counter
    cur = None
    tally = Counter()
    for row in out:
        key = (row["bucket"], row["reciter"])
        if key != cur:
            cur = key
            print(f"\n=== [{row['bucket']}] {row['reciter']} ===")
        print(f"  ch{row['chapter']:>3}  {row['junction']:18} {row['status']:11} ({row['source']})")
        tally[row["status"]] += 1
    summary = "  ".join(f"{k}={v}" for k, v in sorted(tally.items()))
    print(f"\n— totals: {summary}  (rows={len(out)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
