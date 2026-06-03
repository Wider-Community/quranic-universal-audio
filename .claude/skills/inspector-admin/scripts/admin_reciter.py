"""One-shot full-state dump for a reciter — DB + bucket + jobs.

  admin_reciter.py SLUG                       # dev bucket
  admin_reciter.py SLUG --prod
  admin_reciter.py SLUG --prod --transitions 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def _hdr(title: str) -> None:
    print(); print(f"── {title} " + "─" * (60 - len(title)))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("slug")
    p.add_argument("--transitions", type=int, default=10,
                   help="recent transitions count (default: 10)")
    bs.add_common_args(p, mutating=False)
    a = p.parse_args()
    ctx = bs.setup(a, need_actor=False)

    from services.admin import timestamps_jobs  # noqa: E402
    from services.state import state as state_service  # noqa: E402
    from services import db as _db  # noqa: E402

    row = state_service.get_row(a.slug)
    if row is None:
        print(f"unknown slug {a.slug}", file=sys.stderr); return 4

    _hdr("state")
    print(f"slug:           {row.slug}")
    print(f"state:          {row.state.value}")
    print(f"marked_ready:   {row.marked_ready}")
    print(f"assignee_login: {getattr(row, 'assignee_login', None) or '—'}")
    print(f"assignee_hf_id: {getattr(row, 'assignee_hf_id', None) or '—'}")
    print(f"job_ids: {list(getattr(row, 'timestamps_job_ids', []) or [])}")

    _hdr(f"last {a.transitions} transitions")
    conn = _db.get_conn()
    rows = conn.execute(
        "select ts, event, from_state, to_state, actor_login_snapshot, reason "
        "from transitions where slug=? order by ts desc limit ?",
        (a.slug, a.transitions)).fetchall()
    for r in rows:
        print(f"  {r[0]}  {r[1]:<32s}  {r[2] or '—':<18s} → {r[3] or '—':<18s}  "
              f"by {r[4] or '—':<14s}  {r[5] or ''}")

    _hdr("ts jobs")
    for rec in timestamps_jobs.list_job_records(a.slug):
        print(f"  {rec.get('job_id'):42s}  {rec.get('status','?'):>10s}  "
              f"started={bs.fmt_iso(rec.get('started_at'))}  "
              f"ended={bs.fmt_iso(rec.get('ended_at'))}")

    _hdr("bucket files (reciters/<slug>/)")
    from huggingface_hub import HfFileSystem  # noqa: E402
    fs = HfFileSystem()
    base = f"hf://buckets/{ctx.bucket_id}/reciters/{a.slug}"
    info = fs.find(base, detail=True)
    files = [(k, v) for k, v in info.items() if v.get("type") == "file"]
    print(f"  {len(files)} files, "
          f"{sum(v.get('size', 0) for _, v in files) / 1e9:.2f} GB total")
    # Show the standard sidecar JSON presence
    KEYS = ("detailed.json", "segments.json", "pipeline_meta.json",
            "ts_validation.json", "low_confidence_v2.json", "auto_split_v1.json",
            "edit_history.jsonl", "edit_history_peaks.jsonl",
            "audio/_done.json")
    fmap = {k.split(f"/reciters/{a.slug}/", 1)[-1]: v for k, v in files}
    for k in KEYS:
        v = fmap.get(k)
        mark = "✓" if v else "·"
        sz = bs.fmt_size(v.get("size") if v else None)
        print(f"  [{mark}] {k:<32s}  {sz}")
    audio_n = sum(1 for k in fmap if k.startswith("audio/") and k.endswith(".mp3"))
    peaks_n = sum(1 for k in fmap if k.startswith("peaks/") and k.endswith(".json.gz"))
    ts_n = sum(1 for k in fmap if k.startswith("timestamps/")
               and (k.endswith(".json") or k.endswith(".json.gz")))
    print(f"  audio mp3s:   {audio_n}/114")
    print(f"  peaks shards: {peaks_n}/114")
    print(f"  ts shards:    {ts_n}/114")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
