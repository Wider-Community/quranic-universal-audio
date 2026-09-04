#!/usr/bin/env python3
"""Mark legacy cross-verse splits as waṣl when the audio shows no stop.

A reviewer split that crossed a verse boundary before the waṣl pill existed carries no
``is_wasl`` choice, so the pipeline treats the join as waqf. The boundary-review
``false_split_v1.json`` sidecar lists the delivery boundaries every re-segmentation arm
bridged; where such a boundary is one of those unannotated splits and the recorded gap
is short, the join is waṣl. This script writes ``is_wasl: true`` on the left segment in
``detailed.json`` and appends a ``set_is_wasl`` batch to ``edit_history.jsonl`` so the
replay in ``cross_verse_wasl.py`` agrees.

Dry run by default: prints the table and writes nothing. ``--apply`` writes, after
saving the untouched ``detailed.json`` and ``edit_history.jsonl`` under ``--backup-dir``.

  backfill_legacy_wasl.py --bucket prod --reciter <slug> --sidecar <false_split_v1.json>
  backfill_legacy_wasl.py --bucket prod --reciter <slug> --sidecar ... --apply --yes-prod
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bucket"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import _bootstrap as bs  # noqa: E402, I001  (must follow the sys.path insert)
from cross_verse_wasl import _vparts, replay_is_wasl  # noqa: E402
from qua_shared.schemas.bucket.edit_history import EditHistoryBatch  # noqa: E402

#: A bridged boundary whose recorded gap is wider than this is left for a reviewer.
MAX_GAP_MS = 200
#: Both model arms must bridge the boundary; confirming axes alone do not count.
REQUIRED_AXES = frozenset({"trio", "lite"})
BATCH_TYPE = "wasl_backfill"


def consecutive(left_ref: str, right_ref: str) -> bool:
    _, last = _vparts(left_ref)
    first, _ = _vparts(right_ref)
    return bool(last and first) and first[0] == last[0] and first[1] == last[1] + 1


def select(detailed: dict, history_lines: list[str], sidecar: dict) -> list[dict]:
    """Boundaries to mark: unannotated cross-verse splits the arms bridge with a short gap."""
    uid_wasl, split_boundary = replay_is_wasl(history_lines)
    segs = {s["segment_uid"]: s for e in detailed.get("entries", []) for s in e.get("segments", []) if s.get("segment_uid")}
    rows = []
    for uid, hit in sidecar.get("by_uid", {}).items():
        seg = segs.get(uid)
        if seg is None or seg.get("is_wasl") or uid in uid_wasl or uid not in split_boundary:
            continue
        if not REQUIRED_AXES <= set(hit.get("axes", [])) or hit["gap_ms"] > MAX_GAP_MS:
            continue
        if not consecutive(hit["ref_before"], hit["ref_after"]):
            continue
        rows.append({"uid": uid, "chapter": hit["chapter"], "gap_ms": hit["gap_ms"],
                     "junction": f"{hit['ref_before']} → {hit['ref_after']}", "seg": seg})
    return rows


def snapshot(seg: dict, chapter: int, index: int) -> dict:
    return {"segment_uid": seg["segment_uid"], "index_at_save": index, "audio_url": None,
            "time_start": seg["time_start"], "time_end": seg["time_end"],
            "matched_ref": seg.get("matched_ref", ""), "confidence": seg.get("confidence", 0),
            "chapter": chapter}


def apply(detailed: dict, rows: list[dict], reason: str) -> dict:
    """Set ``is_wasl`` on each row's segment in place; return the history batch."""
    index_of = {}
    for entry in detailed.get("entries", []):
        for i, seg in enumerate(entry.get("segments", [])):
            if seg.get("segment_uid"):
                index_of[seg["segment_uid"]] = i
    ops = []
    for row in rows:
        seg, chapter, index = row["seg"], row["chapter"], index_of[row["uid"]]
        before = snapshot(seg, chapter, index)
        seg["is_wasl"] = True
        ops.append({"op_id": str(uuid4()), "op_type": "set_is_wasl", "fix_kind": "auto_fix",
                    "op_context_category": "false_split", "targets_before": [before],
                    "targets_after": [{**snapshot(seg, chapter, index), "is_wasl": True}],
                    "patch": {"before": [before], "after": [{**snapshot(seg, chapter, index), "is_wasl": True}]},
                    "command": {"type": "set_is_wasl", "segment_uid": row["uid"], "is_wasl": True,
                                "reason": reason}})
    return {"schema_version": 1, "batch_id": str(uuid4()),
            "saved_at_utc": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "chapters": sorted({r["chapter"] for r in rows}), "batch_type": BATCH_TYPE,
            "operations": ops}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--reciter", required=True, help="reciter slug (exact)")
    p.add_argument("--sidecar", required=True, help="false_split_v1.json from the boundary review")
    p.add_argument("--apply", action="store_true", help="write to the bucket (default: dry run)")
    p.add_argument("--backup-dir", default=".local/wasl_backfill", help="where the pre-write files go")
    bs.add_bucket_args(p)
    a = p.parse_args()
    if a.apply:
        bs.confirm_mutation(a, f"backfill is_wasl for {a.reciter}")

    fs, bucket = bs.resolve(a)
    base = bs.abs_path(bucket, f"reciters/{a.reciter}")
    detailed_raw = fs.open(f"{base}/detailed.json", "rb").read()
    history_raw = fs.open(f"{base}/edit_history.jsonl", "rb").read()
    detailed = json.loads(detailed_raw)
    sidecar = json.loads(Path(a.sidecar).read_text(encoding="utf-8"))

    rows = select(detailed, history_raw.decode("utf-8", "replace").splitlines(), sidecar)
    print(f"{a.reciter}: {len(rows)} boundary(ies) to mark waṣl of {len(sidecar.get('by_uid', {}))} bridged")
    for r in rows:
        print(f"  {r['chapter']:>3}  gap {r['gap_ms']:>4} ms  {r['junction']}")
    if not rows or not a.apply:
        return 0

    backup = Path(a.backup_dir) / a.reciter / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "detailed.json").write_bytes(detailed_raw)
    (backup / "edit_history.jsonl").write_bytes(history_raw)

    batch = apply(detailed, rows, reason=f"legacy cross-verse split bridged by {sorted(REQUIRED_AXES)}, gap <= {MAX_GAP_MS} ms")
    EditHistoryBatch.model_validate(batch)  # the Inspector's history reader must parse it
    import orjson  # the Inspector's own serialiser, so the file keeps its shape

    history_out = history_raw if history_raw.endswith(b"\n") or not history_raw else history_raw + b"\n"
    bs.batch_write(bucket, {
        f"reciters/{a.reciter}/detailed.json": orjson.dumps(detailed, option=orjson.OPT_INDENT_2),
        f"reciters/{a.reciter}/edit_history.jsonl": history_out + orjson.dumps(batch) + b"\n",
    })
    print(f"wrote {len(rows)} is_wasl mark(s); backup in {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
