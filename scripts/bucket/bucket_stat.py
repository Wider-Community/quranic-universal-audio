"""Summarise a bucket path: file count, total bytes, top-N largest, per-ext breakdown.

  bucket_stat.py                                       # whole bucket
  bucket_stat.py reciters/husary --bucket prod
  bucket_stat.py reciters --top 20
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", nargs="?", default="", help="path within the bucket")
    p.add_argument("--top", type=int, default=10, help="show N largest files")
    bs.add_bucket_args(p)
    a = p.parse_args()

    fs, bucket = bs.resolve(a)
    target = bs.abs_path(bucket, a.path)

    # find(detail=True) returns {path: info}; one bucket-side recursive walk.
    info = fs.find(target, detail=True)
    files = [(k, v) for k, v in info.items() if v.get("type") == "file"]

    total = sum(v.get("size", 0) for _, v in files)
    by_ext: dict[str, list[int]] = defaultdict(list)
    for k, v in files:
        ext = Path(k).suffix.lower() or "(none)"
        by_ext[ext].append(v.get("size", 0))

    print(f"path: {target}")
    print(f"files: {len(files)}  total: {bs.fmt_size(total)}")
    print()
    print("by extension:")
    print(f"  {'ext':<12s} {'count':>6s} {'total':>12s} {'mean':>10s}")
    for ext, sizes in sorted(by_ext.items(), key=lambda kv: -sum(kv[1])):
        s = sum(sizes)
        print(f"  {ext:<12s} {len(sizes):>6d} {bs.fmt_size(s):>12s} "
              f"{bs.fmt_size(s/len(sizes)):>10s}")

    if a.top > 0 and files:
        print()
        print(f"top {a.top} largest:")
        for k, v in sorted(files, key=lambda kv: -kv[1].get("size", 0))[:a.top]:
            name = k.split("/", 3)[-1]
            print(f"  {bs.fmt_size(v.get('size')):>12s}  {name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
